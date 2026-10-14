# -*- coding: utf-8 -*-
"""
资格规则数据一致性校验（数据工程 ③）

背景
----
`pathway-eligibility.json` 里 `national-special` 的 `county_codes` 是从
`pathway-regions.json` 抄来的。人工抄写已实测出错（多了一个 411322 方城县，
它属省定 15 县、不在国家专项内）。

  为杜绝这类错误，本脚本做三件事：
1. **校验**：比对两份文件中的县码集合是否严格一致；
2. **修复**：`--fix` 时用区域表的权威结果回写 eligibility 文件；
3. **引用完整性**：`pathway-eligibility.json` / `pathway-regions.json` 中每条 `pathway_id`
   必须存在于 `pathways-26.json`（途字字典）。**只报不改** —— id 改名属口径判断，
   须人工确认后手改（避免脚本猜出一个错的 id 反而把错误固化）。

运行
----
    python data/scripts/check_eligibility_consistency.py          # 只校验
    python data/scripts/check_eligibility_consistency.py --fix    # 校验并回写县码
"""

from __future__ import annotations

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGION_FILE = os.path.join(BASE_DIR, "dictionaries", "pathway-regions.json")
ELIG_FILE = os.path.join(BASE_DIR, "dictionaries", "pathway-eligibility.json")
PATHWAY_FILE = os.path.join(BASE_DIR, "dictionaries", "pathways-26.json")


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def region_codes(regions: list, pathway_id: str) -> set[str]:
    return {r["county_code"] for r in regions if r["pathway_id"] == pathway_id}


def find_region_rule(rules: list, pathway_id: str) -> dict | None:
    for rule in rules:
        if rule.get("pathway_id") == pathway_id and rule.get("rule_type") == "区域":
            return rule
    return None


def pathway_ids() -> set[str]:
    """途字字典（权威 id 清单）。"""
    return {p["id"] for p in load(PATHWAY_FILE)["pathways"]}


def check_pathway_refs(regions: list, rules: list, placeholders: list) -> bool:
    """`pathway_id` 引用完整性：必须存在于 pathways-26.json。

    placeholders 例外 —— 它们本就 `data_status=schema_only`、`source_id=null`，
    是刻意保留的「骨架占位」，允许不出现在 26 条字典中。

    只报不改：悬空 id 的正确值属口径判断，脚本不猜。
    """
    ids = pathway_ids()
    print(f"[途字字典] pathways-26 = {len(ids)} 条")

    ok = True
    for label, rows in (("regions", regions), ("rules", rules)):
        dangling = sorted({r["pathway_id"] for r in rows} - ids)
        if dangling:
            ok = False
            print(f"❌ {label} 悬空 pathway_id {len(dangling)} 个：{dangling}")
            for r in rows:
                if r["pathway_id"] in dangling:
                    print(f"     · {r['pathway_id']} | "
                          f"{r.get('pathway_name') or r.get('county_name') or r.get('province')}"
                          f" | rule_type={r.get('rule_type')}")
            print("     处置：确认为字典中哪一条后**手改 id**（本脚本不自动改名，避免猜错固化）")
        else:
            n = len({r["pathway_id"] for r in rows})
            print(f"✅ {label} pathway_id 引用完整（{n} 个 id 引用，全部在字典内）")

    ph_dangling = sorted({r["pathway_id"] for r in placeholders} - ids)
    print(f"ℹ️  placeholders 占位 {len(placeholders)} 条"
          f"（不在字典内 {len(ph_dangling)} 个：{ph_dangling}，设计允许）")
    return ok


def main() -> int:
    region_doc = load(REGION_FILE)
    elig_doc = load(ELIG_FILE)

    regions = region_doc["regions"]
    rules = elig_doc["rules"]

    nat_codes = region_codes(regions, "national-special")
    col_codes = region_codes(regions, "college-special")

    print(f"[区域表] national-special = {len(nat_codes)} 县")
    print(f"[区域表] college-special  = {len(col_codes)} 县")
    print(f"[区域表] 高校独有（省定15）= {len(col_codes - nat_codes)} 县")
    print()

    ok = True

    # ── 校验 national-special 显式 county_codes ──
    rule = find_region_rule(rules, "national-special")
    if rule is None:
        print("❌ eligibility 中找不到 national-special 的「区域」规则")
        return 2

    declared = set(rule["params"].get("county_codes") or [])
    if declared == nat_codes:
        print(f"✅ national-special county_codes 一致（{len(declared)} 条）")
    else:
        ok = False
        print("❌ national-special county_codes 不一致")
        only_region = nat_codes - declared
        only_elig = declared - nat_codes
        if only_elig:
            print(f"   eligibility 多了 {len(only_elig)} 个：{sorted(only_elig)}")
        if only_region:
            print(f"   eligibility 少了 {len(only_region)} 个：{sorted(only_region)}")

        if "--fix" in sys.argv:
            rule["params"]["county_codes"] = sorted(nat_codes)
            rule["params"]["count"] = len(nat_codes)
            with open(ELIG_FILE, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(elig_doc, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            print(f"   🔧 已用区域表结果回写 {os.path.relpath(ELIG_FILE, BASE_DIR)}")
            ok = True

    # ── 校验 college-special 的 count 声明 ──
    col_rule = find_region_rule(rules, "college-special")
    if col_rule is not None and col_rule["params"].get("count") == len(col_codes):
        print(f"✅ college-special count 一致（{len(col_codes)}）")
    elif col_rule is not None:
        ok = False
        print(f"❌ college-special count 不一致："
              f"声明 {col_rule['params'].get('count')}，实际 {len(col_codes)}")

    # ── 结构自检：38 ⊂ 53 ──
    if nat_codes.issubset(col_codes):
        print("✅ 国家专项 38 县 ⊂ 高校专项 53 县")
    else:
        ok = False
        print(f"❌ 集合包含关系不成立：多出 {sorted(nat_codes - col_codes)}")

    # ── 引用完整性：pathway_id 必须存在于途字字典 ──
    print()
    if not check_pathway_refs(regions, rules, elig_doc.get("placeholders") or []):
        ok = False

    print()
    print("结论：" + ("✅ 全部一致" if ok else "❌ 存在不一致"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
