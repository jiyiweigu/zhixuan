# -*- coding: utf-8 -*-
"""
软科中国大学排名（ShanghaiRanking · BCUR 主榜）采集脚本
=====================================================
数据源：https://www.shanghairanking.cn/api/pub/v1/bcur
  - bcur_type=11  主榜（综合性大学榜）
  - year=2024     最新已发布年份
  - 直连 HTTP 200，无 WAF，JSON 接口

用途：为院校库补充「软科排名」字段 + 交叉核对 level（双一流/985/211）。

产出：
  data/schools/shanghairanking_2024.json   全量 594 条
  data/schools/shanghai_top300.json        排名前 300（含边界并列处理）
  data/schools/shanghai_top300.csv         同上前 300 的扁平表

⚠️ 口径声明：软科排名是**第三方机构排名**，非官方数据。
   在本项目中仅作为「参考位次/层次校验」辅助，**不得替代官方来源**。
   source_name = 上海软科教育信息咨询有限公司
   source_url  = https://www.shanghairanking.cn/rankings/bcur/2024
   year        = 2024

用法：
  python fetch_shanghairanking.py                # 全量抓取 + 生成 top300
  python fetch_shanghairanking.py --top 300      # 自定义 top 边界
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

import urllib.request
import urllib.error

BASE_DIR = Path(__file__).resolve().parent.parent          # data/
OUT_DIR = BASE_DIR / "schools"
CACHE_DIR = OUT_DIR / ".cache_srk"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

API = "https://www.shanghairanking.cn/api/pub/v1/bcur"
BCUR_TYPE = 11          # 主榜
YEAR = 2024

SOURCE_NAME = "上海软科教育信息咨询有限公司"
SOURCE_URL = "https://www.shanghairanking.cn/rankings/bcur/2024"
SOURCE_ID = "SRC-SHANGHAIRANKING"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.shanghairanking.cn/rankings/bcur/2024",
}


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    ctx = None
    # 本机走 localhost/代理环境，软科公网直连；若需代理可在此扩展
    with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status} for {url}")
        return resp.read()


def fetch_raw() -> dict:
    """抓取软科主榜 JSON（带本地缓存）。"""
    cache = CACHE_DIR / f"bcur_{BCUR_TYPE}_{YEAR}.json"
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except Exception:
            pass
    url = f"{API}?bcur_type={BCUR_TYPE}&year={YEAR}"
    print(f"[fetch] {url}")
    raw = _get(url)
    cache.write_bytes(raw)
    time.sleep(0.5)
    return json.loads(raw.decode("utf-8"))


def normalize(payload: dict) -> list[dict]:
    if payload.get("code") != 200:
        raise RuntimeError(f"接口返回异常: code={payload.get('code')} msg={payload.get('msg')}")
    rankings = payload.get("data", {}).get("rankings", [])
    out = []
    for r in rankings:
        # 接口返回的 ranking / rankOverall 是字符串，需转 int 便于排序与边界判断
        def _int(v):
            if v is None:
                return None
            try:
                return int(str(v).strip())
            except ValueError:
                return None
        out.append({
            "ranking":       _int(r.get("ranking")),
            "rankOverall":   _int(r.get("rankOverall")),
            "name":          (r.get("univNameCn") or "").strip(),
            "name_en":       (r.get("univNameEn") or "").strip(),
            "province":      (r.get("province") or "").strip(),
            "category":      (r.get("univCategory") or "").strip(),
            "score":         r.get("score"),
            "tags":          r.get("univTags") or [],
            "remark":        (r.get("univNameRemark") or "").strip(),
            "rank_change":   r.get("rankChange"),
            "source_name":   SOURCE_NAME,
            "source_url":    SOURCE_URL,
            "year":          YEAR,
            "source_id":     SOURCE_ID,
        })
    # 按排名排序（无排名放最后）
    out.sort(key=lambda x: (x["ranking"] is None, x["ranking"] or 99999))
    return out


def build_top(records: list[dict], top_n: int) -> list[dict]:
    """取前 top_n 名，并处理边界并列。

    软科排名存在并列（同一 ranking 值多条），因此「前 300」若边界并列，
    应把同一 ranking 的全部纳入，避免人为截断。返回结果含 boundary_note。
    """
    ranked = [r for r in records if isinstance(r["ranking"], int)]
    # 找边界名次
    boundary = None
    picked = []
    for r in ranked:
        if r["ranking"] <= top_n:
            picked.append(r)
        else:
            boundary = r["ranking"]
            break
    # 边界并列：ranking == top_n 的可能有多条，上面已全部纳入（因 <= top_n）
    # 但若 top_n 正好切在并列中间（例如 300 名有 2 条），也已全部纳入
    note = ""
    same = [r for r in ranked if r["ranking"] == top_n]
    if len(same) > 1:
        note = f"第 {top_n} 名存在 {len(same)} 所并列，已全部纳入"
    for r in picked:
        r["in_top"] = top_n
        r["boundary_note"] = note
    return picked


def write_outputs(records: list[dict], top_n: int) -> None:
    # 全量
    full = OUT_DIR / "shanghairanking_2024.json"
    full.write_text(json.dumps({
        "meta": {
            "source_name": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "year": YEAR,
            "bcur_type": BCUR_TYPE,
            "count": len(records),
            "note": "第三方机构排名，非官方数据，仅作参考位次/层次校验用途",
        },
        "rankings": records,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[out] {full}  ({len(records)} 条)")

    # top N
    top = build_top(records, top_n)
    topf = OUT_DIR / f"shanghai_top{top_n}.json"
    topf.write_text(json.dumps({
        "meta": {
            "source_name": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "year": YEAR,
            "top_n": top_n,
            "count": len(top),
            "boundary_note": top[0]["boundary_note"] if top else "",
        },
        "rankings": top,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[out] {topf}  ({len(top)} 条)")

    # CSV
    csvf = OUT_DIR / f"shanghai_top{top_n}.csv"
    with csvf.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ranking", "name", "province", "category", "score",
                    "tags", "source_name", "source_url", "year"])
        for r in top:
            w.writerow([r["ranking"], r["name"], r["province"], r["category"],
                        r["score"], "|".join(r["tags"]),
                        r["source_name"], r["source_url"], r["year"]])
    print(f"[out] {csvf}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=300)
    args = ap.parse_args()

    payload = fetch_raw()
    records = normalize(payload)
    print(f"[info] 软科主榜 {YEAR} 共 {len(records)} 条")
    if records:
        print(f"       第1名: {records[0]['name']} (score={records[0]['score']})")
        tail = [r for r in records if r['ranking'] == args.top]
        print(f"       第{args.top}名: " +
              ", ".join(f"{r['name']}({r['score']})" for r in tail))
    write_outputs(records, args.top)
    return 0


if __name__ == "__main__":
    sys.exit(main())
