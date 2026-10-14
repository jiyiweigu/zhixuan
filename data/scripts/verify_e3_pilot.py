# -*- coding: utf-8 -*-
"""
E3 · L2 试点核实 —— 一分一段「第二通道」交叉验证
================================================

背景（对应 E3 = L2 试点核实，产品书「拿奖」判定点）
====================================================
我方一分一段（2022–2025 河南/江西）来源为 `SRC-GAOKAO-COMPASS`（Gaokao-Compass-11M
渠道数据集），**记录级 `source_url` 全空**。成员张的分支另行采集了同一批数据，
来源标注「中国教育在线·掌上高考（转载省考试院）」且**带可访问 URL**。

两条采集路径**互相独立**。若逐条数值一致，即为渠道数据可信度的**外部佐证**——
这正是 E3 证据链要的东西。本脚本负责**机械复核**，不做任何写入。

复核对象
========
张分支产物（须先导出到仓库外，见下）：
  - 河南 2023 / 2024 / 2025  →  <zhang>/data/output/score_segment.json
  - 江西 2024                →  <zhang>/data/jiangxi/output/score_segment.json

导出命令（不污染仓库）：
  git archive origin/feature/zhang data/output data/jiangxi/output \\
    | tar -x -C "C:/Users/lenovo/.pg16/zhang_data"

用法
====
  python data/scripts/verify_e3_pilot.py
  python data/scripts/verify_e3_pilot.py --zhang "C:/Users/lenovo/.pg16/zhang_data"
  python data/scripts/verify_e3_pilot.py --json out.json     # 结果落 JSON
  python data/scripts/verify_e3_pilot.py --strict             # 有差异则退出码 1

比对键：(科类, 分数)   —— 分数唯一，`batch` 由分数区间决定（不参与键）
比对值：`cumulative_rank`（累计人数 = 位次）

退出码：0 = 全部一致；1 = 存在差异（仅 --strict 时）
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OURS_DIR = ROOT / "data" / "score_segment"
DEFAULT_ZHANG = Path("C:/Users/lenovo/.pg16/zhang_data")

# (我方文件名, 张内相对路径, 省, 年)
PAIRS = [
    ("score_segment_2023_河南.json", "data/output/score_segment.json", "河南", 2023),
    ("score_segment_2024_河南.json", "data/output/score_segment.json", "河南", 2024),
    ("score_segment_2025_河南.json", "data/output/score_segment.json", "河南", 2025),
    ("score_segment_2024_江西.json", "data/jiangxi/output/score_segment.json", "江西", 2024),
]


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _index_ours(recs: list[dict]) -> tuple[dict, list]:
    """我方 → {(科类,分数): 累计人数}，并返回键冲突明细。"""
    idx: dict[tuple, int] = {}
    dup: list = []
    for r in recs:
        k = (r.get("subject_type"), r.get("score"))
        v = r.get("cumulative_rank")
        if k in idx and idx[k] != v:
            dup.append({"key": k, "old": idx[k], "new": v})
        idx[k] = v
    return idx, dup


def _index_zhang(recs: list[dict], province: str, year: int):
    """张 → {(科类,分数): 累计人数} + {(科类): url}。"""
    idx: dict[tuple, int] = {}
    urls: dict[str, str] = {}
    for r in recs:
        if r.get("province") != province or r.get("year") != year:
            continue
        k = (r.get("subject_type"), r.get("score"))
        idx[k] = r.get("cumulative_rank")
        urls.setdefault(r.get("subject_type"), r.get("source_url"))
    return idx, urls


def main() -> int:
    ap = argparse.ArgumentParser(description="E3 一分一段第二通道交叉验证")
    ap.add_argument("--zhang", default=str(DEFAULT_ZHANG), help="张分支导出根目录")
    ap.add_argument("--json", help="结果写入指定 JSON 路径")
    ap.add_argument("--strict", action="store_true", help="有差异时返回退出码 1")
    args = ap.parse_args()

    zroot = Path(args.zhang)
    print("=" * 78)
    print("E3 · L2 试点核实 —— 一分一段交叉验证（我方 vs 张，第二通道）")
    print("=" * 78)

    zcache: dict[Path, object] = {}
    report = {"pairs": [], "url_map": [], "total_ok": 0, "total_diff": 0,
              "total_ours_only": 0, "total_zhang_only": 0}
    any_bad = False

    for our_name, zrel, prov, year in PAIRS:
        our_p = OURS_DIR / our_name
        z_p = zroot / zrel
        if not our_p.exists():
            print(f"❌ 缺我方文件：{our_p}")
            any_bad = True
            continue
        if not z_p.exists():
            print(f"❌ 缺张分支文件：{z_p}（先 git archive 导出）")
            any_bad = True
            continue

        if z_p not in zcache:
            zcache[z_p] = _load(z_p)
        z_all = zcache[z_p]

        our_recs = _load(our_p).get("segments", [])
        o_idx, o_dup = _index_ours(our_recs)
        z_idx, z_urls = _index_zhang(z_all, prov, year)

        common = set(o_idx) & set(z_idx)
        only_o = set(o_idx) - set(z_idx)
        only_z = set(z_idx) - set(o_idx)
        diff = [k for k in common if o_idx[k] != z_idx[k]]

        rep = {
            "province": prov, "year": year, "our_file": our_name,
            "ours": len(o_idx), "zhang": len(z_idx), "common": len(common),
            "consistent": len(common) - len(diff), "mismatch": len(diff),
            "ours_only": len(only_o), "zhang_only": len(only_z),
            "key_dup_in_ours": o_dup,
            "mismatch_detail": [{"key": k, "ours": o_idx[k], "zhang": z_idx[k]}
                                for k in sorted(diff)][:50],
            "ours_only_detail": sorted(only_o)[:50],
            "zhang_only_detail": sorted(only_z)[:50],
            "urls": z_urls,
        }
        report["pairs"].append(rep)
        report["total_ok"] += rep["consistent"]
        report["total_diff"] += rep["mismatch"]
        report["total_ours_only"] += rep["ours_only"]
        report["total_zhang_only"] += rep["zhang_only"]

        print(f"\n▌ {prov} {year}  我方 {len(o_idx)} 条 ｜ 张 {len(z_idx)} 条")
        print(f"   一致 {rep['consistent']} ｜ 不一致 {rep['mismatch']} ｜ "
              f"仅我方 {rep['ours_only']} ｜ 仅张 {rep['zhang_only']}")
        for subj, url in sorted(z_urls.items()):
            print(f"   URL[{subj}] = {url}")
            report["url_map"].append({"province": prov, "year": year,
                                      "subject_type": subj, "source_url": url})
        if diff:
            any_bad = True
            for k, o, z in [(k, o_idx[k], z_idx[k]) for k in sorted(diff)][:20]:
                print(f"   ⚠ 不一致 {k}: 我方={o} 张={z}")
        if only_z:
            for k in sorted(only_z)[:20]:
                print(f"   ➕ 仅张有 {k}: 位次={z_idx[k]}   ← 待回源核")
        if only_o:
            for k in sorted(only_o)[:20]:
                print(f"   ➖ 仅我方有 {k}: 位次={o_idx[k]}")
        if o_dup:
            print(f"   ⚠ 我方键冲突 {len(o_dup)} 处")

    print("\n" + "=" * 78)
    print(f"合计：一致 {report['total_ok']} ｜ 不一致 {report['total_diff']} ｜ "
          f"仅我方 {report['total_ours_only']} ｜ 仅张 {report['total_zhang_only']}")
    print("=" * 78)

    if args.json:
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"结果已写入：{args.json}")

    if args.strict and any_bad:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
