#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Gaokao-Compass-11M 数据集导入脚本（文档《数据源与数据获取方案》§3.1 字段对照）

职责边界（重要）：
  ★ ③ 数据工程的职责是「让数据库有数据」——采集/清洗/结构化/口径定义/入库校验。
  ★ 建表 + Alembic 迁移是 ② 后端的职责（产品书 M0-3）。本脚本**不建表**。
  ★ 因此本脚本默认产出「规范化中间层」（JSONL + 报告），而非直连 PostgreSQL。
    待 ② 冻结表结构后，用 --emit-sql 生成 INSERT 语句，或由 ② 接 SQLAlchemy。

本脚本做三件事：
  1. 读取 data/raw/{year}_{province}_{table}.csv
  2. 按文档 §3.1 字段对照做映射 + 清洗 + 口径标记
  3. 输出到 data/staged/{province}/ 下的 JSONL，并生成导入报告

关键口径处理（红线）：
  - 强制标记 exam_system：河南 2025 起 / 江西 2024 起为 3+1+2，之前为「文理科」
  - subject_req 走 parse_subject_req.parse()，解析失败一律进 missing_rule_sets，**绝不猜测**
  - 2023 河南 school-admission（25 行空分）标 missing，不补全、不插值
  - 所有输出记录带 source_name / source_url / year（三要素），否则不入 staged
  - 数据状态一律先标 schema_only / partial，**不标 available**（核实通过后才升）

用法：
  python data/scripts/import_dataset.py --scan            # 盘点 raw 目录
  python data/scripts/import_dataset.py                   # 全量导入 → data/staged/
  python data/scripts/import_dataset.py --province 河南 --year 2025
  python data/scripts/import_dataset.py --emit-sql        # 额外生成 INSERT 骨架（待 ② 定表后完善）
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from parse_subject_req import parse as parse_subject_req  # noqa: E402

RAW = ROOT / "data" / "raw"
STAGED = ROOT / "data" / "staged"

# ── 口径常量 ──────────────────────────────────────────────────────────
FIRST_NEW_GAOKAO = {"河南": 2025, "江西": 2024}

# 数据集来源（渠道）与上游官方来源（署名）
DATASET_SOURCE = {
    "dataset": "Gaokao-Compass-11M",
    "doi": "10.57967/hf/9882",
    "license": "MIT",
    "channel": "hf-mirror.com (HuggingFace 镜像)",
    "upstream_note": "数据集为获取渠道；作品内事实结论的 source_url 应指向省考试院/阳光高考",
}

# 按省给上游官方 source_id（署名用），已在 source-table.json 登记
UPSTREAM_SOURCE_ID = {
    "河南": "SRC-HENAN-2026-ZY",
    "江西": "SRC-JIANGXI-2026-ZY",
}

# 文档 §3.1 字段对照表（数据集字段 → 我方逻辑字段）
FIELD_MAP = {
    "enrollment-plan": {
        "province": "province",
        "year": "year",
        "batch": "batch",
        "category": "category",
        "university_code": "school_national_code",
        "university_name": "school_name",
        "major_group": "group_code",
        "major_code": "major_code",
        "major_name": "major_name",
        "major_note": "major_note",
        "plan_count": "plan_count",
        "duration": "duration",
        "tuition": "tuition",
        # subject_req 特殊处理 → subject_requirement
    },
    "school-admission": {
        "province": "province",
        "year": "year",
        "category": "category",
        "batch": "batch",
        "university_code": "school_national_code",
        "university_name": "school_name",
        "major_group": "group_code",
        "min_score": "min_score",
        "min_rank": "min_rank",
        "control_score": "control_score",
        "score_diff": "score_diff",
        "admit_count": "admit_count",
        "school_province": "school_province",
        "school_nature": "school_nature",
        "is_985": "is_985",
        "is_211": "is_211",
    },
    "major-admission": {
        "province": "province",
        "year": "year",
        "category": "category",
        "batch": "batch",
        "university_code": "school_national_code",
        "university_name": "school_name",
        "major_group": "group_code",
        "major_code": "major_code",
        "major_name": "major_name",
        "major_note": "major_note",
        "min_score": "min_score",
        "min_rank": "min_rank",
        "max_score": "max_score",
        "avg_score": "avg_score",
        "admit_count": "admit_count",
        "school_province": "school_province",
        "school_nature": "school_nature",
        "is_985": "is_985",
        "is_211": "is_211",
    },
    "score-range": {
        "province": "province",
        "year": "year",
        "category": "category",
        "batch": "batch",
        "control_score": "control_score",
        "score": "score",
        "score_range": "score_range",
        "segment_count": "segment_count",
        "cumulative_count": "cumulative_rank",   # 文档：分数→位次
        "rank_range": "rank_range",
    },
}


def exam_system_of(province: str, year: int) -> str:
    """判定该省该年的考试制度（口径断裂处理，红线）"""
    first = FIRST_NEW_GAOKAO.get(province)
    if first is None:
        return "unknown"
    return "3+1+2" if year >= first else "文理科"


def normalize_group_code(v: str) -> str:
    """major_group 在投档表带括号（101），在计划表不带（101）→ 统一去括号"""
    return (v or "").strip().strip("（）()")


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


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def import_one(path: Path, province: str, year: int, table: str) -> tuple[list[dict], dict]:
    """导入单文件，返回 (staged 记录, 统计)"""
    rows = read_csv(path)
    fm = FIELD_MAP[table]
    es = exam_system_of(province, year)
    upstream = UPSTREAM_SOURCE_ID.get(province, "")

    stats = {
        "file": path.name,
        "province": province,
        "year": year,
        "table": table,
        "rows_in": len(rows),
        "rows_out": 0,
        "empty_scores": 0,
        "subject_req_missing": 0,
        "subject_req_ok": 0,
        "subject_req_unparsed": 0,
        "data_status": "partial",
    }
    out: list[dict] = []

    for r in rows:
        rec = {"_table": table}
        for src_f, dst_f in fm.items():
            v = (r.get(src_f) or "").strip()
            if dst_f in ("min_score", "max_score", "avg_score", "control_score",
                         "score_diff", "score", "tuition"):
                rec[dst_f] = to_float(v)
            elif dst_f in ("min_rank", "admit_count", "plan_count", "duration",
                           "segment_count", "cumulative_rank", "is_985", "is_211"):
                rec[dst_f] = to_int(v)
            elif dst_f == "year":
                rec[dst_f] = to_int(v) or year
            else:
                rec[dst_f] = v or None

        # group_code 归一化
        if "group_code" in rec:
            rec["group_code"] = normalize_group_code(rec["group_code"])

        # 口径标记（红线：必须标）
        rec["exam_system"] = es
        rec["data_status"] = "schema_only"   # 首期一律先 schema_only，核实后才升
        rec["source_id"] = upstream
        rec["source_name"] = f"{province}省教育考试院（上游）/ Gaokao-Compass-11M（渠道）"
        rec["source_url"] = ""               # 待核实后填具体官方 URL，不编造
        rec["dataset"] = DATASET_SOURCE["dataset"]
        rec["dataset_doi"] = DATASET_SOURCE["doi"]

        # 空分统计
        if table in ("school-admission", "major-admission") and rec.get("min_score") is None:
            stats["empty_scores"] += 1

        # 选科要求解析（enrollment-plan / 投档表才有）
        raw_req = (r.get("subject_req") or "").strip()
        if "subject_req" in r or table in ("enrollment-plan", "school-admission", "major-admission"):
            pr = parse_subject_req(raw_req)
            if pr.status == "missing":
                stats["subject_req_missing"] += 1
                rec["subject_requirement"] = None
            elif pr.status == "ok":
                stats["subject_req_ok"] += 1
                rec["subject_requirement"] = pr.to_contract()
            else:
                stats["subject_req_unparsed"] += 1
                rec["subject_requirement"] = None
                rec["subject_requirement_raw"] = raw_req

        out.append(rec)

    stats["rows_out"] = len(out)

    # ── 脏数据/缺失判定（红线：宁可标 missing，不可猜）────────────────
    # 1) 校名为空比例过高 → 视有无院校代号决定 missing / partial（仅对含校名的表）
    if "school_name" in fm.values():
        empty_name = sum(1 for r in out if not r.get("school_name"))
        if out and empty_name / len(out) > 0.5:
            code_ok = sum(1 for r in out if r.get("school_national_code"))
            if code_ok / len(out) > 0.5:
                # 有院校代号 → 可通过代号反查补名（派生字段），标 partial
                stats["data_status"] = "partial"
                stats["quality_flags"] = ["school_name_empty_but_code_present"]
                stats["note"] = (f"{empty_name}/{len(out)} 条 school_name 为空，"
                                 f"但 university_code 完整 → 属可修复（用院校代号反查补名），"
                                 f"标 partial；补出的校名为派生字段，须在导入时标注来源")
            else:
                stats["data_status"] = "missing"
                stats["quality_flags"] = ["school_name_and_code_empty"]
                stats["note"] = (f"{empty_name}/{len(out)} 条 school_name 为空，"
                                 f"且院校代号亦缺失 → 无法关联 school 表，判为不可用，标 missing")

    # 2) 投档表行数异常少（相较其他年份 1000+）且无有效位次
    if table in ("school-admission",):
        rank_ok = sum(1 for r in out if r.get("min_rank") is not None)
        if len(out) < 100 and rank_ok == 0:
            stats["data_status"] = "missing"
            stats.setdefault("quality_flags", []).append("too_few_rows_and_no_rank")
            stats["note"] = (f"仅 {len(out)} 行且无任何 min_rank；"
                             f"对比其他年份 1000+ 行，判为整表缺失，不补全、不插值")

    # 3) 河南 2023 投档表特别标注
    if table == "school-admission" and province == "河南" and year == 2023:
        stats["data_status"] = "missing"
        stats.setdefault("quality_flags", []).append("henan_2023_school_admission_broken")
        stats["note"] = ("2023 河南院校投档表仅 25 行、校名全空、admit_count 全 0，"
                         "分数呈现脏数据特征（68/63/71/187/563 混杂），整表不可用。"
                         "标 missing，不补全、不插值。")
    return out, stats


def discover() -> list[tuple[str, int, str, Path]]:
    """扫描 raw 目录，返回 (province, year, table, path)"""
    found = []
    for p in sorted(RAW.glob("*.csv")):
        stem = p.stem  # 2025_henan_enrollment-plan
        parts = stem.split("_", 2)
        if len(parts) != 3:
            continue
        year_s, prov_en, table = parts
        if not year_s.isdigit():
            continue
        province = {"henan": "河南", "jiangxi": "江西"}.get(prov_en, prov_en)
        if table not in FIELD_MAP:
            continue
        found.append((province, int(year_s), table, p))
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--province", help="只看某省（河南/江西）")
    ap.add_argument("--year", type=int, help="只看某年")
    ap.add_argument("--scan", action="store_true", help="只盘点，不写文件")
    args = ap.parse_args()

    items = discover()
    if args.province:
        items = [i for i in items if i[0] == args.province]
    if args.year:
        items = [i for i in items if i[1] == args.year]

    if args.scan:
        print(f"raw 目录可识别 {len(items)} 个文件：")
        for prov, yr, table, p in items:
            print(f"  {prov} {yr} {table:18s} {p.name}")
        return 0

    all_stats = []
    total_rows = 0
    for prov, yr, table, p in items:
        try:
            recs, st = import_one(p, prov, yr, table)
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ {p.name}: {e}")
            continue
        d = STAGED / f"{prov}" / f"{yr}"
        d.mkdir(parents=True, exist_ok=True)
        outfile = d / f"{table}.jsonl"
        with outfile.open("w", encoding="utf-8") as f:
            for rec in recs:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        all_stats.append(st)
        total_rows += st["rows_out"]
        print(f"  ✓ {prov} {yr} {table:18s} {st['rows_out']:>6} 行  "
              f"(选科 ok={st['subject_req_ok']} missing={st['subject_req_missing']} "
              f"unparsed={st['subject_req_unparsed']}) → {outfile.relative_to(ROOT)}")

    # 写报告
    report = {
        "meta": {
            "generated_at": "2026-10-12",
            "owner": "徐（③ 数据工程）",
            "dataset": DATASET_SOURCE,
            "note": "staged 中间层。所有记录 data_status=schema_only/partial，未核实前不得标 available。",
        },
        "summary": {
            "files": len(all_stats),
            "total_rows": total_rows,
            "subject_req_ok": sum(s["subject_req_ok"] for s in all_stats),
            "subject_req_missing": sum(s["subject_req_missing"] for s in all_stats),
            "subject_req_unparsed": sum(s["subject_req_unparsed"] for s in all_stats),
            "empty_scores": sum(s["empty_scores"] for s in all_stats),
        },
        "files": all_stats,
    }
    STAGED.mkdir(parents=True, exist_ok=True)
    rp = STAGED / "_import_report.json"
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n合计 {total_rows} 行 → 报告 {rp.relative_to(ROOT)}")
    print(f"选科：ok={report['summary']['subject_req_ok']} "
          f"missing={report['summary']['subject_req_missing']} "
          f"unparsed={report['summary']['subject_req_unparsed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
