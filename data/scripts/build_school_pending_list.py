# -*- coding: utf-8 -*-
"""院校库「教育部名单外院校」补录台账与一致性核对（数据工程 ③ — 任务 2.1）

背景
----
`merge_schools.py` 把「河南省招生计划系统」（源 A）与「教育部全国高校名单」（源 B）
按国标代码/院校名合并。31 所院校在**源 B 中不存在**（教育部名单不含军队院校、
不含母体高校的分校/校区、不含中国香港院校），因此源 B 无法提供 `city` / `ownership`。

这 31 所已于 2026-10-13 由 ③ 依据**官方来源**单独核定并补录，写入：
    data/schools/school_unmatched_supplement.json

本脚本不修改数据，只做两件事：
1. 生成「名单外院校」台账（类别 / city / ownership / 来源）
2. 核对 supplement 是否已 100% 正确应用到 `schools_merged.json`

产出
----
    data/schools/school_pending_unmatched.json   — 台账 + 核对结果

运行
----
    python data/scripts/build_school_pending_list.py            # 生成台账
    python data/scripts/build_school_pending_list.py --check    # 有未补/不一致则退出码 1
"""

from __future__ import annotations

import json
import os
import sys
from typing import Dict, List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_DIR = os.path.dirname(BASE_DIR)
DIR = os.path.join(BASE_DIR, "schools")
SRC = os.path.join(DIR, "schools_merged.json")
SUP = os.path.join(DIR, "school_unmatched_supplement.json")
OUT = os.path.join(DIR, "school_pending_unmatched.json")

HK_MACAU_TAIWAN = "港澳台院校"
MILITARY = "军队院校"
CAMPUS = "母体高校分校/校区"

# 母体高校分校 → 母体院校名（补录值来源说明）
CAMPUS_PARENT = {
    "复旦大学医学院": "复旦大学",
    "浙江大学医学院": "浙江大学",
    "山东大学威海分校": "山东大学",
    "东北大学秦皇岛分校": "东北大学",
    "中国石油大学(北京)克拉玛依校区": "中国石油大学(北京)",
    "内蒙古科技大学包头师范学院": "内蒙古科技大学",
    "内蒙古科技大学包头医学院": "内蒙古科技大学",
}


def classify(rec: dict) -> str:
    if (rec.get("province") or "") in ("中国香港", "中国澳门", "中国台湾"):
        return HK_MACAU_TAIWAN
    code = (rec.get("code") or "").strip()
    if code[:2] in ("91", "92"):  # 军队院校国标代码段
        return MILITARY
    return CAMPUS


def main() -> int:
    check_mode = "--check" in sys.argv

    for p in (SRC, SUP):
        if not os.path.exists(p):
            print(f"❌ 缺少 {p}", file=sys.stderr)
            return 2

    records = json.load(open(SRC, encoding="utf-8"))["records"]
    sup = json.load(open(SUP, encoding="utf-8"))
    sup_by_code: Dict[str, dict] = {r["code"]: r for r in sup["records"]}
    sup_by_name: Dict[str, dict] = {r["name"]: r for r in sup["records"]}

    def empty(v):
        return v is None or str(v).strip() == ""

    # 「名单外」= 未匹配上源 B（_match 为空）
    outside = [r for r in records if empty(r.get("_match"))]

    items: List[dict] = []
    remaining: List[str] = []
    mismatch: List[str] = []
    groups: Dict[str, int] = {}

    for r in sorted(outside, key=lambda x: x["id"]):
        cat = classify(r)
        groups[cat] = groups.get(cat, 0) + 1
        s = sup_by_code.get((r.get("code") or "").strip()) or sup_by_name.get(r["name"])
        applied = bool(r.get("_supplement"))
        item = {
            "id": r["id"],
            "name": r["name"],
            "code": r.get("code") or "",
            "province": r.get("province") or "",
            "category": cat,
            "city": r.get("city") or "",
            "ownership": r.get("ownership") or "",
            "supplemented": applied,
        }
        if s is not None:
            item["source_id"] = s.get("source_id", "")
            item["source_url"] = s.get("source_url", "")
            item["ownership_basis"] = s.get("ownership_basis", "")
            # 一致性核对
            if r.get("city") != s.get("city") or r.get("ownership") != s.get("ownership"):
                mismatch.append(r["name"])
                item["consistent"] = False
            else:
                item["consistent"] = True
        elif empty(r.get("city")) or empty(r.get("ownership")):
            remaining.append(r["name"])
            item["consistent"] = "n/a"
        items.append(item)

    ok = not remaining and not mismatch
    result = {
        "meta": {
            "target_table": "school",
            "generated_from": "schools_merged.json + school_unmatched_supplement.json",
            "outside_moe_list": len(items),
            "supplemented": sum(1 for i in items if i.get("supplemented")),
            "remaining_unfilled": len(remaining),
            "inconsistent": len(mismatch),
            "category_stats": groups,
            "status": "OK（名单外院校已全部补录且与补录源一致）" if ok else "ATTENTION",
            "note": "源 B（教育部名单）不含军队院校 / 母体分校 / 港澳院校；"
                    "其 city/ownership 由官方来源单独核定，见 school_unmatched_supplement.json",
        },
        "items": items,
    }

    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print(f"名单外院校（源 B 不含）：{len(items)} 所")
    for cat, n in groups.items():
        print(f"   {cat}：{n} 所")
    print(f"已补录 {result['meta']['supplemented']} ｜ 未补 {len(remaining)} ｜ 不一致 {len(mismatch)}")
    for x in remaining:
        print(f"   ⏸ 未补：{x}")
    for x in mismatch:
        print(f"   ⚠️ 不一致：{x}")
    print(f"   → {os.path.relpath(OUT, ROOT_DIR)}")

    if check_mode and not ok:
        print("❌ 核对未通过（存在未补或不一致项）", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
