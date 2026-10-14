#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Golden Layer 构建脚本（③ 数据工程 · Step 1「转换」）

职责
----
把 `data/` 下的**产物**转成「表结构可直接吃」的规范化中间层：

    data/产物 (*.json / staged/*.jsonl)
        └─ build_golden_layer.py ─▶ data/staged_golden/<table>.jsonl  ← 逐表一行一 JSON
                                      data/staged_golden/_plan.json   ← 每表行数 + id 分配
                                      data/staged_golden/_ledger.json ← 丢弃/待裁 台账

它**不连数据库、不建表、不写库**（写库是 Step 2 的 loader）。

消除的硬阻塞
------------
- `source_id`：字符串逻辑键 `SRC-XXX` → `source.id`（int），并**额外吸收**产物里的
  inline 三要素（`school_profile` 793 条 / `enrollment_rule` 5 条）为新的 source 行。
- `major_id`：国标专业码（含 `K`/`T` 后缀 7 位）→ `major.id`（int）；
  `map_by_code` 已知**零未匹配**（`major-code-map.score_major_id_unmatched_samples = []`）。
- NOT NULL 文本列：`None` → `""`（对齐 check_schema_alignment 的「有默认值→写默认值」口径）。

id 分配（确定性，可复现）
-------------------------
- `source.id`：① 登记的 17 条按原顺序 1–17；② 产物 inline 三要素按 (name,url,year) 排序续号
- `school.id`：沿用 `schools_merged.records[].id`（1–1453，无空洞）
- `major.id` ：`major_table_rows.rows` 文件顺序 1–938
- 其余表不指定 id（交给 DB 序列）

用法
----
    python data/scripts/build_golden_layer.py            # 构建（覆盖 staged_golden/）
    python data/scripts/build_golden_layer.py --scan     # 只盘点不写文件
    python data/scripts/build_golden_layer.py --province 河南 --year 2025   # 只做子集
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
OUT = DATA / "staged_golden"

# 目标表插入顺序（外键依赖）
TABLE_ORDER = [
    "source", "school", "major",
    "score_segment", "school_major_score",
    "pathway", "pathway_region", "pathway_eligibility",
    "province_exam_rule", "enrollment_rule", "school_profile", "school_life",
]

# NOT NULL 文本列：None → ""
TEXT_NOT_NULL: dict[str, tuple[str, ...]] = {
    "school": ("province", "city", "level", "type", "ownership", "website", "intro"),
    "major": ("category", "first_class", "degree", "ownership", "duration", "campus",
              "single_subject_req", "language_req", "gender_req"),
    "pathway": ("name", "category", "batch", "target_group", "apply_time",
                "description", "priority", "data_status"),
    "pathway_region": ("province", "county_name"),
    "pathway_eligibility": ("province", "rule_type", "rule_desc"),
    "province_exam_rule": ("province", "batch", "mode", "admit_method", "ratio",
                           "tie_rule", "province_code", "batch_code", "exam_type"),
    "enrollment_rule": ("content", "subject_req", "health_req", "foreign_lang_req"),
    "school_profile": ("tuition_range", "accommodation_fee", "student_faculty_ratio"),
    "school_life": ("category", "content", "source_type", "source_name",
                    "source_url", "reliability"),
    "school_major_score": ("province", "batch", "subject_type"),
}

# province_exam_rule.exam_type 口径映射（库里 CHECK 只允许 普通|艺术|体育）
EXAM_TYPE_MAP = {
    "普通类": "普通",
    "历史、物理科目组": "普通",
    "艺术类 / 体育类": None,   # None = 无法无损映射单值 ⇒ 不入库，记台账待裁
}


def load(rel: str) -> Any:
    with (ROOT / rel).open(encoding="utf-8") as f:
        return json.load(f)


def as_list(payload: Any, *keys: str) -> list[dict]:
    """从 dict 里按 keys 找列表；本身是 list 则直接返回。"""
    if isinstance(payload, list):
        return payload
    for k in keys:
        v = payload.get(k)
        if isinstance(v, list):
            return v
    raise KeyError(f"找不到列表字段：{keys}（顶层 keys={list(payload)}）")


def num(v: Any) -> Any:
    """float 且为整数值 → int；否则原样。"""
    if isinstance(v, bool):
        return v
    if isinstance(v, float) and v == int(v):
        return int(v)
    return v


def txt(v: Any) -> str:
    """文本列（NOT NULL DEFAULT ''）：None / 空白 → ''。"""
    if v is None:
        return ""
    return str(v).strip()


def fill_text(table: str, rec: dict) -> dict:
    """NOT NULL 文本列：None / 缺失 → ""。"""
    for col in TEXT_NOT_NULL.get(table, ()):
        if col in rec and (rec[col] is None or (isinstance(rec[col], str) and not rec[col].strip())):
            rec[col] = ""
        elif col not in rec:
            rec[col] = ""
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true", help="只盘点，不写文件")
    ap.add_argument("--province")
    ap.add_argument("--year", type=int)
    ap.add_argument("--allow-null-identity", action="store_true", dest="allow_null_identity",
                    help="按契约 §8.10.3 红线②：school_major_score 的 school_id/major_id "
                         "若为数据侧『真实未匹配』则保留并以 NULL 入库（需 schema ≥ 0008/0009），"
                         "同时输出身份列 group_code/major_code/major_name/exam_system")
    args = ap.parse_args()

    ledger: dict[str, list[dict]] = {}
    ROUND_STAT: Counter = Counter()          # 分数取整（统计量）：聚合计数
    ROUND_SAMPLES: dict[str, list] = {"min_score": [], "avg_score": []}
    NULL_STAT: Counter = Counter()           # 分数置 NULL（口径不明）：聚合计数
    NULL_SAMPLES: dict[str, list] = {"min_score": []}
    NULL_ID_STAT: Counter = Counter()        # 身份列真实未匹配、以 NULL 入库：聚合计数
    plan: dict[str, Any] = {"meta": {
        "title": "Golden Layer 构建计划",
        "owner": "徐（③ 数据工程）",
        "generated_at": "2026-10-14",
        "note": "逐表可直接 INSERT 的规范化层；逻辑键已换成物理 id。不连库。",
        "identity_mode": ("allow_null (§8.10.3 红线②；需 schema ≥ 0008/0009)"
                          if args.allow_null_identity else "legacy(身份列缺省丢弃)"),
        "schema_requirement": ("0009_school_major_score_identity"
                               if args.allow_null_identity else "0007_rule_datasets"),
    }, "tables": {}}
    tables: dict[str, list[dict]] = {}

    def drop(kind: str, rec: dict, why: str) -> None:
        ledger.setdefault(kind, []).append({"reason": why, **rec})

    # ------------------------------------------------------------------ #
    # 0) source —— 登记 17 条 + 产物 inline 三要素
    # ------------------------------------------------------------------ #
    registry = as_list(load("data/sources/source-table.json"), "sources", "records")
    src_map: dict[str, int] = {}          # SRC-XXX -> int id
    trip_map: dict[tuple, int] = {}       # (name,url,year) -> int id
    sources: list[dict] = []
    for i, s in enumerate(registry, start=1):
        sources.append({
            "id": i,
            "source_name": s.get("source_name"),
            "source_url": s.get("source_url"),
            "year": int(s.get("year")),
            "source_type": s.get("source_type"),
            "fetched_at": s.get("fetched_at"),
        })
        src_map[str(s.get("id"))] = i
        trip_map[(str(s.get("source_name")).strip(), str(s.get("source_url")).strip(), int(s.get("year")))] = i

    def ensure_source(name: Any, url: Any, year: Any, stype: Any) -> int | None:
        """按三要素取回 id；三要素不全 → None（拒入）。"""
        if not (name and url and year):
            return None
        key = (str(name).strip(), str(url).strip(), int(year))
        if key in trip_map:
            return trip_map[key]
        new_id = len(sources) + 1
        sources.append({"id": new_id, "source_name": key[0], "source_url": key[1],
                        "year": key[2], "source_type": stype, "fetched_at": None})
        trip_map[key] = new_id
        return new_id

    def sid(logical: Any) -> int | None:
        """SRC-XXX -> int；已是 int 直接返回；未知逻辑键 → None（不猜）。"""
        if logical is None:
            return None
        if isinstance(logical, int):
            return logical
        return src_map.get(str(logical).strip())

    # ------------------------------------------------------------------ #
    # 1) school
    # ------------------------------------------------------------------ #
    sch_recs = as_list(load("data/schools/schools_merged.json"), "records")
    schools = []
    for r in sch_recs:
        schools.append(fill_text("school", {
            "id": r.get("id"), "name": r.get("name"),
            "code": (r.get("code") or None),
            "province": r.get("province"), "city": r.get("city"),
            "level": r.get("level"), "type": r.get("type"),
            "ownership": r.get("ownership"), "website": r.get("website"),
            "intro": r.get("intro"),
        }))
    school_ids = {s["id"] for s in schools}

    # ------------------------------------------------------------------ #
    # 2) major —— 国标码 → id
    # ------------------------------------------------------------------ #
    maj_rows = as_list(load("data/majors/major_table_rows.json"), "rows")
    majors = []
    code_to_major_id: dict[str, int] = {}
    for i, r in enumerate(maj_rows, start=1):
        majors.append(fill_text("major", {
            "id": i, "name": r.get("name"), "code": r.get("code"),
            "category": r.get("category"), "first_class": r.get("first_class"),
            "degree": r.get("degree"), "tuition": r.get("tuition"),
            "ownership": r.get("ownership"), "duration": r.get("duration"),
            "campus": r.get("campus"), "is_category": bool(r.get("is_category")),
            "single_subject_req": r.get("single_subject_req"),
            "language_req": r.get("language_req"),
            "gender_req": r.get("gender_req"),
            "interview_required": bool(r.get("interview_required")),
        }))
        if r.get("code"):
            code_to_major_id[str(r["code"]).strip()] = i

    # 交叉校验：major-code-map 声称零未匹配，这里再验一次
    mm = load("data/mappings/major-code-map.json")
    map_codes = set(mm.get("map_by_code") or {})
    missing_in_major = sorted(map_codes - set(code_to_major_id))
    if missing_in_major:
        print(f"  ⚠ major-code-map 有 {len(missing_in_major)} 个码不在 major_table_rows：{missing_in_major[:5]}")

    # ------------------------------------------------------------------ #
    # 3) score_segment
    # ------------------------------------------------------------------ #
    segs = []
    for p in sorted(glob.glob(str(DATA / "score_segment" / "score_segment_20*.json"))):
        d = json.load(open(p, encoding="utf-8"))
        meta = d.get("meta") or {}
        meta_sid = sid(meta.get("source_id"))
        for r in d.get("segments", []):
            if args.province and r.get("province") != args.province:
                continue
            if args.year and r.get("year") != args.year:
                continue
            s_id = sid(r.get("source_id")) or meta_sid
            if s_id is None:
                drop("score_segment", {"file": os.path.basename(p), **r}, "source_id 无法解析（拒入）")
                continue
            segs.append({
                "province": r.get("province"), "year": int(r.get("year")),
                "subject_type": r.get("subject_type"),
                "score": int(r.get("score")), "cumulative_rank": int(r.get("cumulative_rank")),
                "source_id": s_id,
            })

    # ------------------------------------------------------------------ #
    # 4) school_major_score
    # ------------------------------------------------------------------ #
    sms = []
    for p in sorted(glob.glob(str(DATA / "school_major_score" / "school_major_score_20*.json"))):
        d = json.load(open(p, encoding="utf-8"))
        for r in as_list(d, "scores", "records"):
            if args.province and r.get("province") != args.province:
                continue
            if args.year and r.get("year") != args.year:
                continue
            base = {"file": os.path.basename(p), "school_id": r.get("school_id"),
                    "major_id": r.get("major_id"), "province": r.get("province"),
                    "year": r.get("year"), "major_name": r.get("major_name")}
            s_code = r.get("school_id")
            m_code = r.get("major_id")
            s_empty = s_code is None or (isinstance(s_code, str) and not str(s_code).strip())
            m_empty = m_code is None or (isinstance(m_code, str) and not str(m_code).strip())
            # ① 空 id（数据侧真实未匹配）
            #    · legacy（默认）：列 NOT NULL ⇒ 丢弃待补采
            #    · --allow-null-identity：契约 §8.10.3 红线② 允许原样以 NULL 入库并登记原因
            if s_empty and not args.allow_null_identity:
                drop("school_major_score", base, "school_id 为空（NOT NULL）⇒ 丢弃，待补采")
                continue
            if m_empty and not args.allow_null_identity:
                drop("school_major_score", base, "major_id 为空（NOT NULL）⇒ 丢弃，待补采")
                continue
            # ② 校 id **有值时**必须存在；有值却悬空一律丢弃
            #    —— 红线①：位置耦合的值一旦对不上，绝不降级为 NULL（那等于把「错位」伪装成「缺失」）
            if not s_empty and int(s_code) not in school_ids:
                drop("school_major_score", base, f"school_id={s_code} 不在 school 表（悬空）⇒ 丢弃")
                continue
            # ③ 国标码 → major.id
            if m_empty:
                mid = None
                if args.allow_null_identity:
                    NULL_ID_STAT["school_major_score.major_id 真实未匹配 ⇒ 以 NULL 入库"] += 1
            else:
                mid = code_to_major_id.get(str(m_code).strip())
                if mid is None:
                    drop("school_major_score", base, f"major_id={m_code} 未匹配 major 表 ⇒ 丢弃")
                    continue
            if s_empty:
                NULL_ID_STAT["school_major_score.school_id 真实未匹配 ⇒ 以 NULL 入库"] += 1
            # ④ source_id
            s_id = sid(r.get("source_id"))
            if s_id is None:
                drop("school_major_score", base, "source_id 无法解析 ⇒ 丢弃")
                continue

            # ⑤ 分数列（表列 INTEGER）——两种口径分别处理，均记账、不静默：
            #    · `min_score` = 官方投档最低分，**必为整数**。上游出现小数即口径不明
            #      （实测 2022_河南：`509.12`、`405.087085014` 并存，且原始 CSV 即如此，
            #      非我方转换引入 —— 见待裁 G3）⇒ 按「宁可缺，不可猜」**置 NULL**。
            #      绝不取整：取整会造出"看似整数、实为均值"的**假投档线**，比缺更坏。
            #    · `avg_score` = 统计量（平均分），取整可接受 ⇒ 四舍五入（half-up，
            #      与中文标签一致；Python round() 是银行家舍入会与 PG 落库值不一致）。
            def _int_score(v: Any, col: str) -> Any:
                if isinstance(v, bool) or v is None:
                    return None
                if isinstance(v, float) and v != int(v):
                    if col == "min_score":
                        NULL_STAT["min_score 非整数（非官方投档线口径）⇒ 置 NULL"] += 1
                        if len(NULL_SAMPLES["min_score"]) < 5:
                            NULL_SAMPLES["min_score"].append(v)
                        return None
                    ROUND_STAT[f"{col} 非整数（统计量）⇒ 四舍五入"] += 1
                    if len(ROUND_SAMPLES[col]) < 5:
                        ROUND_SAMPLES[col].append([v, math.floor(v + 0.5)])
                    return math.floor(v + 0.5)
                return v

            rec = fill_text("school_major_score", {
                "school_id": None if s_empty else int(s_code), "major_id": mid,
                "province": r.get("province"), "year": int(r.get("year")),
                "batch": r.get("batch"), "pathway_id": r.get("pathway_id"),
                "subject_type": r.get("subject_type"),
                "min_score": _int_score(r.get("min_score"), "min_score"),
                "min_rank": num(r.get("min_rank")),
                "avg_score": _int_score(r.get("avg_score"), "avg_score"),
                "plan_count": num(r.get("plan_count")),
                "source_id": s_id,
            })
            if args.allow_null_identity:
                # 0009 身份列（NOT NULL DEFAULT ''）：专业组代码 / 招生专业代号 / 专业名 / 考试制度
                for c in ("group_code", "major_code", "major_name", "exam_system"):
                    rec[c] = txt(r.get(c))
            sms.append(rec)

    # ------------------------------------------------------------------ #
    # 5) pathway / 6) pathway_region / 7) pathway_eligibility
    # ------------------------------------------------------------------ #
    pathways = []
    for r in as_list(load("data/dictionaries/pathways-26.json"), "pathways"):
        s_id = sid(r.get("source_id"))
        if s_id is None:
            drop("pathway", {"id": r.get("id")}, "source_id 无法解析 ⇒ 丢弃")
            continue
        pathways.append(fill_text("pathway", {
            "id": r.get("id"), "name": r.get("name"), "category": r.get("category"),
            "batch": r.get("batch"), "target_group": r.get("target_group"),
            "apply_time": r.get("apply_time"), "description": r.get("description"),
            "priority": r.get("priority"), "data_status": r.get("data_status"),
            "year": int(r.get("year")), "source_id": s_id,
        }))

    regions = []
    for r in as_list(load("data/dictionaries/pathway-regions.json"), "regions"):
        s_id = sid(r.get("source_id"))
        if s_id is None:
            drop("pathway_region", {"county_name": r.get("county_name")}, "source_id 无法解析 ⇒ 丢弃")
            continue
        regions.append(fill_text("pathway_region", {
            "pathway_id": r.get("pathway_id"), "province": r.get("province"),
            "county_name": r.get("county_name"), "county_code": (r.get("county_code") or None),
            "year": int(r.get("year")), "source_id": s_id,
        }))

    dw = load("data/dictionaries/pathway-eligibility.json")
    elig = []
    for r in as_list(dw, "rules"):
        s_id = sid(r.get("source_id"))
        if s_id is None:
            drop("pathway_eligibility", {"pathway_id": r.get("pathway_id")}, "source_id 无法解析 ⇒ 丢弃")
            continue
        elig.append(fill_text("pathway_eligibility", {
            "pathway_id": r.get("pathway_id"), "province": r.get("province"),
            "rule_type": r.get("rule_type"), "rule_desc": r.get("rule_desc"),
            "params": r.get("params") or {}, "year": int(r.get("year")), "source_id": s_id,
        }))
    for r in (dw.get("placeholders") or []):
        drop("pathway_eligibility", {"pathway_id": r.get("pathway_id")},
             "骨架占位（source_id=null）⇒ 三要素不全，拒入")

    # ------------------------------------------------------------------ #
    # 8) province_exam_rule
    # ------------------------------------------------------------------ #
    per = []
    for r in as_list(load("data/dictionaries/province-exam-rule.json"), "rules"):
        et_raw = str(r.get("exam_type") or "").strip()
        et = EXAM_TYPE_MAP.get(et_raw, et_raw)
        if et is None:
            drop("province_exam_rule", {"id": r.get("id"), "exam_type": et_raw},
                 f"exam_type='{et_raw}' 无法无损映射到 CHECK(普通|艺术|体育) ⇒ 待裁，暂不入库")
            continue
        s_id = sid(r.get("source_id"))
        if s_id is None:
            drop("province_exam_rule", {"id": r.get("id")}, "source_id 无法解析 ⇒ 丢弃")
            continue
        per.append(fill_text("province_exam_rule", {
            "province": r.get("province"), "year": int(r.get("year")),
            "batch": r.get("batch"), "mode": r.get("mode"),
            "volunteer_count": int(r.get("volunteer_count") or 0),
            "majors_per_group": num(r.get("majors_per_group")),
            "has_adjust": bool(r.get("has_adjust")),
            "admit_method": r.get("admit_method") or "parallel",
            "ratio": r.get("ratio") or "1:1", "tie_rule": r.get("tie_rule"),
            "mutex_groups": r.get("mutex_groups") if isinstance(r.get("mutex_groups"), (list, dict)) else {},
            "collect_count": num(r.get("collect_count")),
            "source_id": s_id,
            "province_code": r.get("province_code") or "",
            "batch_code": r.get("batch_code") or "",
            "exam_type": et,
            "_src_id": r.get("id"),   # 保留原业务键，仅记账用（loader 不入库）
        }))

    # ------------------------------------------------------------------ #
    # 9) enrollment_rule
    # ------------------------------------------------------------------ #
    enr = []
    for r in as_list(load("data/schools/enrollment_rule_rows.json"), "records"):
        s_id = sid(r.get("source_id")) or ensure_source(
            r.get("source_name"), r.get("source_url"), r.get("year"), r.get("source_type"))
        if s_id is None:
            drop("enrollment_rule", {"school_id": r.get("school_id")}, "source 三要素不全 ⇒ 拒入")
            continue
        if int(r.get("school_id") or 0) not in school_ids:
            drop("enrollment_rule", {"school_id": r.get("school_id")}, "school_id 不在 school 表 ⇒ 丢弃")
            continue
        enr.append(fill_text("enrollment_rule", {
            "school_id": int(r.get("school_id")), "year": int(r.get("year")),
            "content": r.get("content"), "subject_req": r.get("subject_req"),
            "health_req": r.get("health_req"), "foreign_lang_req": r.get("foreign_lang_req"),
            "source_id": s_id,
        }))

    # ------------------------------------------------------------------ #
    # 10) school_profile  —— source 为 inline 三要素
    # ------------------------------------------------------------------ #
    prof = []
    for r in as_list(load("data/schools/school_profile_rows.json"), "records"):
        s_id = ensure_source(r.get("source_name"), r.get("source_url"), r.get("year"), r.get("source_type"))
        if s_id is None:
            drop("school_profile", {"school_id": r.get("school_id")}, "source 三要素不全 ⇒ 拒入")
            continue
        if int(r.get("school_id") or 0) not in school_ids:
            drop("school_profile", {"school_id": r.get("school_id")}, "school_id 不在 school 表 ⇒ 丢弃")
            continue
        mpp = r.get("master_phd_points")
        prof.append(fill_text("school_profile", {
            "school_id": int(r.get("school_id")),
            "tuition_range": r.get("tuition_range"), "accommodation_fee": r.get("accommodation_fee"),
            "campus_list": r.get("campus_list") if isinstance(r.get("campus_list"), list) else [],
            "established_year": num(r.get("established_year")),
            "master_phd_points": mpp if isinstance(mpp, (dict, list)) else None,
            "first_class_major_count": num(r.get("first_class_major_count")),
            "faculty_count": num(r.get("faculty_count")),
            "student_faculty_ratio": r.get("student_faculty_ratio"),
            "source_id": s_id,
        }))

    # ------------------------------------------------------------------ #
    # 11) school_life —— 自持来源，无 source_id
    # ------------------------------------------------------------------ #
    life = []
    for r in as_list(load("data/schools/school_life_rows.json"), "records"):
        if not (r.get("source_name") and r.get("source_url") and r.get("year")):
            drop("school_life", {"school_id": r.get("school_id")}, "source 三要素不全 ⇒ 拒入")
            continue
        if int(r.get("school_id") or 0) not in school_ids:
            drop("school_life", {"school_id": r.get("school_id")}, "school_id 不在 school 表 ⇒ 丢弃")
            continue
        life.append(fill_text("school_life", {
            "school_id": int(r.get("school_id")), "category": r.get("category"),
            "content": r.get("content"), "source_type": r.get("source_type"),
            "source_name": r.get("source_name"), "source_url": r.get("source_url"),
            "year": int(r.get("year")), "reliability": r.get("reliability"),
        }))

    # ------------------------------------------------------------------ #
    # FK 后校验：悬空引用 → 台账（不猜、不入 golden）
    # ------------------------------------------------------------------ #
    pw_ids = {p["id"] for p in pathways}

    def guard(rows: list[dict], table: str, checks: list[tuple[str, set, str]]) -> list[dict]:
        keep = []
        for r in rows:
            bad = None
            for col, pool, what in checks:
                v = r.get(col)
                if v is not None and v not in pool:
                    bad = f"{col}='{v}' 悬空（不在 {what}）⇒ 待核，暂不入库"
                    break
            if bad:
                drop(table, {k: r.get(k) for k in
                             ("pathway_id", "school_id", "major_id", "county_name") if k in r}, bad)
            else:
                keep.append(r)
        return keep

    regions = guard(regions, "pathway_region", [("pathway_id", pw_ids, "pathway 表")])
    elig = guard(elig, "pathway_eligibility", [("pathway_id", pw_ids, "pathway 表")])
    sms = guard(sms, "school_major_score", [("pathway_id", pw_ids, "pathway 表")])

    tables = {
        "source": sources, "school": schools, "major": majors,
        "score_segment": segs, "school_major_score": sms,
        "pathway": pathways, "pathway_region": regions, "pathway_eligibility": elig,
        "province_exam_rule": per, "enrollment_rule": enr,
        "school_profile": prof, "school_life": life,
    }

    # ------------------------------------------------------------------ #
    # 输出
    # ------------------------------------------------------------------ #
    print("=== Golden Layer 计划 ===")
    for t in TABLE_ORDER:
        n = len(tables[t])
        d = len(ledger.get(t, []))
        print(f"  {t:22s} {n:>7} 行   丢弃/待裁 {d:>5}")
        plan["tables"][t] = {"rows": n, "dropped": d}
    plan["tables"]["source"]["note"] = "含登记 17 条 + 产物 inline 三要素扩展"
    plan["ledger_total"] = sum(len(v) for v in ledger.values())

    print("\n=== 台账（丢弃/待裁）明细 ===")
    for t in TABLE_ORDER:
        items = ledger.get(t)
        if not items:
            continue
        print(f"  [{t}] {len(items)} 条")
        for why, cnt in Counter(i["reason"] for i in items).most_common():
            print(f"      {cnt:>6} × {why}")

    if NULL_STAT:
        print("\n=== 口径不明 → 置 NULL（已入库，聚合记录）===")
        for k, n in NULL_STAT.most_common():
            print(f"      {n:>6} 行 × {k}")
        for col, s in NULL_SAMPLES.items():
            if s:
                print(f"          {col} 原值样例（未入库）: {s}")
    plan["nulled"] = {"stat": dict(NULL_STAT), "samples": NULL_SAMPLES}

    if ROUND_STAT:
        print("\n=== 精度转换（已入库，聚合记录）===")
        for k, n in ROUND_STAT.most_common():
            print(f"      {n:>6} 行 × {k}")
        for col, s in ROUND_SAMPLES.items():
            if s:
                print(f"          {col} 样例(原值→入库): {s}")
        plan["rounding"] = {"stat": dict(ROUND_STAT), "samples": ROUND_SAMPLES}

    if NULL_ID_STAT:
        print("\n=== 身份列真实未匹配 → 以 NULL 入库（§8.10.3 红线②，已入库）===")
        for k, n in NULL_ID_STAT.most_common():
            print(f"      {n:>6} 行 × {k}")
        plan["null_identity"] = dict(NULL_ID_STAT)

    if args.scan:
        print("\n(--scan：未写文件)")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    for t in TABLE_ORDER:
        with (OUT / f"{t}.jsonl").open("w", encoding="utf-8") as f:
            for rec in tables[t]:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    (OUT / "_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "_ledger.json").write_text(json.dumps(
        {k: v for k, v in ledger.items()}, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "_source-id-golden.json").write_text(json.dumps(
        {"src_map": src_map,
         "triplet_to_id": {"|".join(str(x) for x in k): v for k, v in trip_map.items()}},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n→ 已写出 {OUT.relative_to(ROOT)}/（12 张表 + _plan/_ledger/_source-id-golden）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
