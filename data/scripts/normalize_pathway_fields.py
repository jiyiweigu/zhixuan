#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
pathway 系列字典补缺 / 口径归一（D7）

对照目标表（backend/app/models/pathway.py）逐个字段核对，本脚本处理三处缺漏：

  1) pathway.source_id —— 模型为 NOT NULL 外键，而 pathways-26.json 只有内联三要素
     （source_name / source_url / year），**缺 source_id**。
     处理：用三要素去 data/sources/source-table.json 反查 SRC-XXX 写入。
     （实测 26 条三要素 **全部在册**，0 条落空）

  2) pathway_eligibility.year —— 模型为 NOT NULL Integer，而规则的 JSON 缺该字段。
     处理：取**其所属途径字典的年份**（pathway.year = 2025）。
     ⚠️ 这是唯一一处需要「定口径」的补值，理由与备选见 meta.year_basis；
        如规则引擎按 2026 高考年份取值，需队长裁定后改为 2026。

  3) pathway_region.province —— 同表其他数据（school / province_exam_rule /
     pathway_eligibility）一律用「河南」，本文件却是「河南省」，会导致跨表 join 落空。
     处理：province 归一为「河南」，原值保留在 province_raw（不改写、可回溯）。

**幂等**：重复执行结果不变（已有 source_id / year / province_raw 时跳过）。

用法
  python data/scripts/normalize_pathway_fields.py
  python data/scripts/normalize_pathway_fields.py --check   # 只报告不写
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DICT = ROOT / "data" / "dictionaries"
SOURCE_TABLE = ROOT / "data" / "sources" / "source-table.json"

F_PATHWAYS = DICT / "pathways-26.json"
F_ELIGIBILITY = DICT / "pathway-eligibility.json"
F_REGIONS = DICT / "pathway-regions.json"

# pathway_eligibility.year 的取数依据（口径）
ELIGIBILITY_YEAR_BASIS = (
    "取所属途径字典的年份 pathway.year=2025：资格规则是对途径的资格限定，与途径字典同版本。"
    "备选为 2026（P0 两省高考年份，与 province_exam_rule 一致）；"
    "若规则引擎按高考年份取值，需队长裁定后统一为 2026。"
)
PROVINCE_ALIAS = {"河南省": "河南", "江西省": "江西"}


def load(p: Path):
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def dump(p: Path, data) -> None:
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    src = load(SOURCE_TABLE)["sources"]
    tri2id = {(s["source_name"], s["source_url"], s["year"]): s["id"] for s in src}
    print("=" * 70)
    print("D7 pathway 系列字典补缺 / 口径归一")
    print("=" * 70)

    changed = {"pathways_added_source_id": 0, "eligibility_added_year": 0,
               "regions_normalized_province": 0}

    # ── 1) pathways-26.json：补 source_id ─────────────────────────
    pw = load(F_PATHWAYS)
    recs = pw["pathways"]
    miss = []
    for r in recs:
        if r.get("source_id"):
            continue
        t = (r.get("source_name"), r.get("source_url"), r.get("year"))
        sid = tri2id.get(t)
        if sid:
            r["source_id"] = sid
            changed["pathways_added_source_id"] += 1
        else:
            miss.append((r.get("id"), t))
    used = Counter(r.get("source_id") for r in recs)
    print(f"[1] pathways-26.json  补 source_id: {changed['pathways_added_source_id']}/{len(recs)}"
          f"  落空 {len(miss)}")
    for k, v in used.items():
        print(f"      {k}: {v} 条")
    for m in miss:
        print(f"      ⚠️ 三要素不在册: {m}")

    # ── 2) pathway-eligibility.json：补 year ─────────────────────
    el = load(F_ELIGIBILITY)
    pw_year = Counter(r.get("year") for r in recs).most_common(1)[0][0]
    added = 0
    for key in ("rules", "placeholders"):
        for r in el.get(key, []):
            if r.get("year") is None:
                r["year"] = pw_year
                added += 1
    changed["eligibility_added_year"] = added
    n_rules = len(el.get("rules", []))
    print(f"[2] pathway-eligibility.json  补 year(= {pw_year}): {added} 条"
          f"（rules {n_rules} + placeholders {len(el.get('placeholders', []))}）")

    # ── 3) pathway-regions.json：province 归一 ───────────────────
    rg = load(F_REGIONS)
    norm = 0
    for key in ("regions", "counties"):
        for r in rg.get(key, []):
            pv = str(r.get("province") or "")
            if pv in PROVINCE_ALIAS and "province_raw" not in r:
                r["province_raw"] = pv
                r["province"] = PROVINCE_ALIAS[pv]
                norm += 1
    changed["regions_normalized_province"] = norm
    print(f"[3] pathway-regions.json  province 归一「河南省→河南」: {norm} 条"
          f"（regions {len(rg.get('regions', []))} + counties {len(rg.get('counties', []))}）")

    # ── meta 留痕 ────────────────────────────────────────────────
    stamp = {
        "d7_normalized_at": str(date.today()),
        "d7_changes": dict(changed),
        "d7_province_alias": PROVINCE_ALIAS,
    }
    for data, key in ((pw, "_meta"), (el, "meta"), (rg, "meta")):
        data.setdefault(key, {})
        data[key].update(stamp)
    el["meta"]["year_basis"] = ELIGIBILITY_YEAR_BASIS
    el["meta"]["table_fields"] = (
        "id, pathway_id, province, rule_type(户籍/学籍/区域/成绩), rule_desc, "
        "params(json), year, source_id"
    )
    rg["meta"]["province_note"] = (
        "province 已统一为「河南」（与 school / province_exam_rule / pathway_eligibility 一致），"
        "原始值「河南省」保留在 province_raw 字段，未丢弃、可回溯。"
    )

    if args.check:
        print("\n(--check，未写出文件)")
        return 0

    dump(F_PATHWAYS, pw)
    dump(F_ELIGIBILITY, el)
    dump(F_REGIONS, rg)
    print(f"\n✅ 已写回 {F_PATHWAYS.relative_to(ROOT)}")
    print(f"✅ 已写回 {F_ELIGIBILITY.relative_to(ROOT)}")
    print(f"✅ 已写回 {F_REGIONS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
