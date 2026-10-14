#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一分一段表导入脚本（score_segment 表）

数据来源：Gaokao-Compass-11M 数据集的 score-range.csv
目标表：`score_segment`（产品书第 7 章）
字段映射（第 7 章：province, year, subject_type, score, cumulative_rank, ...）：
    数据集字段            目标字段            说明
    province              province            直取
    year                  year                转 int
    category              subject_type        ★ 口径断裂：河南 2024 及以前为「理科/文科」，
                                                  2025 起为「物理类/历史类」；江西 2024 起即为新高考
    batch                 batch               ★ 必须保留！老高考曲线被批次线切成多段
                                                  （本科一批/本科二批/专科批），合并会丢批次线
    score                 score               直取（可能带 .0）
    cumulative_count      cumulative_rank     ★ 官方口径 = 该分数及以上累计人数，即位次
    control_score         control_score       批次控制线
    segment_count         segment_count       本分数段人数
    rank_range            rank_range          位次区间字符串
    score_range           score_range         分数区间字符串

关键口径（红线）：
  1. **不得跨考试制度比较**：老高考「理科」与新高考「物理类」不是同一群体。
     必须用 subject_type + exam_system 双重标记。
  2. **不得合并批次**：本科一批/二批的累计值是同一条曲线的两段，
     「本科一批累计 10~130195」+「本科二批 131720~329573」才是完整本科段。
  3. 保留 confidence 字段：数据集为渠道来源，未逐条对官方核实的标 `channel`。

用法：
  python data/scripts/import_score_segment.py --scan
  python data/scripts/import_score_segment.py
  python data/scripts/import_score_segment.py --province 河南 --year 2025
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "score_segment"

FIRST_NEW_GAOKAO = {"河南": 2025, "江西": 2024}

# 数据集来源登记（渠道）
CHANNEL = {
    "source_name": "河南省教育考试院 / 江西省教育考试院（上游）",
    "dataset": "Gaokao-Compass-11M",
    "dataset_doi": "10.57967/hf/9882",
    "source_id": "SRC-GAOKAO-COMPASS",
}

# ── 数据状态：以 ③ 数据集核实登记表为准 ──────────────────────────────── #
#   契约 v1.3 的 data_status 只有 available / partial / schema_only / unavailable，
#   且禁用 verified / pending / mock（docs/api-contract.md L41）。
#   「是否核实过」是另一个维度，登记在 data/dictionaries/dataset-verification.json，
#   由 data/scripts/dataset_status.py 维护。
#   ⚠️ 本脚本原先写死 "pending"（废弃枚举）——重新生成即回归，已改为查表。
REGISTRY = ROOT / "data" / "dictionaries" / "dataset-verification.json"


def data_status_of(province: str, year: int) -> str:
    """取该 (省, 年) 的契约 data_status；登记表缺项时保守取 partial。"""
    try:
        with REGISTRY.open("r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return "partial"
    for e in doc.get("entries", []):
        if (e.get("dataset") == "score_segment"
                and e.get("province") == province
                and int(e.get("year", 0)) == int(year)):
            return e.get("data_status", "partial")
    return "partial"


def to_int(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def to_float(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def exam_system_of(province: str, year: int) -> str:
    first = FIRST_NEW_GAOKAO.get(province)
    if first is None:
        return "unknown"
    return "3+1+2" if year >= first else "文理科"


def discover() -> list[tuple[str, int, Path]]:
    out = []
    for p in sorted(RAW.glob("*_score-range.csv")):
        parts = p.stem.split("_", 2)
        if len(parts) != 3:
            continue
        year_s, prov_en, _ = parts
        if not year_s.isdigit():
            continue
        province = {"henan": "河南", "jiangxi": "江西"}.get(prov_en, prov_en)
        if province not in FIRST_NEW_GAOKAO:
            continue
        out.append((province, int(year_s), p))
    return out


def import_one(province: str, year: int, path: Path) -> tuple[list[dict], dict]:
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    es = exam_system_of(province, year)
    segs: list[dict] = []
    for r in rows:
        cum = to_int(r.get("cumulative_count"))
        segs.append({
            "province": province,
            "year": year,
            "subject_type": (r.get("category") or "").strip(),
            "batch": (r.get("batch") or "").strip(),
            "score": to_float(r.get("score")),
            "cumulative_rank": cum,          # 第7章字段名
            "control_score": to_float(r.get("control_score")),
            "segment_count": to_int(r.get("segment_count")),
            "rank_range": (r.get("rank_range") or "").strip() or None,
            "score_range": (r.get("score_range") or "").strip() or None,
            "exam_system": es,
            "confidence": "channel",          # 渠道来源，未逐条对官方核实
            "data_status": data_status_of(province, year),   # ★ 查 ③ 核实登记表
            "source_id": CHANNEL["source_id"],
            "source_name": CHANNEL["source_name"],
            "source_url": "",
        })

    # 质量检查：单调性（同一 subject_type+batch 内，score 降序时 cumulative 应递增）
    mono_breaks = 0
    groups: dict[tuple, list] = {}
    for s in segs:
        groups.setdefault((s["subject_type"], s["batch"]), []).append(s)
    for k, g in groups.items():
        g2 = sorted([x for x in g if x["score"] is not None and x["cumulative_rank"] is not None],
                    key=lambda x: x["score"], reverse=True)
        for a, b in zip(g2, g2[1:]):
            if b["cumulative_rank"] < a["cumulative_rank"]:
                mono_breaks += 1

    stats = {
        "province": province, "year": year, "exam_system": es,
        "rows": len(segs),
        "groups": {f"{k[0]}|{k[1]}": len(v) for k, v in sorted(groups.items())},
        "monotonic_breaks": mono_breaks,
        "null_rank": sum(1 for s in segs if s["cumulative_rank"] is None),
        "data_status": data_status_of(province, year),
        "source_id": CHANNEL["source_id"],
    }
    return segs, stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--province")
    ap.add_argument("--year", type=int)
    ap.add_argument("--scan", action="store_true")
    args = ap.parse_args()

    items = discover()
    if args.province:
        items = [i for i in items if i[0] == args.province]
    if args.year:
        items = [i for i in items if i[1] == args.year]

    if args.scan:
        print(f"可导入 {len(items)} 个一分一段文件：")
        for prov, yr, p in items:
            print(f"  {prov} {yr} ({exam_system_of(prov, yr)})  {p.name}")
        return 0

    all_stats = []
    for prov, yr, p in items:
        segs, st = import_one(prov, yr, p)
        OUT.mkdir(parents=True, exist_ok=True)
        fn = OUT / f"score_segment_{yr}_{prov}.json"
        fn.write_text(json.dumps({
            "meta": {
                "title": f"{prov}省 {yr} 年一分一段表（{'新高考' if st['exam_system']=='3+1+2' else '老高考'}）",
                "target_table": "score_segment",
                "province": prov, "year": yr,
                "exam_system": st["exam_system"],
                "source_id": CHANNEL["source_id"],
                "source_name": CHANNEL["source_name"],
                "dataset": CHANNEL["dataset"],
                "dataset_doi": CHANNEL["dataset_doi"],
                "cumulative_rank_note": "官方口径：该分数及以上累计人数，即位次。",
                "batch_note": "★ 老高考一分为多段（本科一批/本科二批/专科批），"
                              "各段累计值连续，合并会丢批次线信息，故必须按 batch 保留。",
                "data_status": data_status_of(prov, yr),
                "verified_note": "核实状态与依据见 data/dictionaries/dataset-verification.json"
                                 "（由 data/scripts/dataset_status.py 维护）。",
            },
            "segments": segs,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        all_stats.append(st)
        st["file"] = str(fn.relative_to(ROOT))
        print(f"  ✓ {prov} {yr} ({st['exam_system']}) {st['rows']:>4} 行 "
              f"| 分组 {len(st['groups'])} | 单调破坏 {st['monotonic_breaks']} "
              f"| 空位次 {st['null_rank']} → {fn.name}")

    # 汇总报告
    rep = {
        "meta": {
            "generated_at": "2026-10-12",
            "owner": "徐（③ 数据工程）",
            "target_table": "score_segment",
            "purpose": "位次换算基础：分数 → 位次。供 ② 的推荐算法与志愿方案使用。",
        },
        "summary": {
            "files": len(all_stats),
            "total_rows": sum(s["rows"] for s in all_stats),
            "total_monotonic_breaks": sum(s["monotonic_breaks"] for s in all_stats),
            "total_null_rank": sum(s["null_rank"] for s in all_stats),
        },
        "files": all_stats,
    }
    (OUT / "_score_segment_import_report.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n合计 {rep['summary']['total_rows']} 行，"
          f"单调破坏 {rep['summary']['total_monotonic_breaks']} 处，"
          f"空位次 {rep['summary']['total_null_rank']} 处")
    return 0


if __name__ == "__main__":
    sys.exit(main())
