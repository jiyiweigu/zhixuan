# -*- coding: utf-8 -*-
"""
院校库合并脚本（数据工程 ③ — 任务 2.1）

把两个源合并成完整的 `school` 表数据：

  源 A：河南省招生计划查询系统（fetch_schools.py）
        → 提供「在豫招生的院校清单」+ 教育部国标代码 + 批次
  源 B：教育部《全国普通高等学校名单》（fetch_moe_schools.py）
        → 提供 所在地(province/city) / 层次 / 主管部门

合并键：教育部国标代码（5 位）
  - 两边都有代码时精确匹配（首选）
  - 代码缺失时用院校名精确匹配
  - 仍匹配不上 → 保留源 A 记录并标记 unmatched（不编造）

字段填充优先级
--------------
province : 源B（教育部名单更权威）> 源A
city     : 源B
level    : 源A批次判定（在豫招生批）> 源B
ownership: 由源B「主管部门」推断（公办/民办），无法判断留空
website / intro : 两源均无 → 保持空，data_status=pending

运行
----
    python data/scripts/merge_schools.py
"""

from __future__ import annotations

import csv
import json
import os
import sys
from typing import Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_DIR = os.path.dirname(BASE_DIR)
DIR = os.path.join(BASE_DIR, "schools")

CSV_FIELDS = ["id", "name", "code", "province", "city",
              "level", "type", "ownership", "website", "intro",
              "source_id", "source_name", "source_url", "year", "data_status"]

# 民办高校特征词（主管部门为「XX省教育厅」时不足以判断，需名称/主管部门综合判断）
PRIVATE_HINTS = ("民办", "独立学院", "职业技术学院（民办）")


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def infer_ownership(name: str, dept: str) -> str:
    """
    由教育部名单的「主管部门」推断办学性质。

    实测规律（已用已知公办/民办院校交叉验证）
    ------------------------------------------
    教育部《全国普通高等学校名单》中，主管部门字段的取值本身即区分公办/民办：

      | 主管部门形态              | 含义                     | 判定   |
      |---------------------------|--------------------------|--------|
      | `教育部` / `国家XX委` / 部委 | 中央部委直属             | 公办   |
      | `河南省` / `广东省`（省名）  | 省属公办                 | 公办   |
      | `河南省教育厅`（省+教育厅）  | **民办 / 独立学院**       | 民办   |

    验证样本：
      郑州大学      → 河南省        → 公办 ✓
      河南大学      → 河南省        → 公办 ✓
      黄河科技学院   → 河南省教育厅  → 民办 ✓
      郑州升达经贸管理学院 → 河南省教育厅 → 民办 ✓
      河北大学工商学院（独立学院）→ 河北省教育厅 → 民办 ✓

    ⚠️ 判不出就返回空字符串——**绝不猜**。
    """
    d = (dept or "").strip()
    if not d:
        return ""

    # 省教育厅 / 市教育局主管 → 民办（含独立学院）
    if "教育厅" in d or "教育局" in d:
        return "民办"

    # 中央部委 / 其他中央机构 → 公办
    if "教育部" in d or "委员会" in d or d.endswith("部"):
        return "公办"

    # 省名 / 自治区名（不含"厅局"后缀）→ 省属公办
    if d.endswith(("省", "自治区", "市")) or "自治区" in d:
        return "公办"

    return ""


def main() -> int:
    a_path = os.path.join(DIR, "schools.json")
    b_path = os.path.join(DIR, "moe_schools.json")
    if not (os.path.exists(a_path) and os.path.exists(b_path)):
        print("❌ 缺少输入。请先跑 fetch_schools.py 与 fetch_moe_schools.py", file=sys.stderr)
        return 2

    src_a = load(a_path)
    src_b = load(b_path)

    # 建索引：国标代码 → 记录；院校名 → 记录
    by_code: Dict[str, dict] = {}
    by_name: Dict[str, dict] = {}
    for r in src_b["records"]:
        c = (r.get("national_code") or "").strip()
        n = (r.get("name") or "").strip()
        if c and c not in by_code:
            by_code[c] = r
        if n and n not in by_name:
            by_name[n] = r

    merged: List[dict] = []
    unmatched: List[dict] = []
    match_code = match_name = 0

    for idx, s in enumerate(src_a["records"], start=1):
        code = (s.get("code") or "").strip()
        name = (s.get("name") or "").strip()

        b = by_code.get(code) if code else None
        hit = "code"
        if b is None:
            b = by_name.get(name)
            hit = "name"
        if b is None:
            # 尝试去掉括号后缀（如「北京交通大学(威海校区)」→「北京交通大学」）再匹配
            base = name.split("(")[0].split("（")[0].strip()
            b = by_name.get(base)
            hit = "name-base"

        row = {
            "id": idx,
            "name": name,
            "code": code,
            "province": (b or {}).get("province") or s.get("province", ""),
            "city": (b or {}).get("city", ""),
            "level": s.get("level") or (b or {}).get("level", ""),
            "type": "",                       # 两源均无，待补
            "ownership": infer_ownership(name, (b or {}).get("department", "")),
            "website": "",                    # 待补
            "intro": "",                      # 待补
            "_henan_code": s.get("_henan_code", ""),
            "_department": (b or {}).get("department", ""),
            "_match": hit if b else "",
            "source_id": s.get("source_id", ""),
            "source_name": s.get("source_name", ""),
            "source_url": s.get("source_url", ""),
            "year": s.get("year", 2026),
            "data_status": "partial",         # 已补 province/city/level，仍缺 type/website/intro
        }
        if b:
            if hit == "code":
                match_code += 1
            else:
                match_name += 1
        else:
            unmatched.append({"name": name, "code": code,
                              "_henan_code": s.get("_henan_code", "")})

        # 若 type/website/intro 都空，状态退回 pending
        if not row["type"] and not row["website"] and not row["intro"]:
            row["data_status"] = "pending"

        merged.append(row)

    prov_stats: Dict[str, int] = {}
    for r in merged:
        prov_stats[r["province"]] = prov_stats.get(r["province"], 0) + 1

    payload = {
        "meta": {
            "target_table": "school",
            "sources": [
                {"id": src_a["meta"]["source_id"], "name": src_a["meta"]["source_name"],
                 "url": src_a["meta"]["source_url"]},
                {"id": src_b["meta"]["source_id"], "name": src_b["meta"]["source_name"],
                 "url": src_b["meta"]["source_url"]},
            ],
            "year": 2026,
            "school_count": len(merged),
            "match_stats": {
                "by_code": match_code,
                "by_name": match_name,
                "unmatched": len(unmatched),
            },
            "province_stats": dict(sorted(prov_stats.items(), key=lambda kv: -kv[1])),
            "field_status": {
                "filled": ["id", "name", "code", "province", "city", "level"],
                "partial": ["ownership"],
                "pending": ["type", "website", "intro"],
                "note": "type 需测绘/学科门类数据；website/intro 需各校官网；严禁编造",
            },
        },
        "records": merged,
        "unmatched": unmatched,
    }

    jp = os.path.join(DIR, "schools_merged.json")
    with open(jp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    cp = os.path.join(DIR, "schools.csv")
    with open(cp, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS + ["_henan_code", "_department", "_match"])
        w.writeheader()
        for r in merged:
            w.writerow({k: r.get(k, "") for k in CSV_FIELDS + ["_henan_code", "_department", "_match"]})

    print(f"✅ 合并完成：{len(merged)} 所")
    print(f"   代码匹配 {match_code} ｜ 名称匹配 {match_name} ｜ 未匹配 {len(unmatched)}")
    filled_city = sum(1 for r in merged if r["city"])
    filled_own = sum(1 for r in merged if r["ownership"])
    print(f"   已填 city {filled_city} ｜ 已推断 ownership {filled_own}")
    if unmatched:
        print(f"   ⚠️ 未匹配（前 10）：")
        for u in unmatched[:10]:
            print(f"      {u['name']} [{u['code']}]")
    print(f"   → {os.path.relpath(jp, ROOT_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
