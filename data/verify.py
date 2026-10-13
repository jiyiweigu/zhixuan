"""离线自检脚本（默认不联网）。

用法：
    python data/verify.py                # 纯离线校验
    ZHIXUAN_DSN=postgresql://... python data/verify.py   # 额外做一次实库连通/行数校验

校验内容：
    1. 全部模块可导入（13 个采集器 + 清洗器 + 入库器）
    2. 批次控制线解析器（离线样本，抽样值比对官方）
    3. 一分一段解析器（区间 / 带批注单元格）
    4. 批次名 / 科类归一化
    4b. D-4 专项录取分解析（专业组表格 rowspan + 官方文本）
    5. 清洗器：缺来源三要素的行必须被拒收
    6. 清洗器：batch_score_line / pathway_time 业务校验
    7. 入库器：LOADERS 覆盖全部产出 doc_type（14 类）
    8. 既有产出 data/output/*.json 的来源三要素覆盖率 = 100%
    9. db/schema.sql 关键表齐全
   10.（可选）实库连通与行数校验

全部通过返回码 0，否则返回 1。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT))

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))


# --------------------------------------------------------------------------
# 1. 模块导入（全部采集器）
# --------------------------------------------------------------------------
COLLECTOR_MODULES = [
    "base", "c_segment", "c_school", "c_admission", "c_region", "c_pathway",
    "c_line", "c_batch_line", "c_policy_doc", "c_eligibility", "c_zhangcheng",
    "c_profile", "c_pathway_score", "c_discipline", "c_life", "c_plan",
]
try:
    import importlib
    for m in COLLECTOR_MODULES:
        importlib.import_module(f"data.collectors.{m}")
    from data.collectors.base import (RawRecord, parse_html,
                                      normalize_batch, normalize_subject)
    from data.collectors.c_line import parse_scoreline
    from data.collectors.c_pathway_score import (parse_group_table,
                                                 parse_gov_text, pathway_name_of)
    from data.collectors.c_life import parse_life_from_intro
    from data.collectors import c_segment
    from data.cleaners.normalize import clean_records
    from data.loaders import pg
    check(f"模块导入（{len(COLLECTOR_MODULES)} 采集器 + 清洗 + 入库）", True,
          f"解析器={__import__('data.collectors.base', fromlist=['PARSER']).PARSER}")
    ok_import = True
except Exception as e:                              # noqa: BLE001
    check(f"模块导入（{len(COLLECTOR_MODULES)} 采集器 + 清洗 + 入库）", False, repr(e))
    ok_import = False


# --------------------------------------------------------------------------
# 2. 批次控制线解析（离线样本）
# --------------------------------------------------------------------------
if ok_import:
    try:
        sample = (DATA / "samples" / "scoreline_sample.html").read_text(encoding="utf-8")
        recs = parse_scoreline(parse_html(sample))
        values = {(r.year, r.data["batch"], r.data["subject_type"]): r.data["score"]
                  for r in recs}
        ok = (
            len(recs) == 12
            and values.get((2025, "普通本科批", "历史类")) == 471
            and values.get((2025, "普通本科批", "物理类")) == 427
            and values.get((2025, "特殊类型", "物理类")) == 535
            and values.get((2024, "本科一批", "文科")) == 521
            and values.get((2024, "本科二批", "理科")) == 396
        )
        check("批次控制线解析（2024/2025）", ok, f"{len(recs)} 条，抽样值比对官方一致")
    except Exception as e:                          # noqa: BLE001
        check("批次控制线解析（2024/2025）", False, repr(e))


# --------------------------------------------------------------------------
# 3. 一分一段解析（离线样本）
# --------------------------------------------------------------------------
if ok_import:
    try:
        sample = (DATA / "samples" / "segment_sample.html").read_text(encoding="utf-8")
        rows = c_segment._parse_table(parse_html(sample))
        by_score = {r.score: r for r in rows}
        ok = (
            len(rows) == 7
            and by_score[710].cumulative_rank == 12
            and by_score[427].cumulative_rank == 348358   # 本科线累计人数
            and by_score[535].cumulative_rank == 143976   # 特招线累计人数
        )
        check("一分一段解析（区间/带后缀单元格）", ok, f"{len(rows)} 行")
    except Exception as e:                          # noqa: BLE001
        check("一分一段解析（区间/带后缀单元格）", False, repr(e))


# --------------------------------------------------------------------------
# 4. 批次名 / 科类归一化
# --------------------------------------------------------------------------
if ok_import:
    try:
        ok = (
            normalize_batch("本科批") == "普通本科批"
            and normalize_batch("普通高职（专科）批") == "高职高专批"
            and normalize_batch("专科批") == "高职高专批"
            and normalize_batch("本科一批") == "本科一批"
            and normalize_subject("理工") == "理科"
            and normalize_subject("文史") == "文科"
            and normalize_subject("物理") == "物理类"
            and normalize_subject("") is None
        )
        check("批次名/科类归一化", ok, "本科批→普通本科批，理工→理科 ...")
    except Exception as e:                          # noqa: BLE001
        check("批次名/科类归一化", False, repr(e))


# --------------------------------------------------------------------------
# 4b. D-4 专项录取分解析（离线样本，含 rowspan 合并首列）
# --------------------------------------------------------------------------
if ok_import:
    try:
        sample = (DATA / "samples" / "pathway_score_sample.html").read_text(encoding="utf-8")
        rows = parse_group_table(parse_html(sample))
        special = [r for r in rows if "专项" in (r["group_name"] or "")]
        keyed = {(r["group_code"], r["subject_type"]): r["min_score"] for r in rows}
        gov = parse_gov_text(parse_html(sample).get_text(" "))
        gov_keyed = {(r["pathway_name"], r["subject_type"]): (r["min_score"], r["max_score"])
                     for r in gov}
        table_ok = (
            len(rows) == 10                                  # 全表 10 个科类行
            and len(special) == 6                            # 其中专项组 6 行
            and keyed.get(("301", "历史类")) == 579           # rowspan 沿用组名后仍能对齐
            and keyed.get(("301", "物理类")) == 567
            and keyed.get(("402", "物理类")) == 570
            and pathway_name_of(special[0]["group_name"]) in
                {"国家专项计划", "地方专项计划"}
        )
        gov_ok = (
            len(gov) == 4
            and gov_keyed.get(("国家专项计划", "历史类")) == (598.0, 619.0)
            and gov_keyed.get(("国家专项计划", "物理类")) == (616.0, 642.0)
            and gov_keyed.get(("地方专项计划", "物理类")) == (600.0, 630.0)
        )
        check("D-4 专项录取分解析（表格+官方文本）", table_ok and gov_ok,
              f"表格 {len(rows)} 行/专项 {len(special)} 行；文本 {len(gov)} 条")
    except Exception as e:                          # noqa: BLE001
        check("D-4 专项录取分解析（表格+官方文本）", False, repr(e))


# --------------------------------------------------------------------------
# 4c. D-9/D-11 解析器（离线，纯函数）
# --------------------------------------------------------------------------
if ok_import:
    try:
        sample_text = ("我校宿舍实行公寓化管理，四人一间。"
                       "校园食堂共有三个大型餐厅，菜品丰富。"
                       "校区交通便利，地铁一号线直达校门口。"
                       "这段文字不含任何生活关键词应当被跳过。")
        out = parse_life_from_intro("测试大学", sample_text)
        cats = {o["category"] for o in out}
        ok = (cats == {"宿舍", "食堂", "交通"} and len(out) == 3)
        check("D-11 生活信息段落抽取", ok, f"抽到类别 {sorted(cats)}")
    except Exception as e:                          # noqa: BLE001
        check("D-11 生活信息段落抽取", False, repr(e))


# --------------------------------------------------------------------------
# 4d. D-12 三大专项实施区域县名单（离线，口径校验）
#   国家专项 38 县；高校专项 53 县；地方专项=全省农村不划县
# --------------------------------------------------------------------------
if ok_import:
    try:
        seeds = json.loads(
            (DATA / "seeds" / "pathway_regions.json").read_text(encoding="utf-8"))
        nat = seeds.get("国家专项计划", {}).get("counties", [])
        hi = seeds.get("高校专项计划", {}).get("counties", [])
        loc = seeds.get("地方专项计划", {}).get("counties", [])
        nat_codes = {c["county_code"] for c in nat}
        hi_codes = {c["county_code"] for c in hi}
        d12_ok = (
            len(nat) == 38 and len(nat_codes) == 38
            and len(hi) == 53 and len(hi_codes) == 53
            and len(loc) == 0                      # 地方专项无县名单
            and nat_codes <= hi_codes              # 国家 38 县 ⊆ 高校 53 县
        )
        check("D-12 专项县名单口径", d12_ok,
              f"国家{len(nat)}县/高校{len(hi)}县/地方0县（全省农村），国家⊆高校={nat_codes <= hi_codes}")
    except Exception as e:                          # noqa: BLE001
        check("D-12 专项县名单口径", False, repr(e))


# --------------------------------------------------------------------------
# 5. 清洗器：缺来源三要素必须拒收
# --------------------------------------------------------------------------
if ok_import:
    try:
        good = RawRecord(data={"province": "河南", "year": 2025, "subject_type": "物理类",
                               "score": 600, "same_score_count": 10, "cumulative_rank": 100},
                         source_name="河南省阳光高考信息平台",
                         source_url="https://gaokao.haedu.cn/", year=2025,
                         doc_type="score_segment")
        bad = RawRecord(data={"province": "河南", "year": 2025, "subject_type": "物理类",
                              "score": 601, "same_score_count": 10, "cumulative_rank": 90},
                        source_name="", source_url="", year=2025, doc_type="score_segment")
        res = clean_records([good, bad])
        ok = res.valid_count == 1 and res.rejected_count == 1 \
            and "source_name" in res.rejected[0]["reject_reason"]
        check("清洗器拒收缺来源行", ok,
              f"valid={res.valid_count} rejected={res.rejected_count}")
    except Exception as e:                          # noqa: BLE001
        check("清洗器拒收缺来源行", False, repr(e))


# --------------------------------------------------------------------------
# 6. 清洗器：batch_score_line / pathway_time 业务校验
# --------------------------------------------------------------------------
if ok_import:
    try:
        recs = [
            RawRecord(data={"province": "河南", "year": 2025, "batch": "普通本科批",
                            "subject_type": "物理类", "score": 427},
                      source_name="河南省阳光高考信息平台",
                      source_url="https://gaokao.haedu.cn/scoreline", year=2025,
                      doc_type="batch_score_line"),
            # 分数越界 -> 应被拒
            RawRecord(data={"province": "河南", "year": 2025, "batch": "普通本科批",
                            "subject_type": "物理类", "score": 999},
                      source_name="河南省阳光高考信息平台",
                      source_url="https://gaokao.haedu.cn/scoreline", year=2025,
                      doc_type="batch_score_line"),
            RawRecord(data={"pathway_name": "国家专项计划",
                            "apply_time": "4月底前完成资格申报"},
                      source_name="河南省教育考试院",
                      source_url="https://gaokao.haedu.cn/", year=2025,
                      doc_type="pathway_time"),
            # 缺 pathway_name -> 应被拒
            RawRecord(data={"apply_time": "x"},
                      source_name="河南省教育考试院",
                      source_url="https://gaokao.haedu.cn/", year=2025,
                      doc_type="pathway_time"),
        ]
        res = clean_records(recs)
        ok = res.valid_count == 2 and res.rejected_count == 2
        check("清洗器 batch_score_line/pathway_time 校验", ok,
              f"valid={res.valid_count} rejected={res.rejected_count}（越界/缺字段被拒）")
    except Exception as e:                          # noqa: BLE001
        check("清洗器 batch_score_line/pathway_time 校验", False, repr(e))


# --------------------------------------------------------------------------
# 7. 入库器：LOADERS 覆盖全部产出 doc_type
# --------------------------------------------------------------------------
if ok_import:
    try:
        produced = {
            "score_segment", "school", "major", "school_major_score",
            "batch_score_line", "pathway", "pathway_region",
            "pathway_eligibility", "pathway_time", "enrollment_rule",
            "school_profile", "pathway_score", "discipline_eval", "school_life",
            "knowledge_doc", "knowledge_chunk",
        }
        missing = sorted(produced - set(pg.LOADERS))
        check("入库器覆盖全部产出 doc_type", not missing,
              f"缺失 loader：{missing}" if missing else f"{len(produced)}/{len(produced)} 均有 loader")
    except Exception as e:                          # noqa: BLE001
        check("入库器覆盖全部产出 doc_type", False, repr(e))


# --------------------------------------------------------------------------
# 8. 既有产出的来源三要素覆盖率
# --------------------------------------------------------------------------
out_dir = DATA / "output"
if out_dir.exists():
    bad_total = 0
    files = 0
    for jf in sorted(out_dir.glob("*.json")):
        if jf.name in ("validation_report.json", "reject_report.json", "load_report.json"):
            continue
        try:
            rows = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:                           # noqa: BLE001
            continue
        if not isinstance(rows, list):
            continue
        files += 1
        bad_total += sum(1 for r in rows
                         if not r.get("source_name") or not r.get("source_url")
                         or not r.get("year"))
    check("既有产出 来源三要素覆盖率", bad_total == 0,
          f"检查 {files} 个文件，缺失 {bad_total} 行")
else:
    check("既有产出 来源三要素覆盖率", False, "data/output 不存在（先跑 run_pipeline.py）")


# --------------------------------------------------------------------------
# 9. schema 关键表齐全
# --------------------------------------------------------------------------
ALL_TABLES = [
    "source", "pathway", "pathway_eligibility", "pathway_region",
    "school", "major", "school_major_score", "pathway_score",
    "score_segment", "batch_score_line", "enrollment_rule", "discipline_eval",
    "school_profile", "school_life", "knowledge_doc", "knowledge_chunk",
    "app_user", "user_profile", "user_favorite", "user_plan",
    "qa_log", "review_task", "admin_user", "admin_audit_log", "stg_import",
]
schema = ROOT / "db" / "schema.sql"
if schema.exists():
    import re as _re
    sql = schema.read_text(encoding="utf-8")
    missing = [t for t in ALL_TABLES
               if not _re.search(rf"CREATE TABLE IF NOT EXISTS\s+{_re.escape(t)}\s*\(", sql)]
    check("schema 全部表齐全", not missing,
          f"缺失：{missing}" if missing else f"{len(ALL_TABLES)}/{len(ALL_TABLES)}")
else:
    check("schema 全部表齐全", False, "db/schema.sql 不存在")


# --------------------------------------------------------------------------
# 10.（可选）实库连通与行数校验
# --------------------------------------------------------------------------
dsn = os.environ.get("ZHIXUAN_DSN")
if dsn:
    try:
        with pg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM school")
            n_school = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM score_segment")
            n_seg = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM source")
            n_src = cur.fetchone()[0]
        ok = n_school > 0 and n_seg > 0 and n_src > 0
        check("实库连通与行数", ok,
              f"school={n_school} score_segment={n_seg} source={n_src}")

        # 事实表 source_id 非空（来源铁律）
        FACT_TABLES = [
            "school_major_score", "pathway_score", "score_segment",
            "batch_score_line", "enrollment_rule", "school_profile",
            "discipline_eval", "school_life", "pathway_region",
            "pathway_eligibility", "knowledge_doc", "knowledge_chunk",
        ]
        with pg.connect(dsn) as conn, conn.cursor() as cur:
            bad = []
            for t in FACT_TABLES:
                cur.execute(f"SELECT count(*) FROM {t} WHERE source_id IS NULL")
                n = cur.fetchone()[0]
                if n:
                    bad.append(f"{t}={n}")
        check("实库事实表 source_id 非空", not bad,
              f"全部 {len(FACT_TABLES)} 张表合规" if not bad else f"NULL: {bad}")

        # D-9/D-11 已入库
        with pg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM discipline_eval")
            n_de = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM school_life")
            n_sl = cur.fetchone()[0]
        check("实库 D-9/D-11 已入库", n_de > 0 and n_sl > 0,
              f"discipline_eval={n_de} school_life={n_sl}")
    except Exception as e:                          # noqa: BLE001
        check("实库连通与行数", False, repr(e))


# --------------------------------------------------------------------------
# 汇总
# --------------------------------------------------------------------------
def main() -> int:
    width = max(len(n) for n, _, _ in RESULTS)
    print("=" * (width + 22))
    print("智选志愿 · 数据采集离线自检")
    print("=" * (width + 22))
    for name, ok, detail in RESULTS:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:<{width}}  {detail}")
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("-" * (width + 22))
    print(f"  {passed}/{len(RESULTS)} 项通过")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
