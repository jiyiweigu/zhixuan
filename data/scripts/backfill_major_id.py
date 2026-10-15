#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
回填 `school_major_score.major_id`：把录取分的 `major_name` 映射到 `major` 表

背景
  首期导入录取分时 major_id 全为 null（专业库尚未建立）。现将
  `data/majors/majors.json`（教育部本科专业目录 845 条 + 93 个专业类）
  作为映射表回填。

映射原则（★ 与 ③ 的数据红线一致：宁可缺，不可猜）
  1. **精确匹配优先**：专业名 == 目录专业名 → kind="专业"
  2. **专业类匹配**：专业名 == 目录专业类名（如「化学类」「工科试验班类」）→ kind="专业类"
     ⚠️ 这类**不是具体专业**，是招生时的「按专业类招生」。单独标注、**不合入专业**。
  3. **规范化后匹配**：仅做**零歧义**清洗——
     - 去除换行符与所有空白（已知脏值：17 个名字里插了 `\\n`，如 `健康服务\\n与管理`）
     - 全角括号 → 半角
     **不做**同义词推断、**不猜**错字。
  4. **不匹配就留 null**，并写入原因分类。**严禁强行映射**。

已知不可映射的类别（照实登记，不补）
  - 试验班 / 大类招生（如「工科试验班」「理科试验班」）——不是专业
  - 职业本科 / 专科专业（如「大数据与会计」「人工智能工程技术」）——不在本科目录
  - 疑似数据脏值（如「商务英诺」「国际经济与贸异」）——原样保留，不修

用法
  python data/scripts/backfill_major_id.py --dry-run   # 只统计
  python data/scripts/backfill_major_id.py             # 回填 + 写出报告
"""

import argparse
import collections
import glob
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAJORS = ROOT / "data" / "majors" / "majors.json"
SCORE_DIR = ROOT / "data" / "school_major_score"
REPORT = SCORE_DIR / "_major_id_backfill_report.json"

MAJOR_TABLE_SOURCE = "SRC-MOE-ZHUANYE-2025"


# ─────────────────────────────────────────────
# 规范化（只做零歧义清洗）
# ─────────────────────────────────────────────

_WS = re.compile(r"\s+")


def normalize(name: str) -> str:
    """去所有空白 + 全角括号转半角。不改变任何汉字。"""
    s = _WS.sub("", name or "")
    s = s.replace("（", "(").replace("）", ")")
    return s.strip()


# 试验班 / 大类招生：明确不是「专业」，单列
RE_EXPERIMENT = re.compile(r"试验班|实验班|大类招生|强化班|基地班|菁英班|英才班")


def classify_unmatched(name: str, norm: str) -> str:
    """给未匹配的名字归类（用于 report，不用于猜测映射）"""
    if RE_EXPERIMENT.search(name):
        return "试验班/大类招生（非专业）"
    if re.search(r"(工程技术|制作技术|数字技术|控制技术|智能技术|测绘技术)$", name):
        return "疑似职业本科/专科专业（不在本科目录）"
    if re.match(r"^大数据与", name) or re.match(r"^云计算|^区块链|^人工智能工程", name):
        return "疑似职业本科/专科专业（不在本科目录）"
    if re.search(r"(管理|服务|运营|策划|制作)$", name) and len(name) >= 5:
        return "疑似职业本科/专科专业（不在本科目录）"
    if name != norm:
        return "规范化后仍未匹配"
    return "院校自设专业名/其他（需人工确认）"


def build_indexes():
    data = json.loads(MAJORS.read_text(encoding="utf-8"))
    majors = data["majors"]
    classes = data["classes"]

    by_name: dict[str, dict] = {}
    by_norm: dict[str, dict] = {}
    for m in majors:
        by_name.setdefault(m["name"], m)
        by_norm.setdefault(normalize(m["name"]), m)

    cls_by_name: dict[str, dict] = {}
    cls_by_norm: dict[str, dict] = {}
    for c in classes:
        cls_by_name.setdefault(c["class_name"], c)
        cls_by_norm.setdefault(normalize(c["class_name"]), c)

    return majors, classes, by_name, by_norm, cls_by_name, cls_by_norm


def resolve(name: str, idx) -> dict | None:
    """返回 {'matched': True, 'kind': '专业'|'专业类', ...} 或 None"""
    _, _, by_name, by_norm, cls_by_name, cls_by_norm = idx
    raw = (name or "").strip()
    if not raw:
        return None

    # 1) 精确命中专业
    if raw in by_name:
        m = by_name[raw]
        return {"kind": "专业", "code": m["code"], "matched_name": m["name"],
                "class_code": m["class_code"], "class_name": m["class_name"],
                "menlei": m["menlei"], "via": "exact"}

    # 2) 精确命中专业类
    if raw in cls_by_name:
        c = cls_by_name[raw]
        return {"kind": "专业类", "code": c["class_code"], "matched_name": c["class_name"],
                "class_code": c["class_code"], "class_name": c["class_name"],
                "menlei": c["menlei"], "via": "exact"}

    # 3) 规范化后命中专业
    n = normalize(raw)
    if n in by_norm:
        m = by_norm[n]
        return {"kind": "专业", "code": m["code"], "matched_name": m["name"],
                "class_code": m["class_code"], "class_name": m["class_name"],
                "menlei": m["menlei"], "via": "normalized"}

    # 4) 规范化后命中专业类
    if n in cls_by_norm:
        c = cls_by_norm[n]
        return {"kind": "专业类", "code": c["class_code"], "matched_name": c["class_name"],
                "class_code": c["class_code"], "class_name": c["class_name"],
                "menlei": c["menlei"], "via": "normalized"}

    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    idx = build_indexes()
    majors, classes = idx[0], idx[1]

    files = sorted(glob.glob(str(SCORE_DIR / "school_major_score_*.json")))
    if not files:
        print("✗ 未找到录取分文件", file=sys.stderr)
        return 2

    report_files = []
    grand = collections.Counter()
    unresolved_map: dict[str, dict] = {}

    for path in files:
        p = Path(path)
        doc = json.loads(p.read_text(encoding="utf-8"))
        rows = doc["scores"]

        stat = collections.Counter()
        for r in rows:
            name = (r.get("major_name") or "").strip()
            if not name:
                r["major_id"] = None
                r["major_match"] = None
                stat["空专业名"] += 1
                continue

            hit = resolve(name, idx)
            if hit:
                # major_id 用专业代码（国标码，唯一且稳定）；
                # 命中专业类时用 4 位类码，靠 major_match.kind 区分
                r["major_id"] = hit["code"]
                r["major_match"] = {
                    "kind": hit["kind"],
                    "matched_name": hit["matched_name"],
                    "class_code": hit["class_code"],
                    "class_name": hit["class_name"],
                    "menlei": hit["menlei"],
                    "via": hit["via"],
                }
                stat[f"命中-{hit['kind']}-{hit['via']}"] += 1
            else:
                r["major_id"] = None
                r["major_match"] = None
                stat["未匹配"] += 1
                n = normalize(name)
                key = name
                if key not in unresolved_map:
                    unresolved_map[key] = {
                        "name": name,
                        "normalized": n,
                        "rows": 0,
                        "reason": classify_unmatched(name, n),
                    }
                unresolved_map[key]["rows"] += 1

        doc.setdefault("meta", {})["major_id_note"] = (
            "major_id 已按 `data/majors/majors.json`（教育部本科专业目录2025年）回填。"
            "kind=专业 → 6/7 位国标专业代码；kind=专业类 → 4 位专业类代码（按类招生，非具体专业）。"
            "未匹配者 major_id=null 并保留 major_name 原文，原因见 _major_id_backfill_report.json。"
        )
        doc["meta"]["major_table_source_id"] = MAJOR_TABLE_SOURCE

        total = len(rows)
        matched = total - stat["未匹配"] - stat["空专业名"]
        report_files.append({
            "file": p.name,
            "province": doc["meta"].get("province"),
            "year": doc["meta"].get("year"),
            "rows": total,
            "matched": matched,
            "match_rate": round(matched / total, 4) if total else 0,
            "unmatched": stat["未匹配"],
            "blank_major_name": stat["空专业名"],
            "by_kind": {
                "专业": stat["命中-专业-exact"] + stat["命中-专业-normalized"],
                "专业类": stat["命中-专业类-exact"] + stat["命中-专业类-normalized"],
            },
            "by_via": {
                "exact": stat["命中-专业-exact"] + stat["命中-专业类-exact"],
                "normalized": stat["命中-专业-normalized"] + stat["命中-专业类-normalized"],
            },
        })
        grand.update(stat)

        if not args.dry_run:
            p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 汇总 ──
    tot_rows = sum(f["rows"] for f in report_files)
    tot_matched = sum(f["matched"] for f in report_files)
    tot_unmatched = sum(f["unmatched"] for f in report_files)

    print("=" * 66)
    print("major_id 回填结果")
    print("=" * 66)
    print(f"专业表来源          : {MAJOR_TABLE_SOURCE}（{len(majors)} 专业 + {len(classes)} 专业类）")
    print(f"录取分行数          : {tot_rows}")
    print(f"已映射 major_id     : {tot_matched}  ({tot_matched/tot_rows*100:.2f}%)")
    print(f"  其中 具体专业     : {grand['命中-专业-exact']+grand['命中-专业-normalized']}")
    print(f"  其中 专业类(按类) : {grand['命中-专业类-exact']+grand['命中-专业类-normalized']}")
    print(f"未映射              : {tot_unmatched}  ({tot_unmatched/tot_rows*100:.2f}%)")
    print()
    print(f"{'省':<4}{'年':<6}{'行数':>8}{'已映射':>9}{'命中率':>9}{'未映射':>8}")
    for f in report_files:
        print(f"{f['province']:<4}{f['year']:<6}{f['rows']:>8}{f['matched']:>9}"
              f"{f['match_rate']*100:>8.2f}%{f['unmatched']:>8}")
    print()
    print(f"未映射的去重专业名 : {len(unresolved_map)} 个")
    reason = collections.Counter(v['reason'] for v in unresolved_map.values())
    reason_rows = collections.Counter()
    for v in unresolved_map.values():
        reason_rows[v['reason']] += v['rows']
    for r, c in reason.most_common():
        print(f"   {r:<44} {c:>3} 个 / {reason_rows[r]:>5} 行")
    print()

    if not args.dry_run:
        REPORT.write_text(json.dumps({
            "meta": {
                "generated_at": str(date.today()),
                "owner": "徐（③ 数据工程）",
                "target_table": "school_major_score",
                "purpose": "回填 major_id；未匹配者照实登记原因，不做推断",
                "major_table": "data/majors/majors.json",
                "major_table_source_id": MAJOR_TABLE_SOURCE,
                "parser": "data/scripts/backfill_major_id.py",
                "rule": "精确匹配 → 专业类匹配 → 去空白/全角转半角后匹配；其余留 null",
            },
            "summary": {
                "rows": tot_rows,
                "matched": tot_matched,
                "unmatched": tot_unmatched,
                "match_rate": round(tot_matched / tot_rows, 4),
                "matched_as_major": grand['命中-专业-exact'] + grand['命中-专业-normalized'],
                "matched_as_class": grand['命中-专业类-exact'] + grand['命中-专业类-normalized'],
                "unmatched_distinct_names": len(unresolved_map),
                "reason_distribution": {
                    r: {"names": c, "rows": reason_rows[r]}
                    for r, c in reason.most_common()
                },
            },
            "files": report_files,
            "unresolved": sorted(
                unresolved_map.values(), key=lambda x: -x["rows"]
            ),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✅ 已回填 {len(files)} 个文件")
        print(f"✅ 已写出 {REPORT.relative_to(ROOT)}")
    else:
        print("(--dry-run，未写出)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
