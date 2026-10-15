# -*- coding: utf-8 -*-
"""
Gaokao-Compass-11M 选科要求原始数据取数脚本
==========================================
数据源（三要素，见 data/sources/source-table.json 的 SRC-GAOKAO-COMPASS）：
  name : Gaokao-Compass-11M 高考数据集（MIT，DOI 10.57967/hf/9882）
  url  : https://hf-mirror.com/datasets/choucsan/Gaokao-Compass-11M   （国内镜像）
  year : 2017–2025（本脚本只取 2022–2025）

许可：MIT，可再分发；作品内事实结论的 source_url 须指向省考试院/阳光高考，
      本数据集仅作为获取渠道（与既有 score_segment / school_major_score 同口径）。

仓库布局约定（与 parse_subject_req.py --scan 的 glob 对齐）：
  data/raw/<prov>_<year>_enrollment-plan.csv
  data/raw/<prov>_<year>_school-admission.csv
  data/raw/<prov>_<year>_major-admission.csv
上游仓库内布局：data/<year>/<province>/<kind>.csv（kind ∈ enrollment-plan /
  school-admission / major-admission / score-range / meta.json）。
  本脚本默认只取 enrollment-plan（subject_req 字段只存在于招生计划表，
  录取分表无该字段，取回只会制造海量 missing 噪声）。

⚠️ data/raw/ 属于数据本体，不入公开仓库（.gitignore: data/raw/*）。

特性：幂等 + 断点续传（HTTP Range 续传 .part 文件），已完整文件直接跳过。

用法：
  python fetch_gaokao_compass.py                 # 河南+江西 2022–2025 enrollment-plan
  python fetch_gaokao_compass.py --kinds enrollment-plan school-admission
  python fetch_gaokao_compass.py --list          # 只列出远端待取文件与大小
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # data/
RAW_DIR = BASE_DIR / "raw"

# ---- 渠道与许可（来源登记三要素）---------------------------------------
SOURCE_ID = "SRC-GAOKAO-COMPASS"
SOURCE_NAME = "Gaokao-Compass-11M 高考数据集（MIT，DOI 10.57967/hf/9882）"
SOURCE_URL = "https://hf-mirror.com/datasets/choucsan/Gaokao-Compass-11M"
LICENSE = "MIT"

REPO = "choucsan/Gaokao-Compass-11M"
MIRROR = "https://hf-mirror.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# ---- 取数范围（试点省份：河南第一 + 江西第二）---------------------------
PROVINCES = ["henan", "jiangxi"]
YEARS = [2022, 2023, 2024, 2025]
KINDS = ["enrollment-plan"]        # subject_req 只在招生计划表
ALL_KINDS = ["enrollment-plan", "school-admission", "major-admission"]

CHUNK = 1 << 16                    # 64 KiB


def _open(url: str, extra: dict | None = None) -> urllib.request.urlopen:
    # 本机环境常残留 http_proxy 环境变量且代理不稳，hf-mirror 国内直连更快；
    # 逐请求剥离代理（不改进程全局，便于他人带代理复用其他脚本）。
    headers = {"User-Agent": UA}
    if extra:
        headers.update(extra)
    req = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(req, timeout=60)


def remote_size(prov: str, year: int, kind: str) -> int | None:
    url = f"{MIRROR}/api/datasets/{REPO}/tree/main/data/{year}/{prov}"
    try:
        with _open(url) as resp:
            import json
            entries = json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 列目录失败 {url}: {e}")
        return None
    for e in entries:
        if e.get("path") == f"data/{year}/{prov}/{kind}.csv":
            return int(e.get("size") or 0)
    return None


def download(prov: str, year: int, kind: str) -> str:
    """下载单个文件（幂等 + Range 断点续传）。返回 skipped|done|failed。"""
    out = RAW_DIR / f"{prov}_{year}_{kind}.csv"
    part = out.with_suffix(".csv.part")
    url = f"{MIRROR}/datasets/{REPO}/resolve/main/data/{year}/{prov}/{kind}.csv"

    if out.exists() and out.stat().st_size > 0:
        return "skipped"

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    expect = remote_size(prov, year, kind)

    for attempt in range(3):
        try:
            have = part.stat().st_size if part.exists() else 0
            extra = {"Range": f"bytes={have}-"} if have else None
            with _open(url, extra) as resp:
                total = int(resp.headers.get("Content-Length") or 0) + have
                if expect and total and total != expect:
                    # 服务器不支持 Range（200 全量）时 have 应为 0
                    if have and resp.status == 200:
                        have = 0
                        total = expect
                mode = "ab" if (have and resp.status == 206) else "wb"
                with part.open(mode) as f:
                    while True:
                        chunk = resp.read(CHUNK)
                        if not chunk:
                            break
                        f.write(chunk)
            if expect and part.stat().st_size != expect:
                raise RuntimeError(
                    f"体积不符：本地 {part.stat().st_size} != 远端 {expect}")
            part.replace(out)
            return "done"
        except Exception as e:  # noqa: BLE001
            print(f"[retry {attempt + 1}/3] {out.name}: {e}")
            time.sleep(2 * (attempt + 1))
    return "failed"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kinds", nargs="*", default=KINDS, choices=ALL_KINDS)
    ap.add_argument("--list", action="store_true", help="只列出远端文件与大小")
    args = ap.parse_args()

    os.environ.pop("http_proxy", None)
    os.environ.pop("https_proxy", None)

    targets = [(p, y, k) for p in PROVINCES for y in YEARS for k in args.kinds]
    print(f"[plan] {SOURCE_ID} · {MIRROR}")
    print(f"[plan] {'+'.join(PROVINCES)} × {YEARS} × {args.kinds}，共 {len(targets)} 个文件\n")

    if args.list:
        for p, y, k in targets:
            size = remote_size(p, y, k)
            print(f"  {p}_{y}_{k}.csv  {'' if size is None else f'{size/1e6:.1f} MB'}")
        return 0

    rc = 0
    for p, y, k in targets:
        r = download(p, y, k)
        out = RAW_DIR / f"{p}_{y}_{k}.csv"
        mark = {"skipped": "·已存在", "done": "✓", "failed": "✗失败"}[r]
        print(f"  {mark:<6} {out.name}  {out.stat().st_size/1e6:.1f} MB" if out.exists()
              else f"  ✗失败  {p}_{y}_{k}.csv")
        if r == "failed":
            rc = 1
    print(f"\n[done] 输出目录 {RAW_DIR}（不入库）")
    return rc


if __name__ == "__main__":
    sys.exit(main())
