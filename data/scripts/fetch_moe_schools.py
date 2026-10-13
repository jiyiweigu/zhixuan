# -*- coding: utf-8 -*-
"""
教育部《全国普通高等学校名单》采集脚本（数据工程 ③ — 任务 2.1 配套）

数据来源
--------
中华人民共和国教育部 · 全国高等学校名单查询
  https://hudong.moe.gov.cn/qggxmd/
  接口：GET /school/wcmdata/getDataIndex.jsp?listid=10000101&page=<n>

为什么需要这个源
----------------
河南阳光高考的招生计划接口（fetch_schools.py）**不含** city / type / ownership /
website / intro，这几项在 `school` 表里是必填/期望字段。
教育部名单是**最权威**的高校基础信息源，含：
  - 学校名称          → name
  - 学校标识码（10位） → 与国标代码对照
  - 主管部门          → 可用于推断 ownership（公办/民办）
  - 所在地            → province + city
  - 层次（本科/专科）  → level

返回结构（HTML 表格，实测）
---------------------------
<tr><td>1</td><td>北京大学</td><td>4111010001</td>
    <td>教育部</td><td>北京市</td><td>本科</td><td></td></tr>

运行
----
    python data/scripts/fetch_moe_schools.py            # 抓取并输出
    python data/scripts/fetch_moe_schools.py --refresh  # 忽略缓存重抓

输出
----
- data/schools/.cache_moe/page_<n>.html   ← 原始 HTML 缓存
- data/schools/moe_schools.json           ← 教育部高校名单（结构化）
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import ssl
import sys
import time
import urllib.request
from typing import Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_DIR = os.path.dirname(BASE_DIR)
OUT_DIR = os.path.join(BASE_DIR, "schools")
CACHE_DIR = os.path.join(OUT_DIR, ".cache_moe")

LIST_ID = "10000101"          # 全国普通高等学校名单
API = f"https://hudong.moe.gov.cn/school/wcmdata/getDataIndex.jsp?listid={LIST_ID}"
REFERER = "https://hudong.moe.gov.cn/qggxmd/"

SOURCE_ID = "SRC-MOE-SCHOOL-LIST"
SOURCE_NAME = "中华人民共和国教育部（全国普通高等学校名单）"
SOURCE_URL = "https://hudong.moe.gov.cn/qggxmd/"

# 页面每页条数（实测）
PAGE_SIZE = 20
MAX_PAGE = 160                # 安全上限（实测末页 148）


def _ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _get(url: str, *, retries: int = 3) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Referer": REFERER,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    })
    last: Optional[Exception] = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30, context=_ssl_ctx()) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"抓取失败 {url}：{last}")


def parse_rows(page_html: str) -> List[List[str]]:
    """解析 HTML 表格，返回 [[序号, 校名, 标识码, 主管部门, 所在地, 层次, 备注], ...]"""
    out: List[List[str]] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page_html, re.S):
        cells = [
            html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
            for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        ]
        if len(cells) >= 6 and cells[0].isdigit():
            out.append(cells)
    return out


def crawl(*, refresh: bool = False) -> List[List[str]]:
    """抓取全部分页，缓存原始 HTML。"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    rows: List[List[str]] = []
    empty_streak = 0
    page = 1

    while page <= MAX_PAGE:
        cache = os.path.join(CACHE_DIR, f"page_{page}.html")
        if os.path.exists(cache) and not refresh:
            with open(cache, encoding="utf-8") as fh:
                doc = fh.read()
        else:
            doc = _get(f"{API}&page={page}")
            with open(cache, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(doc)
            time.sleep(0.2)

        batch = parse_rows(doc)
        if not batch:
            empty_streak += 1
            if empty_streak >= 1:
                break
        else:
            empty_streak = 0
            rows.extend(batch)
        if page % 20 == 0:
            print(f"  page {page:>3}: 累计 {len(rows)}")
        page += 1

    return rows


def split_location(loc: str) -> "tuple[str, str]":
    """
    所在地 → (省, 市)。

    教育部名单给出的所在地有两种形态（实测）：
      1) 带省前缀：河北省石家庄市 / 内蒙古自治区呼和浩特市 / 广东省广州市
      2) 仅市名：  北京市 / 保定市 / 石家庄市 / 呼和浩特市
    直辖市（北京/上海/天津/重庆）单列，省=市。

    ⚠️ 不能把「市」当省级后缀，否则「保定市」会被误当省名。
       省级后缀只认：省 / 自治区 / 特别行政区。
    """
    if not loc:
        return "", ""

    # 1) 直辖市
    for muni in ("北京市", "上海市", "天津市", "重庆市"):
        if loc == muni:
            return muni[:-1], muni[:-1]

    # 2) 带省级前缀
    for suf in ("维吾尔自治区", "回族自治区", "壮族自治区", "自治区",
                "特别行政区", "省"):
        idx = loc.find(suf)
        if idx != -1:
            prov = loc[: idx + len(suf)]
            rest = loc[idx + len(suf):]
            prov_clean = (prov.replace("维吾尔自治区", "")
                              .replace("回族自治区", "")
                              .replace("壮族自治区", "")
                              .replace("自治区", "")
                              .replace("特别行政区", "")
                              .replace("省", ""))
            return prov_clean, rest

    # 3) 仅市名（如「保定市」）→ 省市同名，省由调用方按需回填
    return "", loc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"[采集] {SOURCE_NAME}")
    rows = crawl(refresh=args.refresh)
    print(f"[采集] 共 {len(rows)} 所高校")

    records = []
    for cells in rows:
        no, name, code10, dept, loc, level = (cells + [""] * 7)[:6]
        prov, city = split_location(loc)
        records.append({
            "seq": int(no),
            "name": name,
            "code10": code10,          # 教育部 10 位标识码
            # ★ 10 位标识码的**后 5 位**即国标院校代码
            #   例：北京大学 4111010001 → 10001（与河南招生计划接口一致）
            "national_code": code10[-5:] if len(code10) >= 5 else "",
            "department": dept,         # 主管部门
            "location": loc,            # 原始所在地
            "province": prov,
            "city": city,
            "level": level,             # 本科 / 专科
        })

    # ── 自举：用「带省前缀」的记录建立 市 → 省 映射，回填「仅市名」的记录 ──
    city2prov: Dict[str, str] = {}
    for r in records:
        if r["province"] and r["city"]:
            city2prov.setdefault(r["city"], r["province"])
    backfilled = 0
    for r in records:
        if not r["province"] and r["city"] and r["city"] in city2prov:
            r["province"] = city2prov[r["city"]]
            backfilled += 1
    print(f"   省市自举：{len(city2prov)} 个市 → 省，回填 {backfilled} 条")

    payload = {
        "meta": {
            "source_id": SOURCE_ID,
            "source_name": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "total": len(records),
            "note": ("教育部《全国普通高等学校名单》全量，"
                     "用于补全 school 表的 province/city/level 及反向校验 code"),
        },
        "records": records,
    }
    jp = os.path.join(OUT_DIR, "moe_schools.json")
    with open(jp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    benke = sum(1 for r in records if r["level"] == "本科")
    print(f"✅ 本科 {benke} / 专科 {len(records) - benke}")
    print(f"   → {os.path.relpath(jp, ROOT_DIR)}")
    print("   抽查前 3 条：")
    for r in records[:3]:
        print(f"     [{r['national_code']}] {r['name']} · {r['province']}/{r['city']}"
              f" · {r['level']} · 主管:{r['department']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
