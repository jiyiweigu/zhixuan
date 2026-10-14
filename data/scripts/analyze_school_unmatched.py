# -*- coding: utf-8 -*-
"""
N21 诊断 · 事实表院校挂载失败清单（只诊断，不改数据）
=====================================================
目的：定位「招生计划 / 录取分」中挂不上院校库 `school_id` 的院校，
      为院校库补录（③ 独立任务）提供**可核对的清单**。

★ 只读诊断：不写任何产物（除 --out 指定的清单文件）。
★ 依据：铁律「宁可缺不可猜」——本脚本只输出「库中确无此校」的事实，
        不推断、不补名。

用法：
    python analyze_school_unmatched.py                 # 招生计划（本科批）
    python analyze_school_unmatched.py --kind all      # 招生计划 + 录取分
    python analyze_school_unmatched.py --out xxx.json  # 落盘清单
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
SCHOOLS = DATA / "schools" / "schools_merged.json"
MOE = DATA / "schools" / "moe_schools.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_major_score import SchoolIndex, AliasIndex  # noqa: E402


def is_benke(batch: str) -> bool:
    b = (batch or "").strip()
    return bool(b) and "专" not in b and "本" in b


def match_school(idx: SchoolIndex, alias: AliasIndex, code: str, name: str,
                 cache: dict) -> tuple[int | None, str]:
    key = (code or "", name or "")
    if key in cache:
        return cache[key]
    sid = idx.resolve_henan(code or "") or idx.resolve_name(name)
    how = "code" if (sid and idx.resolve_henan(code or "")) else ("name" if sid else "")
    if sid is None:
        cur = alias.resolve(name)
        if cur:
            sid2 = idx.resolve_name(cur)
            if sid2 is not None:
                sid, how = sid2, "alias"
            else:
                how = "alias_target_missing"
        else:
            how = "none"
    cache[key] = (sid, how)
    return sid, how


def scan_enrollment(idx, alias):
    """招生计划（本科批）——与 build_enrollment_rule.py 同口径。"""
    stats = collections.Counter()
    miss = collections.defaultdict(lambda: {"rows": 0, "years": set(),
                                            "henan_codes": set(), "provinces": set(),
                                            "how": ""})
    cache: dict = {}
    for f in sorted(RAW.glob("*_enrollment-plan.csv")):
        year = int(f.stem.split("_", 1)[0])
        province = "河南" if "henan" in f.stem else "江西"
        with f.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                stats["rows"] += 1
                if not is_benke(row.get("batch")):
                    stats["skip_not_benke"] += 1
                    continue
                nm = (row.get("university_name") or "").strip()
                if not nm or nm.upper() == "<NA>":
                    stats["skip_no_name"] += 1
                    continue
                sid, how = match_school(idx, alias, row.get("university_code") or "", nm, cache)
                if sid is None:
                    stats["unmatched_rows"] += 1
                    d = miss[nm]
                    d["rows"] += 1
                    d["years"].add(year)
                    d["provinces"].add(province)
                    d["how"] = how
                    hc = (row.get("university_code") or "").strip()
                    if hc and province == "河南":
                        d["henan_codes"].add(hc)
                else:
                    stats["matched_rows"] += 1
    return stats, miss


def scan_score(idx, alias, kind: str):
    """录取分：kind = 'major' 或 'school'。"""
    stats = collections.Counter()
    miss = collections.defaultdict(lambda: {"rows": 0, "years": set(),
                                            "henan_codes": set(), "provinces": set(),
                                            "how": ""})
    cache: dict = {}
    for f in sorted(RAW.glob(f"*_{kind}-admission.csv")):
        year = int(f.stem.split("_", 1)[0])
        province = "河南" if "henan" in f.stem else "江西"
        with f.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                stats["rows"] += 1
                nm = (row.get("university_name") or "").strip()
                if not nm or nm.upper() == "<NA>":
                    stats["skip_no_name"] += 1
                    continue
                sid, how = match_school(idx, alias, row.get("university_code") or "", nm, cache)
                if sid is None:
                    stats["unmatched_rows"] += 1
                    d = miss[nm]
                    d["rows"] += 1
                    d["years"].add(year)
                    d["provinces"].add(province)
                    d["how"] = how
                    hc = (row.get("university_code") or "").strip()
                    if hc and province == "河南":
                        d["henan_codes"].add(hc)
                else:
                    stats["matched_rows"] += 1
    return stats, miss


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["plan", "all"], default="plan")
    ap.add_argument("--top", type=int, default=60)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    idx = SchoolIndex(SCHOOLS)
    alias = AliasIndex(DATA / "schools" / "school_aliases.json")
    moe = json.loads(MOE.read_text(encoding="utf-8"))["records"]
    moe_names = {(r.get("name") or "").strip() for r in moe}

    print("=" * 78)
    print("N21 诊断 · 事实表院校挂载失败清单")
    print(f"院校库 {len(idx.records)} 所 ｜ 教育部名单 {len(moe_names)} 所")
    print("=" * 78)

    results = {}
    pstats, pmiss = scan_enrollment(idx, alias)
    results["enrollment_plan_benke"] = (pstats, pmiss)
    print(f"\n【招生计划·本科批】行 {pstats['rows']:,} ｜ 匹配 {pstats['matched_rows']:,} "
          f"｜ 未匹配 {pstats['unmatched_rows']:,} ｜ 涉及院校 {len(pmiss)}")
    print(f"  跳过：非本科批 {pstats['skip_not_benke']:,} ｜ 无名 {pstats['skip_no_name']:,}")

    if args.kind == "all":
        for kind, label in (("major", "专业录取分"), ("school", "院校录取分")):
            s, m = scan_score(idx, alias, kind)
            results[f"{kind}_admission"] = (s, m)
            print(f"\n【{label}】行 {s['rows']:,} ｜ 匹配 {s['matched_rows']:,} "
                  f"｜ 未匹配 {s['unmatched_rows']:,} ｜ 涉及院校 {len(m)}")

    # ── 招生计划未匹配清单（按行数降序）──────────────────────────────
    print("\n" + "-" * 78)
    print("招生计划·本科批 未匹配院校（行数降序，前 %d）" % args.top)
    print("-" * 78)
    print(f"{'院校名':<30}{'行数':>7}  {'省':<4} {'年份':<14} {'教育部名单':<10} 匹配退化")
    ordered = sorted(pmiss.items(), key=lambda kv: (-kv[1]["rows"], kv[0]))
    in_moe = 0
    for nm, d in ordered[:args.top]:
        y = ",".join(str(x) for x in sorted(d["years"]))
        pv = ",".join(sorted(d["provinces"]))
        inlist = "✓" if nm in moe_names else "-"
        if nm in moe_names:
            in_moe += 1
        print(f"{nm:<30}{d['rows']:>7}  {pv:<4} {y:<14} {inlist:<10} {d['how']}")

    tot_in_moe = sum(1 for nm in pmiss if nm in moe_names)
    print("-" * 78)
    print(f"未匹配院校总数 {len(pmiss)} ｜ 其中 {tot_in_moe} 所可在教育部名单中找到"
          f"（→ 可直接补录）｜ {len(pmiss) - tot_in_moe} 所名单外")

    # 名单外院校（需另行核实）
    outside = sorted([nm for nm in pmiss if nm not in moe_names])
    if outside:
        print(f"\n⚠ 教育部名单外（{len(outside)} 所，需单独溯源）：")
        for i in range(0, len(outside), 4):
            print("   " + " ｜ ".join(outside[i:i + 4]))

    if args.out:
        out = Path(args.out)
        payload = {
            "meta": {
                "purpose": "N21 院校库补录清单（诊断产物，非灌数数据）",
                "library_size": len(idx.records),
                "moe_list_size": len(moe_names),
                "owner": "徐（③ 数据工程）",
            },
            "enrollment_plan_benke": {
                "stats": dict(pstats),
                "unmatched_schools": [
                    {"name": nm, "rows": d["rows"],
                     "years": sorted(d["years"]), "provinces": sorted(d["provinces"]),
                     "henan_codes": sorted(d["henan_codes"]),
                     "in_moe_list": nm in moe_names, "match_fallback": d["how"]}
                    for nm, d in ordered
                ],
            },
        }
        if args.kind == "all":
            for key in ("major_admission", "school_admission"):
                s, m = results[key]
                payload[key] = {
                    "stats": dict(s),
                    "unmatched_schools": [
                        {"name": nm, "rows": d["rows"],
                         "years": sorted(d["years"]), "provinces": sorted(d["provinces"]),
                         "henan_codes": sorted(d["henan_codes"]),
                         "in_moe_list": nm in moe_names}
                        for nm, d in sorted(m.items(), key=lambda kv: (-kv[1]["rows"], kv[0]))
                    ],
                }
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n清单已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
