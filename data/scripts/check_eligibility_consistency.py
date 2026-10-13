# -*- coding: utf-8 -*-
"""
资格规则数据一致性校验（数据工程 ③）

背景
----
`pathway-eligibility.json` 里 `national-special` 的 `county_codes` 是从
`pathway-regions.json` 抄来的。人工抄写已实测出错（多了一个 411322 方城县，
它属省定 15 县、不在国家专项内）。

为杜绝这类错误，本脚本做两件事：
1. **校验**：比对两份文件中的县码集合是否严格一致；
2. **修复**：`--fix` 时用区域表的权威结果回写 eligibility 文件。

运行
----
    python data/scripts/check_eligibility_consistency.py          # 只校验
    python data/scripts/check_eligibility_consistency.py --fix    # 校验并回写
"""

from __future__ import annotations

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGION_FILE = os.path.join(BASE_DIR, "dictionaries", "pathway-regions.json")
ELIG_FILE = os.path.join(BASE_DIR, "dictionaries", "pathway-eligibility.json")


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

    print()
    print("结论：" + ("✅ 全部一致" if ok else "❌ 存在不一致"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
