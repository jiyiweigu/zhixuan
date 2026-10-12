# -*- coding: utf-8 -*-
"""
河南省在豫招生院校库采集脚本（数据工程 ③ — 任务 2.1）

数据来源
--------
河南省阳光高考信息平台 · 招生计划查询系统
  https://zsjh.haedu.cn/qwerasd/school        （院校列表页）
  https://zsjh.haedu.cn/qwerasd/dyna-school   （★ 真实 AJAX 分页接口）

为什么用这个源
--------------
- `haeea.cn`（河南省教育考试院）、`heao.com.cn`（河南招生考试信息网）、
  `gaokao.chsi.com.cn`（教育部阳光高考）均为 **412 瑞数 JS 挑战 WAF**，纯 HTTP 过不了。
- `zsjh.haedu.cn` 是**传统 ASP.NET WebForms + JSON AJAX** 架构，**无 WAF**，
  纯 HTTP GET 即可拿到结构化 JSON ⇒ **无需 Playwright，零新增依赖**。

接口返回字段（实测）
--------------------
{
  "YEAR": 2026,
  "YXSF": "11",                 # 院校省份代码（国标2位，11=北京）
  "PCDH": "1", "PCMC": "普通本科批",   # 批次代码 / 批次名称
  "KLDH": "1", "KLMC": "历史类",       # 科类代码 / 科类名称
  "YXDH": "0001",               # 院校代号（河南本地4位）
  "YXMC": "北京体育大学",         # 院校名称
  "JHZS": "12",                 # 计划招生数
  "school_national_code": "10043",   # ★ 教育部国标院校代码（5位）
  "JHRS": 66
}

本脚本做什么
------------
1. 遍历 dyna-school 全部分页（约 84 页），抓取在豫招生的**全部**院校记录
2. 按院校名去重（同一校在多批次/科类下会重复出现）
3. 过滤出**本科**批次（任务 2.1 要求"约 300 所本科院校"）
4. 映射省份代码 → 省名
5. 输出 school 表所需的字段（见 data/dictionaries/fields-definition.md 4.5）

字段现状（诚实说明）
--------------------
- `id` / `name` / `code` / `province`  ← 本接口**直接可得**
- `city` / `level` / `type` / `ownership` / `website` / `intro`
  ← 本接口**不含**，需后续从「各校官网」或「教育部全国高校名单」补采。
    这些字段在输出中标记为 `pending`，**不得编造**。

运行
----
    python data/scripts/fetch_schools.py                 # 抓取并输出
    python data/scripts/fetch_schools.py --refresh       # 忽略缓存重抓
    python data/scripts/fetch_schools.py --all           # 含专科（默认仅本科）

输出
----
- data/schools/schools_raw.json      ← 原始全量（含批次/科类，供 school_major_score 复用）
- data/schools/schools.json          ← 清洗后的 school 表数据
- data/schools/schools.csv           ← 人工核对版
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_DIR = os.path.dirname(BASE_DIR)
OUT_DIR = os.path.join(BASE_DIR, "schools")
CACHE_DIR = os.path.join(OUT_DIR, ".cache")

API = "https://zsjh.haedu.cn/qwerasd/dyna-school"
REFERER = "https://zsjh.haedu.cn/qwerasd/school"

SOURCE_ID = "SRC-HENAN-ZSJH"
SOURCE_NAME = "河南省阳光高考信息平台（招生计划查询系统）"
SOURCE_URL = "https://zsjh.haedu.cn/qwerasd/school"

# ── 国标省份代码（前2位）→ 省名 ──────────────────────────────
PROVINCE_BY_CODE: Dict[str, str] = {
    "11": "北京", "12": "天津", "13": "河北", "14": "山西", "15": "内蒙古",
    "21": "辽宁", "22": "吉林", "23": "黑龙江",
    "31": "上海", "32": "江苏", "33": "浙江", "34": "安徽", "35": "福建",
    "36": "江西", "37": "山东",
    "41": "河南", "42": "湖北", "43": "湖南", "44": "广东", "45": "广西",
    "46": "海南",
    "50": "重庆", "51": "四川", "52": "贵州", "53": "云南", "54": "西藏",
    "61": "陕西", "62": "甘肃", "63": "青海", "64": "宁夏", "65": "新疆",
    # 港澳台（在豫招生的港校国标代码以 81 开头）
    "81": "中国香港", "82": "中国澳门", "71": "中国台湾",
}

# ── 国标院校代码前缀 → 省份（代码缺失时兜底推断，仅对港澳台）──
NATCODE_PREFIX_PROVINCE = {"81": "中国香港", "82": "中国澳门", "71": "中国台湾"}

# ── 本科批次判定（任务 2.1 只要本科）────────────────────────
BENKE_KEYWORDS = ("本科",)
ZHUANKE_KEYWORDS = ("高职", "专科")

# school 表字段顺序（见 fields-definition.md 4.5）
CSV_FIELDS = ["id", "name", "code", "province", "city",
              "level", "type", "ownership", "website", "intro",
              "source_id", "source_name", "source_url", "year", "data_status"]


def _ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def fetch_page(page: int, *, retries: int = 3) -> List[dict]:
    """抓取一页；失败重试。返回 Datas 数组。"""
    url = f"{API}?page={page}"
    req = urllib.request.Request(url, headers={
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "X-Requested-With": "XMLHttpRequest",
        "Referer": REFERER,
        "Accept": "application/json, text/javascript, */*; q=0.01",
    })
    last: Optional[Exception] = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30, context=_ssl_ctx()) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            # 接口可能返回 {StatusCode,Result,Datas:[...]} 包壳，也可能直接是数组
            if isinstance(data, dict):
                return data.get("Datas") or []
            if isinstance(data, list):
                return data
            raise ValueError(f"未识别的返回结构：{type(data).__name__}")
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"page {page} 抓取失败：{last}")


def crawl_all(*, refresh: bool = False) -> List[dict]:
    """
    抓取全部分页。缓存到 .cache/page_<n>.json，避免重复请求。
    探测末页：连续 2 页为空即停止。
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    rows: List[dict] = []
    page = 0
    empty_streak = 0

    while True:
        cache = os.path.join(CACHE_DIR, f"page_{page}.json")
        if os.path.exists(cache) and not refresh:
            with open(cache, encoding="utf-8") as fh:
                batch = json.load(fh)
        else:
            batch = fetch_page(page)
            with open(cache, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(batch, fh, ensure_ascii=False)
            time.sleep(0.25)   # 温和限速，避免给对方服务器压力

        if not batch:
            empty_streak += 1
            if empty_streak >= 2:
                break
        else:
            empty_streak = 0
            rows.extend(batch)
        print(f"  page {page:>3}: {len(batch):>3} 条（累计 {len(rows)}）")
        page += 1
        if page > 200:          # 安全阀
            break

    return rows


def is_benke(pcmc: str) -> bool:
    """批次名含'本科'且不含'高职/专科' → 本科批次"""
    if not pcmc:
        return False
    if any(k in pcmc for k in ZHUANKE_KEYWORDS):
        return False
    return any(k in pcmc for k in BENKE_KEYWORDS)


def build_school_table(rows: List[dict], *, benke_only: bool = True):
    """
    去重 + 清洗，产出 school 表记录。

    去重键：院校名（同一院校在不同批次/科类重复出现）。
    省份：取该院校任一条的 YXSF 映射。
    批次信息另存 schools_raw.json，供 school_major_score 复用。
    """
    # 2) 按院校名去重（同一校在多批次/科类下会重复出现）
    merged: Dict[str, dict] = {}
    skipped_zk = 0

    for r in rows:
        if not isinstance(r, dict):     # 防御：过滤非对象元素
            continue
        name = (r.get("YXMC") or "").strip()
        if not name:
            continue
        if benke_only and not is_benke(r.get("PCMC", "")):
            skipped_zk += 1
            continue
        if name in merged:
            continue
        merged[name] = r

    out: List[dict] = []
    for idx, (name, r) in enumerate(sorted(merged.items(),
                                          key=lambda kv: kv[1].get("YXDH", "")), start=1):
        yxsf = str(r.get("YXSF") or "")
        nat = str(r.get("school_national_code") or "").strip()
        # 省份：优先 YXSF；缺失时用国标代码前缀兜底（港澳台）
        province = PROVINCE_BY_CODE.get(yxsf, "")
        if not province and nat[:2] in NATCODE_PREFIX_PROVINCE:
            province = NATCODE_PREFIX_PROVINCE[nat[:2]]
        out.append({
            "id": idx,
            "name": name,
            "code": nat,                       # 教育部国标 5 位代码
            "province": province,
            "city": "",                        # 本接口不含
            "level": "本科",                    # 本批筛选即本科
            "type": "",                        # 本接口不含
            "ownership": "",                   # 本接口不含
            "website": "",                     # 本接口不含
            "intro": "",                       # 本接口不含
            # 附加溯源（供核对，非 school 表字段）
            "_henan_code": r.get("YXDH", ""),
            "_province_code": yxsf,
            # 溯源三要素
            "source_id": SOURCE_ID,
            "source_name": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "year": r.get("YEAR", 2026),
            "data_status": "pending",          # city/type/ownership 待补
        })

    return out, skipped_zk, len(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="忽略缓存重抓")
    ap.add_argument("--all", action="store_true",
                    help="含专科（默认仅本科）")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)

    print(f"[采集] {SOURCE_NAME}")
    rows = crawl_all(refresh=args.refresh)
    print(f"[采集] 原始记录 {len(rows)} 条")

    schools, skipped_zk, total = build_school_table(
        rows, benke_only=not args.all)

    # 原始全量（供 school_major_score 复用批次/科类）
    raw_out = {
        "meta": {
            "source_id": SOURCE_ID,
            "source_name": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "year": 2026,
            "note": "招生计划查询系统原始返回（含批次/科类维度），供录取分等下游复用",
            "total_raw": total,
        },
        "records": rows,
    }
    with open(os.path.join(OUT_DIR, "schools_raw.json"), "w",
              encoding="utf-8", newline="\n") as fh:
        json.dump(raw_out, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    # school 表数据
    prov_stats: Dict[str, int] = {}
    for s in schools:
        prov_stats[s["province"]] = prov_stats.get(s["province"], 0) + 1

    payload = {
        "meta": {
            "target_table": "school",
            "source_id": SOURCE_ID,
            "source_name": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "year": 2026,
            "benke_only": not args.all,
            "school_count": len(schools),
            "skipped_zhuanke_rows": skipped_zk,
            "province_stats": dict(sorted(prov_stats.items(),
                                          key=lambda kv: -kv[1])),
            "field_status": {
                "direct": ["id", "name", "code", "province", "level"],
                "pending": ["city", "type", "ownership", "website", "intro"],
                "note": ("city/type/ownership/website/intro 本接口不含，"
                         "待从各校官网或教育部名单补采；严禁编造"),
            },
        },
        "records": schools,
    }
    jp = os.path.join(OUT_DIR, "schools.json")
    with open(jp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    cp = os.path.join(OUT_DIR, "schools.csv")
    with open(cp, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS + ["_henan_code", "_province_code"])
        w.writeheader()
        for s in schools:
            w.writerow({k: s.get(k, "") for k in CSV_FIELDS + ["_henan_code", "_province_code"]})

    print()
    print(f"✅ 本科院校 {len(schools)} 所（跳过专科行 {skipped_zk}）")
    print(f"   省份分布（前 10）：")
    for p, c in list(zip(prov_stats.keys(),
                         prov_stats.values()))[:10]:
        print(f"     {p or '未知'}: {c}")
    print(f"   → {os.path.relpath(jp, ROOT_DIR)}")
    print(f"   → {os.path.relpath(cp, ROOT_DIR)}")
    print(f"   → {os.path.relpath(os.path.join(OUT_DIR, 'schools_raw.json'), ROOT_DIR)}")

    # 抽查
    print()
    print("   抽查前 5 条：")
    for s in schools[:5]:
        print(f"     [{s['code']}] {s['name']} · {s['province']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
