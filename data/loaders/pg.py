"""入库模块：把清洗后的数据写入 PostgreSQL（对齐 db/schema.sql）。

流程（每条记录）：
    1) ensure_source —— 先登记来源，拿到 source_id（可溯源的基础）
    2) stage         —— 写入 stg_import 暂存区（保留原始 JSON，可追溯/可回放）
    3) upsert        —— 按业务主键 upsert 到正式表（幂等，可重复执行）

设计要点：
    - 事实表全部通过 source_id 外键关联来源，来源缺失会在上游清洗阶段被拒收
    - 所有写入均按唯一键 upsert，重复执行结果一致（幂等）
    - school_major_score 的投档单位是「院校专业组」：主键含可空 major_id，
      入库前先把同组的多条专业级记录聚合到专业组级（取组内最低分 / 计划数求和），
      避免 major_id 为 NULL 时多行互相覆盖
    - 无数据库时本模块不会被调用（run_pipeline.py 用 --load-db 触发）

用法：
    python run_pipeline.py --load-db --dsn "postgresql://postgres:pwd@localhost:5432/zhixuan"
"""
from __future__ import annotations

import json
import logging
from collections import OrderedDict
from pathlib import Path

logger = logging.getLogger(__name__)

# 来源名称关键字 → source.source_type 枚举
SOURCE_TYPE_HINTS = {
    "河南省教育厅": "官方",
    "河南省教育考试院": "官方",
    "河南省人民政府": "官方",
    "阳光高考": "官方",
    "教育部": "官方",
    "中国教育在线": "公开网络",
    "掌上高考": "公开网络",
}

DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/zhixuan"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "db" / "schema.sql"

# 写入顺序：被引用表在前，保证外键可解析（knowledge_doc 先于 knowledge_chunk）
LOAD_ORDER = [
    "school", "major", "pathway",
    "score_segment", "batch_score_line",
    "pathway_region", "pathway_eligibility", "pathway_time",
    "school_major_score", "pathway_score",
    "enrollment_rule", "school_profile",
    "discipline_eval", "school_life",
    "knowledge_doc", "knowledge_chunk",
]


def source_type_of(name: str) -> str:
    for k, v in SOURCE_TYPE_HINTS.items():
        if k in (name or ""):
            return v
    return "公开网络"


def connect(dsn: str = DEFAULT_DSN):
    """建立 psycopg3 连接。"""
    import psycopg
    return psycopg.connect(dsn)


def init_schema(dsn: str = DEFAULT_DSN) -> None:
    """执行 db/schema.sql 建表（等价于 psql -f db/schema.sql）。"""
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with connect(dsn) as conn:
        conn.execute(sql)
    logger.info("schema applied from %s", SCHEMA_PATH)


# ---------------------------------------------------------------------------
# 基础操作
# ---------------------------------------------------------------------------
def _ensure_source(cur, name: str, url: str, year: int) -> int:
    cur.execute(
        """INSERT INTO source (source_name, source_url, year, source_type, reliability)
           VALUES (%s, %s, %s, %s, 'high')
           ON CONFLICT (source_name, source_url, year)
           DO UPDATE SET fetched_at = now()
           RETURNING id""",
        (name, url, year, source_type_of(name)),
    )
    return cur.fetchone()[0]


def _stage(cur, batch_no, doc_type, source_name, source_url, year, raw, row_no):
    """写入暂存区，保留原始 JSON。"""
    cur.execute(
        """INSERT INTO stg_import
             (batch_no, source_name, source_url, year, doc_type, raw, row_no, status)
           VALUES (%s, %s, %s, %s, %s, %s, %s, 'validated')""",
        (batch_no, source_name, source_url, year, doc_type,
         json.dumps(raw, ensure_ascii=False, default=str), row_no),
    )


def _get_or_create_school(cur, name: str | None, source_id: int,
                          province: str = "河南", code: str | None = None):
    """按院校名取 id；不存在则建一条最小记录。"""
    if not name:
        return None
    cur.execute("SELECT id FROM school WHERE name = %s", (name,))
    row = cur.fetchone()
    if row:
        if code:
            cur.execute(
                "UPDATE school SET code = COALESCE(code, %s) WHERE id = %s",
                (code, row[0]))
        return row[0]
    cur.execute(
        """INSERT INTO school (name, province, code, source_id)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (name) DO UPDATE SET
               code = COALESCE(school.code, EXCLUDED.code),
               updated_at = now()
           RETURNING id""",
        (name, province, code, source_id),
    )
    return cur.fetchone()[0]


def _get_or_create_pathway(cur, name: str | None, source_id: int):
    if not name:
        return None
    cur.execute("SELECT id FROM pathway WHERE name = %s", (name,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        """INSERT INTO pathway (name, source_id) VALUES (%s, %s)
           ON CONFLICT (name) DO UPDATE SET updated_at = now()
           RETURNING id""",
        (name, source_id),
    )
    return cur.fetchone()[0]


def _get_major_id(cur, name: str | None):
    if not name:
        return None
    cur.execute("SELECT id FROM major WHERE name = %s LIMIT 1", (name,))
    row = cur.fetchone()
    return row[0] if row else None


def _as_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 各表 upsert
# ---------------------------------------------------------------------------
def _load_score_segment(cur, r, sid):
    cur.execute(
        """INSERT INTO score_segment
             (province, year, subject_type, score, score_end,
              same_score_count, cumulative_rank, source_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (province, year, subject_type, score) DO UPDATE
             SET score_end        = EXCLUDED.score_end,
                 same_score_count = EXCLUDED.same_score_count,
                 cumulative_rank  = EXCLUDED.cumulative_rank,
                 source_id        = EXCLUDED.source_id""",
        (r.get("province", "河南"), r["year"], r["subject_type"], r["score"],
         r.get("score_end"), r.get("same_score_count"), r["cumulative_rank"], sid),
    )


def _load_school(cur, r, sid):
    cur.execute(
        """INSERT INTO school
             (name, code, province, city, level, type, ownership,
              website, intro, is_211, is_985, dual_class, external_id, source_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (name) DO UPDATE SET
             code        = COALESCE(EXCLUDED.code, school.code),
             province    = EXCLUDED.province,
             city        = EXCLUDED.city,
             level       = EXCLUDED.level,
             type        = EXCLUDED.type,
             ownership   = EXCLUDED.ownership,
             is_211      = EXCLUDED.is_211,
             is_985      = EXCLUDED.is_985,
             dual_class  = EXCLUDED.dual_class,
             external_id = EXCLUDED.external_id,
             source_id   = EXCLUDED.source_id,
             updated_at  = now()""",
        (r.get("name"), r.get("code"), r.get("province", "河南"), r.get("city"),
         r.get("level"), r.get("type"), r.get("ownership"), r.get("website"),
         r.get("intro"), r.get("is_211"), r.get("is_985"), r.get("dual_class"),
         str(r.get("eol_school_id")) if r.get("eol_school_id") else None, sid),
    )


def _load_major(cur, r, sid):
    cur.execute(
        """INSERT INTO major (name, code, category, degree, intro, source_id)
           VALUES (%s,%s,%s,%s,%s,%s)
           ON CONFLICT (code) DO UPDATE SET
             name     = EXCLUDED.name,
             category = EXCLUDED.category,
             degree   = EXCLUDED.degree,
             intro    = EXCLUDED.intro,
             source_id = EXCLUDED.source_id,
             updated_at = now()""",
        (r.get("name"), r.get("code"), r.get("category"), r.get("degree"),
         r.get("intro"), sid),
    )


def _load_pathway(cur, r, sid):
    cur.execute(
        """INSERT INTO pathway
             (name, category, batch, target_group, apply_time, description,
              priority, data_status, source_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (name) DO UPDATE SET
             category     = EXCLUDED.category,
             batch        = EXCLUDED.batch,
             target_group = EXCLUDED.target_group,
             apply_time   = COALESCE(EXCLUDED.apply_time, pathway.apply_time),
             description  = EXCLUDED.description,
             priority     = EXCLUDED.priority,
             data_status  = EXCLUDED.data_status,
             source_id    = EXCLUDED.source_id,
             updated_at   = now()""",
        (r.get("name"), r.get("category"), r.get("batch"), r.get("target_group"),
         r.get("apply_time"), r.get("description"), r.get("priority", "P2"),
         r.get("data_status", "schema_only"), sid),
    )


def _load_pathway_time(cur, r, sid):
    """关键时间节点：并入 pathway.apply_time（pathway_time 不是独立事实表）。"""
    pid = _get_or_create_pathway(cur, r.get("pathway_name"), sid)
    if not pid:
        return
    cur.execute(
        "UPDATE pathway SET apply_time = %s, updated_at = now() WHERE id = %s",
        (r.get("apply_time"), pid),
    )


def _load_pathway_region(cur, r, sid):
    pid = _get_or_create_pathway(cur, r.get("pathway_name"), sid)
    if not pid:
        return
    cur.execute(
        """INSERT INTO pathway_region
             (pathway_id, province, county_name, county_code, source_id)
           VALUES (%s,%s,%s,%s,%s)
           ON CONFLICT (pathway_id, province, county_code) DO UPDATE SET
             county_name = EXCLUDED.county_name,
             source_id   = EXCLUDED.source_id""",
        (pid, r.get("province", "河南"), r["county_name"],
         r.get("county_code") or None, sid),
    )


def _load_pathway_eligibility(cur, r, sid):
    pid = _get_or_create_pathway(cur, r.get("pathway_name"), sid)
    if not pid:
        return
    params = r.get("params")
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except (ValueError, TypeError):
            params = None
    cur.execute(
        """INSERT INTO pathway_eligibility
             (pathway_id, province, rule_type, rule_desc, params, source_id)
           VALUES (%s,%s,%s,%s,%s,%s)
           ON CONFLICT (pathway_id, province, rule_type, rule_desc) DO UPDATE SET
             params    = EXCLUDED.params,
             source_id = EXCLUDED.source_id""",
        (pid, r.get("province", "河南"), r["rule_type"], r["rule_desc"],
         json.dumps(params, ensure_ascii=False) if params is not None else None, sid),
    )


def _load_school_major_score(cur, r, sid):
    school_id = _get_or_create_school(
        cur, r.get("school_name"), sid, r.get("province", "河南"), r.get("school_code"))
    if not school_id:
        raise ValueError("school_name 为空，无法关联院校")
    major_id = _get_major_id(cur, r.get("major_name"))
    cur.execute(
        """INSERT INTO school_major_score
             (school_id, major_id, province, year, batch, subject_type,
              group_code, group_name, min_score, min_rank, avg_score,
              plan_count, pathway_id, source_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (school_id, major_id, province, year, batch, subject_type, group_code)
           DO UPDATE SET
             group_name = EXCLUDED.group_name,
             min_score  = EXCLUDED.min_score,
             min_rank   = EXCLUDED.min_rank,
             avg_score  = EXCLUDED.avg_score,
             plan_count = EXCLUDED.plan_count,
             source_id  = EXCLUDED.source_id,
             updated_at = now()""",
        (school_id, major_id, r.get("province", "河南"), r["year"], r["batch"],
         r["subject_type"], r.get("group_code"), r.get("group_name"),
         _as_float(r.get("min_score")), r.get("min_rank"), _as_float(r.get("avg_score")),
         r.get("plan_count"), None, sid),
    )


def _load_pathway_score(cur, r, sid):
    """D-4 专项计划录取分：途径 × 院校 × 年份 × 科类 × 专业组 级。"""
    pid = _get_or_create_pathway(cur, r.get("pathway_name"), sid)
    if not pid:
        raise ValueError("pathway_name 为空，无法关联途径")
    school_id = _get_or_create_school(
        cur, r.get("school_name"), sid, r.get("province", "河南"), r.get("school_code"))
    if not school_id:
        raise ValueError("school_name 为空，无法关联院校")
    major_id = _get_major_id(cur, r.get("major_name"))
    cur.execute(
        """INSERT INTO pathway_score
             (pathway_id, school_id, major_id, province, year, batch, subject_type,
              group_code, group_name, min_score, max_score, min_rank,
              admitted_num, source_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (pathway_id, school_id, province, year, subject_type, group_code)
           DO UPDATE SET
             batch        = EXCLUDED.batch,
             group_name   = EXCLUDED.group_name,
             min_score    = EXCLUDED.min_score,
             max_score    = EXCLUDED.max_score,
             min_rank     = EXCLUDED.min_rank,
             admitted_num = EXCLUDED.admitted_num,
             source_id    = EXCLUDED.source_id""",
        (pid, school_id, major_id, r.get("province", "河南"), r["year"],
         r.get("batch"), r.get("subject_type"), r.get("group_code"),
         r.get("group_name"), _as_float(r.get("min_score")),
         _as_float(r.get("max_score")), r.get("min_rank"),
         r.get("admitted_num"), sid),
    )


def _load_batch_score_line(cur, r, sid):
    cur.execute(
        """INSERT INTO batch_score_line
             (province, year, batch, subject_type, score, source_id)
           VALUES (%s,%s,%s,%s,%s,%s)
           ON CONFLICT (province, year, batch, subject_type) DO UPDATE SET
             score = EXCLUDED.score, source_id = EXCLUDED.source_id""",
        (r.get("province", "河南"), r["year"], r["batch"], r["subject_type"],
         r["score"], sid),
    )


def _load_enrollment_rule(cur, r, sid):
    school_id = _get_or_create_school(
        cur, r.get("school_name"), sid, "河南", r.get("school_code"))
    if not school_id:
        raise ValueError("school_name 为空，无法关联院校")
    cur.execute(
        """INSERT INTO enrollment_rule
             (school_id, year, content, subject_req, health_req,
              foreign_lang_req, source_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (school_id, year) DO UPDATE SET
             content          = EXCLUDED.content,
             subject_req      = EXCLUDED.subject_req,
             health_req       = EXCLUDED.health_req,
             foreign_lang_req = EXCLUDED.foreign_lang_req,
             source_id        = EXCLUDED.source_id,
             updated_at       = now()""",
        (school_id, r["year"], r.get("content"), r.get("subject_req"),
         r.get("health_req"), r.get("foreign_lang_req"), sid),
    )


def _load_school_profile(cur, r, sid):
    school_id = _get_or_create_school(
        cur, r.get("school_name"), sid, "河南", r.get("school_code"))
    if not school_id:
        raise ValueError("school_name 为空，无法关联院校")
    # D-5 富化：把画像里的官网/简介回填到 school 主表
    if r.get("website") or r.get("intro"):
        cur.execute(
            """UPDATE school SET
                 website = COALESCE(NULLIF(%s, ''), website),
                 intro   = COALESCE(NULLIF(%s, ''), intro),
                 updated_at = now()
               WHERE id = %s""",
            (r.get("website") or "", r.get("intro") or "", school_id))
    master = r.get("master_points") or None
    phd = r.get("phd_points") or None
    mp = json.dumps({"master": master, "phd": phd}, ensure_ascii=False) \
        if (master or phd) else None
    cur.execute(
        """INSERT INTO school_profile
             (school_id, tuition_range, accommodation_fee, established_year,
              master_phd_points, faculty_count, source_note, source_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (school_id) DO UPDATE SET
             tuition_range     = EXCLUDED.tuition_range,
             accommodation_fee = EXCLUDED.accommodation_fee,
             established_year  = EXCLUDED.established_year,
             master_phd_points = EXCLUDED.master_phd_points,
             faculty_count     = EXCLUDED.faculty_count,
             source_note       = EXCLUDED.source_note,
             source_id         = EXCLUDED.source_id,
             updated_at        = now()""",
        (school_id, r.get("tuition_range"), r.get("accommodation_fee"),
         r.get("established_year"), mp, r.get("faculty_count"),
         r.get("source_note") or "公开数据", sid),
    )


def _load_knowledge_doc(cur, r, sid):
    pathway_id = _get_or_create_pathway(cur, r.get("pathway_name"), sid)
    cur.execute(
        """INSERT INTO knowledge_doc
             (title, source_name, source_url, year, doc_type, province,
              pathway_id, content, source_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (title, source_url) DO UPDATE SET
             content    = EXCLUDED.content,
             doc_type   = EXCLUDED.doc_type,
             pathway_id = EXCLUDED.pathway_id,
             source_id  = EXCLUDED.source_id""",
        (r["title"], r.get("source_name", ""), r.get("source_url", ""),
         r.get("year"), r.get("doc_category"), r.get("province", "河南"),
         pathway_id, r.get("content"), sid),
    )


def _load_knowledge_chunk(cur, r, sid):
    # 通过 (标题, 来源 URL) 找到主文档
    cur.execute(
        "SELECT id FROM knowledge_doc WHERE title = %s AND source_url = %s",
        (r.get("doc_title"), r.get("source_url", "")))
    row = cur.fetchone()
    if not row:
        raise ValueError(f"未找到 knowledge_doc: {r.get('doc_title')}")
    doc_id = row[0]
    pathway_id = _get_or_create_pathway(cur, r.get("pathway_name"), sid)
    meta = {"province": r.get("province", "河南"),
            "pathway": r.get("pathway_name", "")}
    cur.execute(
        """INSERT INTO knowledge_chunk
             (doc_id, content, chunk_index, meta, province, pathway_id, source_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (doc_id, chunk_index) DO UPDATE SET
             content    = EXCLUDED.content,
             meta       = EXCLUDED.meta,
             pathway_id = EXCLUDED.pathway_id,
             source_id  = EXCLUDED.source_id""",
        (doc_id, r["content"], r["chunk_index"],
         json.dumps(meta, ensure_ascii=False), r.get("province", "河南"),
         pathway_id, sid),
    )


def _load_school_life(cur, r, sid):
    """D-11 生活信息：按 (school_id, category, content) 幂等 upsert。"""
    school_id = _get_or_create_school(
        cur, r.get("school_name"), sid, "河南", r.get("school_code"))
    if not school_id:
        raise ValueError("school_name 为空，无法关联院校")
    cur.execute(
        """INSERT INTO school_life
             (school_id, category, content, source_type, source_name,
              source_url, year, reliability, source_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (school_id, category, content) DO UPDATE SET
             source_type = EXCLUDED.source_type,
             source_name = EXCLUDED.source_name,
             source_url  = EXCLUDED.source_url,
             year        = EXCLUDED.year,
             reliability = EXCLUDED.reliability,
             source_id   = EXCLUDED.source_id,
             updated_at  = now()""",
        (school_id, r.get("category"), r.get("content"),
         r.get("source_type") or "公开网络", r.get("source_name", ""),
         r.get("source_url", ""), int(r.get("year") or 2026),
         r.get("reliability") or "medium", sid),
    )


def _load_discipline_eval(cur, r, sid):
    """D-9 学科评估：按 (school_id, discipline_name, round) 幂等 upsert。"""
    school_id = _get_or_create_school(
        cur, r.get("school_name"), sid, "河南", r.get("school_code"))
    if not school_id:
        raise ValueError("school_name 为空，无法关联院校")
    cur.execute(
        """INSERT INTO discipline_eval
             (school_id, discipline_name, grade, round, source_id)
           VALUES (%s,%s,%s,%s,%s)
           ON CONFLICT (school_id, discipline_name, round) DO UPDATE SET
             grade     = EXCLUDED.grade,
             source_id = EXCLUDED.source_id""",
        (school_id, r.get("discipline_name"), r.get("grade"),
         r.get("round"), sid),
    )


LOADERS = {
    "score_segment": _load_score_segment,
    "school": _load_school,
    "major": _load_major,
    "pathway": _load_pathway,
    "pathway_time": _load_pathway_time,
    "pathway_region": _load_pathway_region,
    "pathway_eligibility": _load_pathway_eligibility,
    "school_major_score": _load_school_major_score,
    "pathway_score": _load_pathway_score,
    "batch_score_line": _load_batch_score_line,
    "enrollment_rule": _load_enrollment_rule,
    "school_profile": _load_school_profile,
    "discipline_eval": _load_discipline_eval,
    "school_life": _load_school_life,
    "knowledge_doc": _load_knowledge_doc,
    "knowledge_chunk": _load_knowledge_chunk,
}


# ---------------------------------------------------------------------------
# 院校专业组聚合（school_major_score）
# ---------------------------------------------------------------------------
def _aggregate_school_major_score(rows: list[dict]) -> list[dict]:
    """把专业级明细聚合到「院校专业组」级（schema 的投档单位）。

    原因：school_major_score 唯一键为
        (school_id, major_id, province, year, batch, subject_type, group_code)，
    major_id 为 NULL（专业组投档）时多行会互相覆盖。聚合到组级后：
        min_score = 组内各专业最低分的最小值（即该组真实投档线）
        min_rank  = 最优位次
        plan_count= 组内计划数之和
        group_name 追加「（N个专业）」便于识别
    聚合在入库前完成，保证重复执行结果一致（幂等）。
    """
    groups: "OrderedDict[tuple, list[dict]]" = OrderedDict()
    for r in rows:
        key = (r.get("school_name"), r.get("province", "河南"), r.get("year"),
               r.get("batch"), r.get("subject_type"), r.get("group_code"))
        groups.setdefault(key, []).append(r)

    out: list[dict] = []
    for key, grp in groups.items():
        base = dict(grp[0])
        scores = [s for s in (_as_float(g.get("min_score")) for g in grp)
                  if s is not None]
        ranks = [g["min_rank"] for g in grp if g.get("min_rank") is not None]
        avgs = [a for a in (_as_float(g.get("avg_score")) for g in grp)
                if a is not None]
        plans = [g["plan_count"] for g in grp if g.get("plan_count") is not None]
        majors = {g.get("major_name") for g in grp if g.get("major_name")}

        base["min_score"] = min(scores) if scores else None
        base["min_rank"] = min(ranks) if ranks else None
        base["avg_score"] = round(sum(avgs) / len(avgs), 1) if avgs else None
        base["plan_count"] = sum(plans) if plans else None
        base["major_name"] = None                      # 聚合后为专业组级
        gn = next((g.get("group_name") for g in grp if g.get("group_name")), None)
        if not gn and key[5]:
            gn = f"专业组{key[5]}"
        if gn and len(majors) > 1:
            gn = f"{gn}（{len(majors)}个专业）"
        base["group_name"] = gn
        base["_major_count"] = len(majors)
        out.append(base)

    if len(out) != len(rows):
        logger.info("school_major_score 专业级 %d 行 → 专业组级 %d 行",
                    len(rows), len(out))
    return out


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------
def load_all(cleaned: dict, dsn: str = DEFAULT_DSN, batch_no: str = "manual") -> dict:
    """
    cleaned: {doc_type: CleanResult(valid=[...])} 或 {doc_type: [row, ...]}
    返回每张表的写入统计。
    """
    stats: dict[str, dict] = {"loaded": 0, "failed": 0, "by_table": {}}

    # 按依赖顺序处理；未知 doc_type 追加在后
    ordered = [dt for dt in LOAD_ORDER if dt in cleaned]
    ordered += [dt for dt in cleaned if dt not in ordered]

    with connect(dsn) as conn:
        with conn.cursor() as cur:
            for doc_type in ordered:
                result = cleaned[doc_type]
                rows = getattr(result, "valid", result)
                loader = LOADERS.get(doc_type)
                if loader is None:
                    logger.warning("无对应正式表，跳过 doc_type=%s（%d 行）",
                                   doc_type, len(rows))
                    stats["by_table"][doc_type] = {"ok": 0, "failed": 0,
                                                   "skipped": len(rows)}
                    continue
                if doc_type == "school_major_score":
                    rows = _aggregate_school_major_score(rows)

                ok = fail = 0
                for i, row in enumerate(rows, start=1):
                    try:
                        sid = _ensure_source(
                            cur, row.get("source_name", ""),
                            row.get("source_url", ""), int(row.get("year") or 0),
                        )
                        _stage(cur, batch_no, doc_type, row.get("source_name", ""),
                               row.get("source_url", ""), row.get("year"), row, i)
                        loader(cur, row, sid)
                        ok += 1
                    except Exception as e:            # noqa: BLE001
                        fail += 1
                        logger.warning("写入失败 %s row#%d: %s", doc_type, i, e)
                stats["loaded"] += ok
                stats["failed"] += fail
                stats["by_table"][doc_type] = {"ok": ok, "failed": fail}
                logger.info("load %-22s ok=%d failed=%d", doc_type, ok, fail)
    return stats
