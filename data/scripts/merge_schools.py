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
website / intro : 两源均无 → 保持空，data_status=schema_only

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

# ★ 契约枚举（validate.py VALID_DATA_STATUS，契约 v1.3 §8.1）——不得自创取值
#   schema_only = 结构已就绪；数据来自渠道/公开源、未对官方逐条核实，核实通过后才升 available
DATA_STATUS_SCHEMA_ONLY = "schema_only"

# 民办高校特征词（主管部门为「XX省教育厅」时不足以判断，需名称/主管部门综合判断）
PRIVATE_HINTS = ("民办", "独立学院", "职业技术学院（民办）")

# 中央机构 / 全国性人民团体白名单（显式枚举，避免后缀规则歧义误判）
# 说明：这些机构不属于「省/市」也不以「部」结尾，普通后缀规则覆盖不到，
#      但它们直属中央、办学经费由国家财政拨付，必为公办。
CENTRAL_AGENCIES = (
    "中国科学院",
    "中国社会科学院",
    "国家民委",
    "国家卫生健康委员会",
    "国家体育总局",
    "国家消防救援局",
    "海关总署",
    "中央办公厅",
    "中央统战部",
    "共青团中央",
    "中华全国总工会",
    "中华妇女联合会",
    "新疆生产建设兵团",
    "上海市 中国科学院",  # 教育部名单中的拼接脏值，实为「上海市 / 中国科学院」共建
)


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def infer_ownership(name: str, dept: str) -> str:
    """
    由教育部名单的「主管部门」推断办学性质。

    实测规律（已用已知公办/民办院校交叉验证）
    ------------------------------------------
    教育部《全国普通高等学校名单》中，主管部门字段的取值本身即区分公办/民办：

      | 主管部门形态                        | 含义                | 判定   |
      |-------------------------------------|---------------------|--------|
      | `教育部` / `国家XX部` / `XX部`         | 中央部委直属         | 公办   |
      | `中国科学院` / `社科院` / `海关总署` 等 | 中央机构（白名单）    | 公办   |
      | `河南省` / `广东省`（省·自治区·市名）  | 省属公办            | 公办   |
      | `河南省教育厅`（省+教育厅/教育局/教委）| **民办 / 独立学院**  | 民办   |

    验证样本：
      郑州大学      → 河南省        → 公办 ✓
      河南大学      → 河南省        → 公办 ✓
      黄河科技学院   → 河南省教育厅  → 民办 ✓
      郑州升达经贸管理学院 → 河南省教育厅 → 民办 ✓
      河北大学工商学院（独立学院）→ 河北省教育厅 → 民办 ✓
      上海纽约大学   → 上海市教委     → 民办 ✓（与昆山杜克/西交利物浦等既有口径一致）
      中国科学院大学  → 中国科学院    → 公办 ✓

    ⚠️ 判不出就返回空字符串——**绝不猜**。
    """
    d = (dept or "").strip()
    if not d:
        return ""

    # 1) 地方教育行政部门主管 → 民办（含独立学院 / 中外合作办学）
    #    「教委」＝直辖市级教育行政部门（北京/上海/天津/重庆），与「教育厅」同义。
    if any(k in d for k in ("教育厅", "教育局", "教委")):
        return "民办"

    # 2) 省名 / 自治区名 / 直辖市名（政府本体，不含"厅局委"后缀）→ 省属公办
    if d.endswith(("省", "自治区", "市")) or "自治区" in d:
        return "公办"

    # 3) 中央部委 → 公办（保留带括号写法：「交通运输部（中国民用航空局）」）
    if d.endswith("部") or "部（" in d or "部(" in d:
        return "公办"

    # 4) 中央机构 / 全国性人民团体白名单 → 公办
    if d in CENTRAL_AGENCIES:
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

    # 加载「教育部名单外院校」人工核定补录（军校 / 母体分校 / 港澳院校）
    # 关键：源 B 不含这些院校，其 city/ownership 由 ③ 依据官方来源单独核定，
    #       与「由主管部门推导」的常规路径分开存放，来源写入 _supplement 便于追溯。
    supplement: Dict[str, dict] = {}
    sup_path = os.path.join(DIR, "school_unmatched_supplement.json")
    if os.path.exists(sup_path):
        for rec in load(sup_path).get("records", []):
            c = (rec.get("code") or "").strip()
            n = (rec.get("name") or "").strip()
            if c:
                supplement[c] = rec
            if n:
                supplement["name:" + n] = rec
    sup_used = 0

    # 加载 D2/D5 字段补丁：type（软科榜单）与 website/intro（软科院校详情）
    # 关键：软科为**第三方非官方**来源 → 一律「仅填空值」并在记录内写入 _*_src 溯源标记；
    #       website 仅当本机实测校验通过（HTTP 200 + 页面出现校名）才写入主字段，
    #       否则降级为 _website_candidate 候选（不得入库，宁可缺不可猜）。
    def _load_supp(fname: str, key: str) -> Dict[str, dict]:
        out: Dict[str, dict] = {}
        p = os.path.join(DIR, fname)
        if os.path.exists(p):
            for rec in load(p).get("records", []):
                n = (rec.get(key) or rec.get("name") or "").strip()
                if n and n not in out:
                    out[n] = rec
        return out

    type_supp = _load_supp("school_type_supplement.json", "school_name")
    web_supp = _load_supp("school_web_intro_supplement.json", "school_name")
    official_intro = _load_supp("school_official_intro_supplement.json", "name")
    type_used = web_used = intro_used = web_cand = official_intro_used = 0

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
            "data_status": DATA_STATUS_SCHEMA_ONLY,   # ★ 契约枚举；对官方逐条核实通过后才升 available
        }
        if b:
            if hit == "code":
                match_code += 1
            else:
                match_name += 1
        else:
            unmatched.append({"name": name, "code": code,
                              "_henan_code": s.get("_henan_code", "")})
            # 教育部名单外院校：应用人工核定补录（来源写入 _supplement）
            sup_rec = supplement.get(code) or supplement.get("name:" + name)
            if sup_rec is not None:
                if sup_rec.get("city"):
                    row["city"] = sup_rec["city"]
                if sup_rec.get("ownership"):
                    row["ownership"] = sup_rec["ownership"]
                row["_supplement"] = {
                    "source_id": sup_rec.get("source_id", ""),
                    "source_url": sup_rec.get("source_url", ""),
                    "ownership_basis": sup_rec.get("ownership_basis", ""),
                }
                sup_used += 1

        # ── D2/D5 补丁：type / website / intro（仅填空值；来源写入 _*_src）──
        tsup = type_supp.get(name)
        if tsup and not row["type"] and tsup.get("type"):
            row["type"] = tsup["type"]
            row["_type_src"] = {
                "source_id": tsup.get("source_id", "SRC-SHANGHAIRANKING"),
                "matched_by": tsup.get("matched_by", ""),
                "official": False,
            }
            type_used += 1
        wsup = web_supp.get(name)
        if wsup:
            if not row["website"] and wsup.get("website"):
                if wsup.get("website_verified"):
                    row["website"] = wsup["website"]
                    row["_website_src"] = {
                        "discovery": "SRC-SHANGHAIRANKING",
                        "source_type": "高校官网",
                        "source_name": "该校官网（软科候选 + 本机实测校验通过）",
                        "source_url": wsup.get("website_final_url") or wsup["website"],
                        "year": 2026,
                        "official": True,
                        "http_status": wsup.get("website_http_status"),
                        "name_hit": bool(wsup.get("website_name_hit")),
                    }
                    web_used += 1
                else:
                    row["_website_candidate"] = {
                        "url": wsup["website"],
                        "verified": False,
                        "note": wsup.get("website_note", ""),
                        "official": False,
                        "discovery": "SRC-SHANGHAIRANKING",
                    }
                    web_cand += 1
            if not row["intro"] and wsup.get("intro"):
                row["intro"] = wsup["intro"]
                row["_intro_src"] = {
                    "source_id": "SRC-SHANGHAIRANKING",
                    "source_name": "上海软科教育信息咨询有限公司（软科中国大学排名）",
                    "source_url": wsup.get("srk_url", ""),
                    "year": 2024,
                    "official": False,
                }
                intro_used += 1

        # 官方简介优先（逐校官网「学校简介」页），覆盖上面的软科非官方值
        osup = official_intro.get(name)
        if osup and osup.get("intro"):
            row["intro"] = osup["intro"]
            row["_intro_src"] = {
                "source_type": "高校官网",
                "source_name": osup.get("source_name", f"{name}官网·学校简介"),
                "source_url": osup.get("source_url", ""),
                "year": 2026,
                "official": True,
            }
            official_intro_used += 1

        # ★ `data_status` 语义 = 「核实状态」，非「完整度」（完整度见 meta.field_status）。
        #   团队枚举仅 pending / schema_only / verified；院校库整体未经 L2 官方核实（E3），
        #   故**一律 pending**——不得因字段已补而升格。
        merged.append(row)

    # ── N21 事实表补录：院校库未收录、但**事实数据出现过**的院校 ──────────
    #  来源：`school_fact_supplement.json`（由 build_school_fact_supplement.py 生成）
    #  字段**全部**取自教育部名单（SRC-MOE-SCHOOL-LIST），来源逐条写入 `_supplement`。
    #  ★ 本轮只并入**本科**（`supplement_records_benke`）——与院校库现有口径一致；
    #    专科补录清单单列（`supplement_records_zhuanke`），待口径裁决（见 N22）。
    fact_sup: List[dict] = []
    sup_fact_path = os.path.join(DIR, "school_fact_supplement.json")
    if os.path.exists(sup_fact_path):
        fact_sup = load(sup_fact_path).get("supplement_records_benke", [])
    base_id = len(merged)
    fact_sup = sorted(fact_sup, key=lambda r: r["name"])
    for k, rec in enumerate(fact_sup, start=1):
        merged.append({
            "id": base_id + k,
            "name": rec["name"],
            "code": rec.get("code", ""),
            "province": rec.get("province", ""),
            "city": rec.get("city", ""),
            "level": rec.get("level", ""),
            "type": "",
            "ownership": rec.get("ownership", ""),
            "website": "",
            "intro": "",
            "_henan_code": "",          # 该院校不在河南 2026 招生计划（正因如此才漏收）
            "_department": rec.get("department", ""),
            "_match": "fact-supplement",
            "_supplement": {
                "source_id": rec.get("source_id", ""),
                "source_url": rec.get("source_url", ""),
                "basis": rec.get("basis", ""),
                "ownership_basis": rec.get("ownership_basis", ""),
                "province_basis": rec.get("province_basis", ""),
                "aliases_from": rec.get("aliases_from", []),
            },
            "source_id": rec.get("source_id", ""),
            "source_name": rec.get("source_name", ""),
            "source_url": rec.get("source_url", ""),
            "year": rec.get("year", 2026),
            "data_status": DATA_STATUS_SCHEMA_ONLY,
        })

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
                "supplemented": sup_used,
                "fact_supplement": len(fact_sup),
                "type_filled": type_used,
                "website_filled": web_used,
                "website_candidate_only": web_cand,
                "intro_filled": intro_used,
                "intro_official_filled": official_intro_used,
            },
            "province_stats": dict(sorted(prov_stats.items(), key=lambda kv: -kv[1])),
            "field_status": {
                "filled": ["id", "name", "code", "province", "city", "level",
                           "ownership", "type", "website", "intro"],
                "partial": [],
                "pending": [],
                "city_coverage": f"{sum(1 for r in merged if r['city'])}/{len(merged)}",
                "ownership_coverage": f"{sum(1 for r in merged if r['ownership'])}/{len(merged)}",
                "type_coverage": f"{sum(1 for r in merged if r['type'])}/{len(merged)}",
                "website_coverage": f"{sum(1 for r in merged if r['website'])}/{len(merged)}",
                "intro_coverage": f"{sum(1 for r in merged if r['intro'])}/{len(merged)}",
                "note": "city/ownership 由源B「主管部门」推导 + 名单外 31 所官方补录（_supplement）；"
                        "type/website 为 **D2/D5 软科补丁（★非官方）**，仅填空值，逐条溯源见 _type_src / _website_src；"
                        "website 仅「实测校验通过」者写入主字段（官方级），未通过者降级 _website_candidate；"
                        "intro 采 **官方来源优先**（逐校官网「学校简介」页，_intro_src.official=true），"
                        "无官方者回退软科简介（非官方）；类型口径待裁（见 契约裁决请求_徐.md N5/N16）；严禁编造",
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
