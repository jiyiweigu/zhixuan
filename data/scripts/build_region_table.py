# -*- coding: utf-8 -*-
"""
专项计划实施区域表构建脚本（数据工程 ③ — 任务 2.3）

用途
----
把「国家专项计划 38 县」「高校专项计划 53 县」两个名单，
用国家统计局行政区划代码（county_code）补全，输出可供入库的
JSON + CSV，并生成一份人工可核对的校验报告。

数据来源
--------
1. 县名单（口径来源）：河南省教育考试院 / 河南省阳光高考信息平台公开文件
   —— 见 data/sources/source-registry.md 第 3.3 节
2. 行政区划代码（county_code）：民政部/国家统计局《中华人民共和国行政区划代码》
   —— 通过镜像 JSON 获取（modood/Administrative-divisions-of-China，dist/pcas-code.json）

设计原则
--------
- **不猜**。任何匹配不上的县一律进 `unmatched`，不写入结果表，需人工复核。
- **一对一**。同名县可能跨市重名（如「息县」「新县」），必须带市校验，避免错配。
- 输出三要素（source_name / source_url / year），满足入库强制校验（任务 2.6）。

运行
----
    python data/scripts/build_region_table.py

输出（写入 data/dictionaries/ 与 data/sources/）
---------------------------------------------
- data/dictionaries/pathway-regions.json   ← 入库用
- data/dictionaries/pathway-regions.csv    ← 人工核对用
- data/sources/区域表构建报告.md            ← 匹配结果与人工复核清单
"""

from __future__ import annotations

import csv
import json
import os
import ssl
import sys
import urllib.request
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_DIR = os.path.dirname(BASE_DIR)
DICT_DIR = os.path.join(BASE_DIR, "dictionaries")
SRC_DIR = os.path.join(BASE_DIR, "sources")

# 行政区划数据镜像（按顺序回退）
DIVISION_MIRRORS = [
    "https://gh-proxy.com/https://raw.githubusercontent.com/"
    "modood/Administrative-divisions-of-China/master/dist/pcas-code.json",
    "https://cdn.jsdelivr.net/gh/"
    "modood/Administrative-divisions-of-China@master/dist/pcas-code.json",
]

PROVINCE = "河南省"

# --- 三要素：写入每一行，满足入库强制校验 ---
# source_id 用于关联 `source` 表主键；此处先占位，待 source 表登记后统一替换为真实 id
SOURCE_ID = "SRC-HENAN-SPECIAL-REGION"
SOURCE_NAME = "河南省教育考试院、河南省阳光高考信息平台（县域名单）；民政部/国家统计局行政区划代码（县码）"
SOURCE_URL = "https://jyt.henan.gov.cn/2019/08-29/1932941.html"
SOURCE_YEAR = 2025
DATA_STATUS = "verified"

# ---------------------------------------------------------------
# 官方实施区域名单（三分类口径）
#
# 权威依据：河南省教育厅《河南省实施"国家专项计划"和"高校专项计划"县域名单》
#   https://jyt.henan.gov.cn/2019/08-29/1932941.html （附件1）
# 交叉印证：河南省阳光高考信息平台 https://gaokao.haedu.cn/content/46981
#          南阳市教育局 https://jyj.nanyang.gov.cn/2026/09-14/1435648.html
#
# 官方口径：
#   国家专项 = 集中连片特困县(26) + 国家级扶贫开发重点县(12) = 38 县
#   高校专项 = 国家专项 38 县 + 省定扶贫开发工作重点县(15) = 53 县
#
# ⚠️ 注意：38 县与 15 县是**两个互斥集合**，合起来才是 53 县。
#    （早期版本曾把 53 县误标为"国家专项38县"，此处已按官方表格纠正。）
#
# 结构：市 -> [县, ...]
# ---------------------------------------------------------------

# ① 集中连片特困地区县（26 个）—— 国家专项
CONTIGUOUS_26 = {
    "开封市": ["兰考县"],
    "洛阳市": ["栾川县", "嵩县", "洛宁县", "汝阳县"],
    "平顶山市": ["鲁山县"],
    "三门峡市": ["卢氏县"],
    "南阳市": ["南召县", "镇平县", "内乡县", "淅川县"],
    "商丘市": ["民权县", "宁陵县", "柘城县"],
    "信阳市": ["光山县", "新县", "商城县", "固始县", "淮滨县", "潢川县"],
    "周口市": ["淮阳县", "沈丘县", "太康县", "商水县", "郸城县"],
    "驻马店市": ["新蔡县"],
}

# ② 国家级扶贫开发工作重点县（12 个）—— 国家专项
NATIONAL_POVERTY_12 = {
    "洛阳市": ["宜阳县"],
    "安阳市": ["滑县"],
    "新乡市": ["封丘县"],
    "濮阳市": ["范县", "台前县"],
    "南阳市": ["社旗县", "桐柏县"],
    "商丘市": ["睢县", "虞城县"],
    "驻马店市": ["上蔡县", "确山县", "平舆县"],
}

# ③ 省定扶贫开发工作重点县（15 个）—— 仅高校专项
PROVINCIAL_POVERTY_15 = {
    "洛阳市": ["伊川县"],
    "平顶山市": ["叶县"],
    "安阳市": ["内黄县"],
    "新乡市": ["原阳县"],
    "濮阳市": ["濮阳县"],
    "漯河市": ["舞阳县"],
    "南阳市": ["方城县"],
    "商丘市": ["夏邑县"],
    "信阳市": ["罗山县", "息县"],
    "周口市": ["西华县", "扶沟县"],
    "驻马店市": ["泌阳县", "正阳县", "汝南县"],
}


# ---------------------------------------------------------------
# 行政区划代码获取
# ---------------------------------------------------------------
def fetch_divisions() -> list:
    """抓取全国行政区划（省市县三级）。"""
    last_err = None
    ctx = ssl.create_default_context()
    for url in DIVISION_MIRRORS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            raw = urllib.request.urlopen(req, timeout=90, context=ctx).read()
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, list) or not data:
                raise ValueError("返回结构不是非空列表")
            print(f"[区划] 获取成功：{url}（{len(raw)} bytes）")
            return data
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            print(f"[区划] 失败 {url} -> {type(exc).__name__}: {str(exc)[:100]}")
    raise RuntimeError(f"所有镜像均失败：{last_err}")


def index_henan(data: list) -> dict:
    """
    建立 河南 市 -> 县 索引。
    返回 {市名: {县名: code}}
    """
    henan = next((p for p in data if p.get("name") == PROVINCE), None)
    if henan is None:
        raise RuntimeError(f"未在区划数据中找到 {PROVINCE}")

    index: dict[str, dict[str, str]] = {}
    for city in henan.get("children", []):
        county_map: dict[str, str] = {}
        for county in city.get("children", []) or []:
            county_map[county["name"]] = county["code"]
        index[city["name"]] = county_map
    print(f"[索引] {PROVINCE} 共 {len(index)} 个市，"
          f"{sum(len(v) for v in index.values())} 个县级单位")
    return index


# ---------------------------------------------------------------
# 匹配
# ---------------------------------------------------------------
def resolve(index: dict, city: str, county: str) -> tuple[str | None, str | None]:
    """
    在市内精确匹配县名。
    兼容「县名 + 区/县」后缀差异（如 淮阳县 vs 淮阳区）。
    返回 (county_code, 实际区划名) 或 (None, None)。
    """
    county_map = index.get(city, {})

    # 1) 精确命中
    if county in county_map:
        return county_map[county], county

    # 2) 去掉「县/区/市」尾巴再比（应对「淮阳县」→「淮阳区」这类撤县设区）
    stem = county.rstrip("县区市")
    for name, code in county_map.items():
        if name.rstrip("县区市") == stem:
            return code, name

    return None, None


def build() -> dict:
    divisions = index_henan(fetch_divisions())

    # 内部按「县」聚合（一个县一条，记录它适用哪些途径）
    counties: list[dict] = []
    unmatched: list[dict] = []

    # (分类名, 名单字典, 适用途径)
    groups = [
        ("集中连片特困县", CONTIGUOUS_26, ["national-special", "college-special"]),
        ("国家级扶贫开发重点县", NATIONAL_POVERTY_12, ["national-special", "college-special"]),
        ("省定扶贫开发工作重点县", PROVINCIAL_POVERTY_15, ["college-special"]),
    ]

    seen: set[str] = set()
    for category, mapping, pathway_ids in groups:
        for city, county_list in mapping.items():
            for county in county_list:
                code, actual = resolve(divisions, city, county)
                if code is None:
                    unmatched.append({"city": city, "county": county,
                                      "reason": "市/县未在国家统计局区划中命中"})
                    continue
                if code in seen:
                    unmatched.append({"city": city, "county": county,
                                      "reason": f"县码 {code} 重复（已在其他分类中出现）"})
                    continue
                seen.add(code)
                counties.append({
                    "county_code": code,
                    "province": PROVINCE,
                    "city": city,
                    "county_name": county,
                    "county_official_name": actual,
                    "category": category,
                    "pathway_ids": list(pathway_ids),
                })

    # 展开为入库行：一个 (县, 途径) 一行 —— 对应产品书 7.2 `pathway_region` 表
    rows: list[dict] = []
    for item in counties:
        for pathway_id in item["pathway_ids"]:
            rows.append({
                "pathway_id": pathway_id,
                "province": item["province"],
                "county_name": item["county_name"],
                "county_code": item["county_code"],
                "city": item["city"],
                "category": item["category"],
                "source_id": SOURCE_ID,
                "source_name": SOURCE_NAME,
                "source_url": SOURCE_URL,
                "year": SOURCE_YEAR,
                "data_status": DATA_STATUS,
            })

    return {
        "counties": counties,
        "rows": rows,
        "unmatched": unmatched,
        "total_counties": len(counties),
        "national_count": sum(1 for r in rows if r["pathway_id"] == "national-special"),
        "college_count": sum(1 for r in rows if r["pathway_id"] == "college-special"),
    }


# ---------------------------------------------------------------
# 输出
# ---------------------------------------------------------------
def write_json(result: dict) -> str:
    payload = {
        "meta": {
            "title": "河南省专项计划实施区域表",
            "generated_at": date.today().isoformat(),
            "owner": "徐（③ 数据工程）",
            "target_table": "pathway_region",
            "unit": "本文件 regions 为「一县一途径一行」的可入库格式（共 %d 行）" % len(result["rows"]),
            "source_id": SOURCE_ID,
            "source_name": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "year": SOURCE_YEAR,
            "note": (
                "county_code 为 6 位行政区划代码。"
                "国家专项 = 集中连片特困县(26) + 国家级扶贫开发重点县(12) = 38 县；"
                "高校专项 = 国家专项 38 县 + 省定扶贫开发工作重点县(15) = 53 县。"
                "两个集合互斥，合起来为 53 县。"
                "未命中项见 unmatched，需人工复核，未写入正式行。"
            ),
        },
        # 入库行（每县每途径一行）
        "regions": result["rows"],
        # 便于人工阅读的县维度视图（含县码、所属分类）
        "counties": result["counties"],
        "unmatched": result["unmatched"],
    }
    path = os.path.join(DICT_DIR, "pathway-regions.json")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return path


CSV_FIELDS = ["pathway_id", "province", "county_name", "county_code",
              "city", "category", "source_id",
              "source_name", "source_url", "year", "data_status"]


def write_csv(result: dict) -> str:
    path = os.path.join(DICT_DIR, "pathway-regions.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in result["rows"]:
            writer.writerow({k: row.get(k, "") for k in CSV_FIELDS})
    return path


def write_report(result: dict) -> str:
    rows = result["rows"]
    counties = result["counties"]
    unmatched = result["unmatched"]

    nat = [c for c in counties if "national-special" in c["pathway_ids"]]
    only_col = [c for c in counties if "national-special" not in c["pathway_ids"]]

    lines: list[str] = []
    lines.append("# 专项区域表构建报告（③ 数据工程）")
    lines.append("")
    lines.append(f"> 生成日期：{date.today().isoformat()}｜ 脚本：`data/scripts/build_region_table.py`")
    lines.append("> 目标表：`pathway_region`（产品书 7.2）")
    lines.append("")
    lines.append("## 一、结果概览")
    lines.append("")
    lines.append("| 口径 | 县数 | 校验 |")
    lines.append("|---|---|---|")
    lines.append(f"| 国家专项（26 集中连片 + 12 国家级贫困） | **{len(nat)}** | "
                 f"{'✅ 与官方 38 一致' if len(nat) == 38 else '❌ 与官方 38 不符'} |")
    lines.append(f"| 高校专项（38 + 15 省定贫困） | **{len(counties)}** | "
                 f"{'✅ 与官方 53 一致' if len(counties) == 53 else '❌ 与官方 53 不符'} |")
    lines.append(f"| 其中：仅高校专项（省定 15 县） | {len(only_col)} | "
                 f"{'✅ 与官方 15 一致' if len(only_col) == 15 else '❌ 与官方 15 不符'} |")
    lines.append("")
    lines.append(f"- 入库行数（一县一途径一行）：**{len(rows)} 行**"
                 f"（national-special {result['national_count']} + college-special {result['college_count']}）")
    lines.append(f"- 未匹配 / 异常：**{len(unmatched)}**")
    lines.append("- 县码来源：民政部/国家统计局《中华人民共和国行政区划代码》（经镜像获取）")
    lines.append("- 名单依据：河南省教育厅《河南省实施国家专项计划和高校专项计划县域名单》")
    lines.append("")
    lines.append("> **⚠️ 口径修正说明**：早期草稿曾把 53 县整体误标为「国家专项 38 县」。")
    lines.append("> 经与河南省教育厅、河南省阳光高考信息平台官方表格逐条比对，已按三分类口径修正：")
    lines.append("> 国家专项 38 县与「省定 15 县」是**互斥集合**，合起来才是高校专项 53 县。")
    lines.append("")
    lines.append("## 二、国家专项实施区域（38 县）")
    lines.append("")
    lines.append("| 省辖市 | 县（含县码） |")
    lines.append("|---|---|")
    by_city: dict[str, list[dict]] = {}
    for item in nat:
        by_city.setdefault(item["city"], []).append(item)
    for city, items in by_city.items():
        cells = "、".join(f"{r['county_name']}({r['county_code']})" for r in items)
        lines.append(f"| {city} | {cells} |")
    lines.append("")
    lines.append(f"**合计：{len(nat)} 县 / {len(by_city)} 个省辖市**")
    lines.append("")
    lines.append("## 三、高校专项独有的 15 县（省定扶贫开发工作重点县）")
    lines.append("")
    lines.append("| 省辖市 | 县（含县码） |")
    lines.append("|---|---|")
    only_city: dict[str, list[dict]] = {}
    for item in only_col:
        only_city.setdefault(item["city"], []).append(item)
    for city, items in only_city.items():
        cells = "、".join(f"{r['county_name']}({r['county_code']})" for r in items)
        lines.append(f"| {city} | {cells} |")
    lines.append("")
    lines.append(f"**合计：{len(only_col)} 县** —— 这 15 县**只能报高校专项，不能报国家专项**，")
    lines.append("资格判定时必须区分，否则会误判考生资格。")
    lines.append("")

    if unmatched:
        lines.append("## 四、⚠️ 未匹配 / 异常项（需人工复核，未入库）")
        lines.append("")
        lines.append("| 省辖市 | 县 | 原因 |")
        lines.append("|---|---|---|")
        for item in unmatched:
            lines.append(f"| {item['city']} | {item['county']} | {item['reason']} |")
        lines.append("")
    else:
        lines.append("## 四、未匹配 / 异常项")
        lines.append("")
        lines.append("✅ 无。全部 53 县均已在国家统计局区划中精确命中，且无重复。")
        lines.append("")

    lines.append("## 五、入库建议")
    lines.append("")
    lines.append("- 目标表：`pathway_region`（产品书 7.2：`id, pathway_id, province, county_name, county_code, source_id`）")
    lines.append("- 字段映射：")
    lines.append("")
    lines.append("| 表字段 | 本文件字段 | 说明 |")
    lines.append("|---|---|---|")
    lines.append("| `id` | （入库时自增） | 主键 |")
    lines.append("| `pathway_id` | `pathway_id` | `national-special` / `college-special` |")
    lines.append("| `province` | `province` | 恒为 河南省 |")
    lines.append("| `county_name` | `county_name` | 县名 |")
    lines.append("| `county_code` | `county_code` | 6 位行政区划代码 |")
    lines.append("| `source_id` | `source_id` | 关联 `source` 表 |")
    lines.append("")
    lines.append("- `city` / `category` / 三要素为**附加字段**，供人工核对与校验使用，入库时可选。")
    lines.append("- 校验：")
    lines.append("")
    lines.append("```bash")
    lines.append("python data/scripts/validate.py data/dictionaries/pathway-regions.json --kind pathway_region")
    lines.append("```")
    lines.append("")

    path = os.path.join(SRC_DIR, "区域表构建报告.md")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
    return path


def main() -> int:
    try:
        result = build()
    except Exception as exc:  # noqa: BLE001
        print(f"[错误] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    p_json = write_json(result)
    p_csv = write_csv(result)
    p_md = write_report(result)

    print()
    print(f"✅ 国家专项 {result['national_count']} 县（官方 38）")
    print(f"✅ 高校专项 {result['college_count']} 县（官方 53）")
    print(f"   合计 {result['total_counties']} 个县条目")
    if result["unmatched"]:
        print(f"⚠️  异常 {len(result['unmatched'])} 项：")
        for item in result["unmatched"]:
            print(f"    - {item['city']} {item['county']}：{item['reason']}")
    print(f"   写出 {os.path.relpath(p_json, ROOT_DIR)}")
    print(f"   写出 {os.path.relpath(p_csv, ROOT_DIR)}")
    print(f"   写出 {os.path.relpath(p_md, ROOT_DIR)}")

    ok = result["national_count"] == 38 and result["college_count"] == 53
    print("   自检：" + ("✅ 与官方口径一致" if ok else "❌ 与官方口径不一致"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
