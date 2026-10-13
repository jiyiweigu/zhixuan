"""
智选志愿 · 江西高考数据采集主程序。

运行：
    cd <repo-root>
    python -m data.jiangxi.run                 # 全程联网采集
    python -m data.jiangxi.run --offline       # 不联网（用已核验种子/基准值）
    python -m data.jiangxi.run --only region,eligibility,batch
    python -m data.jiangxi.run --fieldmap      # 打印「字段→来源→URL→解析方式」
    python -m data.jiangxi.run --export-seeds  # 导出种子为 JSON
    python -m data.jiangxi.run --selftest      # 离线自检

输出（data/jiangxi/output/）：
    <doc_type>.json / .csv   + validation_report.json + reject_report.json
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# 允许 `python data/jiangxi/run.py` 直接运行
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from data.jiangxi import config, collectors, seeds, validators  # noqa: E402
from data.jiangxi.fetcher import Fetcher  # noqa: E402

OUTPUT_DIR = config.OUTPUT_DIR
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("jx.run")


# ---------------------------------------------------------------------------
# 采集 + 清洗 + 输出
# ---------------------------------------------------------------------------
def run(only: list[str] | None, offline: bool, limit: int | None,
        sleep: float | None = None) -> tuple[dict, dict]:
    groups = only or collectors.DEFAULT_ORDER
    bad = [g for g in groups if g not in collectors.COLLECTORS]
    if bad:
        raise SystemExit(f"--only 含未知分组：{bad}\n可选：{list(collectors.COLLECTORS)}")

    all_records: list[validators.Record] = []
    stats: dict[str, dict] = {}
    t0 = time.time()

    with Fetcher(**({"sleep": sleep} if sleep is not None else {})) as fetcher:
        for g in groups:
            fn = collectors.COLLECTORS[g]
            logger.info("===== 采集模块：%s =====", g)
            try:
                import inspect
                kw = {}
                if "limit" in inspect.signature(fn).parameters:
                    kw["limit"] = limit
                recs = fn(fetcher, offline=offline, **kw)
            except Exception as e:  # noqa: BLE001
                logger.exception("模块 %s 失败：%s", g, e)
                recs = []
            logger.info("  模块 %s -> %d 条", g, len(recs))
            all_records.extend(recs)

    # 按 doc_type 分组清洗
    by_type: dict[str, list[validators.Record]] = {}
    for r in all_records:
        by_type.setdefault(r.doc_type, []).append(r)

    for dt, recs in by_type.items():
        cr = validators.clean(recs)
        stats[dt] = cr
        write_output(dt, cr)

    logger.info("采集完成，耗时 %.1fs", time.time() - t0)
    return stats, build_report(stats)


def write_output(doc_type: str, cr: validators.CleanResult) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = cr.valid
    (OUTPUT_DIR / f"{doc_type}.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    keys: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k)
                keys.append(k)
    with open(OUTPUT_DIR / f"{doc_type}.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys or ["empty"], restval="")
        w.writeheader()
        w.writerows(rows)


def build_report(stats: dict[str, validators.CleanResult]) -> dict:
    checks: list[dict] = []
    total_valid = sum(cr.valid_count for cr in stats.values())
    total_rej = sum(cr.rejected_count for cr in stats.values())

    # 1. 来源三要素覆盖率
    for dt, cr in stats.items():
        miss = sum(1 for r in cr.valid
                   if not r.get("source_name") or not r.get("source_url") or not r.get("year"))
        checks.append({"item": f"{dt} 来源三要素覆盖率", "required": "100%",
                       "actual": f"{(cr.valid_count - miss) / cr.valid_count * 100:.1f}%"
                       if cr.valid_count else "N/A",
                       "pass": cr.valid_count > 0 and miss == 0})

    # 2. 专项县名单口径
    pr = stats.get("pathway_region")
    if pr and pr.valid:
        from collections import Counter
        cnt = dict(Counter(r["pathway_name"] for r in pr.valid))
        checks.append({"item": "专项县名单口径（国家24/高校58/苏区54/地方全省）",
                       "required": "国家≥24, 高校≥58, 苏区≥54, 地方=1(全省meta)",
                       "actual": cnt,
                       "pass": (cnt.get("国家专项计划", 0) >= 24
                                and cnt.get("高校专项计划", 0) >= 58
                                and cnt.get("苏区专项计划", 0) >= 54
                                and cnt.get("地方专项计划", 0) >= 1)})

    # 3. 一分一段位次单调性
    seg = stats.get("score_segment")
    if seg and seg.valid:
        ok = True
        keys = {(r["year"], r["subject_type"]) for r in seg.valid}
        for y, s in keys:
            rows = sorted([r for r in seg.valid if r["year"] == y and r["subject_type"] == s],
                          key=lambda r: r["score"], reverse=True)
            ranks = [r["cumulative_rank"] for r in rows]
            if ranks != sorted(ranks):
                ok = False
        checks.append({"item": "一分一段位次单调性", "required": "分数降序→位次升序",
                       "actual": "通过" if ok else "异常", "pass": ok})

    # 4. 批次线分数范围
    bl = stats.get("batch_score_line")
    if bl and bl.valid:
        scores = [r["score"] for r in bl.valid]
        checks.append({"item": "批次线分数范围", "required": "0-750",
                       "actual": f"{min(scores)}-{max(scores)}",
                       "pass": 0 <= min(scores) and max(scores) <= 750})

    # 5. 途径字典数量
    pw = stats.get("pathway")
    if pw:
        checks.append({"item": "途径字典数量", "required": "26 类",
                       "actual": f"{pw.valid_count} 类", "pass": pw.valid_count == 26})

    # 6. 专业组投档线（B6）：分数范围 + 位次覆盖 + 院校广度
    ga = stats.get("group_admission")
    if ga and ga.valid:
        scores = [r["min_score"] for r in ga.valid if r.get("min_score")]
        ranked = sum(1 for r in ga.valid if r.get("min_rank"))
        schools = {r.get("school_name") for r in ga.valid}
        checks.append({"item": "B6 投档线分数范围", "required": "0-750",
                       "actual": f"{min(scores)}-{max(scores)}" if scores else "N/A",
                       "pass": bool(scores) and 0 < min(scores) and max(scores) <= 750})
        checks.append({"item": "B6 位次覆盖率", "required": "≥50%",
                       "actual": f"{ranked / ga.valid_count * 100:.1f}%",
                       "pass": ranked / ga.valid_count >= 0.5})
        checks.append({"item": "B6 覆盖院校数", "required": "≥500",
                       "actual": len(schools), "pass": len(schools) >= 500})

    # 7. 选科要求（B4）覆盖
    sr = stats.get("subject_requirement")
    if sr:
        checks.append({"item": "B4 选科要求覆盖院校", "required": "≥500",
                       "actual": len({r.get("school_name") for r in sr.valid}),
                       "pass": len({r.get("school_name") for r in sr.valid}) >= 500})

    # 8. 院校画像（B8）：985/211 数量应接近全国真值（985≈39 / 211≈116）
    sp = stats.get("school_profile")
    if sp and sp.valid:
        n985 = sum(1 for r in sp.valid if r.get("is_985"))
        n211 = sum(1 for r in sp.valid if r.get("is_211"))
        checks.append({"item": "B8 985 院校数（eol口径含分校）", "required": "45-55",
                       "actual": n985, "pass": 45 <= n985 <= 55})
        checks.append({"item": "B8 211 院校数（eol口径含分校）", "required": "125-140",
                       "actual": n211, "pass": 125 <= n211 <= 140})

    # 9. 征集志愿（B7）覆盖批次
    sup = stats.get("supplement")
    if sup and sup.valid:
        batches = {r.get("batch") for r in sup.valid}
        checks.append({"item": "B7 征集志愿批次覆盖", "required": "≥1 个批次",
                       "actual": f"{len(batches)} 个（{','.join(sorted(b for b in batches if b))}）",
                       "pass": len(batches) >= 1})

    passed = sum(1 for c in checks if c["pass"])
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "province": config.PROVINCE,
        "summary": {"total_valid": total_valid, "total_rejected": total_rej,
                    "doc_types": len(stats), "checks_passed": passed,
                    "checks_total": len(checks),
                    "accuracy_rate": f"{passed / len(checks) * 100:.1f}%" if checks else "N/A"},
        "by_doc_type": {dt: {"valid": cr.valid_count, "rejected": cr.rejected_count}
                        for dt, cr in stats.items()},
        "checks": checks,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "validation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    rejects = [r for cr in stats.values() for r in cr.rejected]
    (OUTPUT_DIR / "reject_report.json").write_text(
        json.dumps(rejects, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


# ---------------------------------------------------------------------------
# 辅助子命令
# ---------------------------------------------------------------------------
def print_fieldmap() -> None:
    for m in config.FIELD_MAP:
        print(f"\n[{m['module']}] {m['title']}  →  doc_type: {m['doc_type']}")
        print(f"  来源 : {m['source']}")
        urls = m["urls"] if isinstance(m["urls"], list) else [m["urls"]]
        print(f"  URL  : {', '.join(str(u) for u in urls[:3])}{' …' if len(urls) > 3 else ''}")
        print(f"  解析 : {m['parse']}")
        print("  字段 :")
        for f in m["fields"]:
            print(f"    - {f['name']:18s} {f['desc']:24s} ← {f['selector']}")


def export_seeds() -> None:
    config.SEED_DIR.mkdir(parents=True, exist_ok=True)
    (config.SEED_DIR / "jiangxi_pathway_regions.json").write_text(
        json.dumps(seeds.PATHWAY_REGION_SEEDS, ensure_ascii=False, indent=2), encoding="utf-8")
    (config.SEED_DIR / "jiangxi_pathway_eligibility.json").write_text(
        json.dumps(seeds.PATHWAY_ELIGIBILITY_SEEDS, ensure_ascii=False, indent=2), encoding="utf-8")
    (config.SEED_DIR / "jiangxi_benchmarks.json").write_text(
        json.dumps(seeds.BENCHMARKS, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"种子已导出 → {config.SEED_DIR}")


def selftest() -> int:
    print("=" * 60)
    print("江西采集 · 离线自检")
    print("=" * 60)
    failed = 0

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal failed
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {detail}")
        if not cond:
            failed += 1

    # 1. 模块导入
    try:
        import data.jiangxi  # noqa: F401
        check("模块导入", True)
    except Exception as e:  # noqa: BLE001
        check("模块导入", False, str(e))

    # 2. 种子县数口径
    cnt = seeds.region_counts()
    for pw, expected in seeds.EXPECTED_REGION_COUNTS.items():
        check(f"{pw} 县数 = {expected}", cnt.get(pw, 0) == expected, f"实际 {cnt.get(pw, 0)}")

    # 3. 分数单元格解析
    cases = {"681及以上": (681, 750), "665~750": (665, 750), "448(本科线)": (448, 448), "550": (550, 550)}
    for raw, exp in cases.items():
        check(f"parse_score_cell('{raw}')", __import__("data.jiangxi.parsers", fromlist=["x"]).parse_score_cell(raw) == exp)

    # 4. 正文解析器
    from data.jiangxi import parsers as P
    rows = collectors.parse_batch_lines_from_text("历史类本科线463、物理类本科线448。特招线历史类532。", 2024)
    check("批次线正文解析", len(rows) >= 3, f"{len(rows)} 条")
    st = collectors.parse_stat_from_text("高考报名总人数为64.63万名，实际参加6月统考考生56.71万名。", 2025)
    check("报名统计解析", st.get("total_registered") == 646300, str(st))
    sc = collectors.parse_schedule_from_text("第一次集中填报，时间为6月26日9:00—27日17:00。", 2025)
    check("日程解析", bool(sc) and "6月26日" in sc[0]["start_time"], str(sc))

    # 5. 科类/批次归一
    check("科类归一 文史类→文科", config.normalize_subject("文史类") == "文科")
    check("科类归一 理工类→理科", config.normalize_subject("理工类") == "理科")
    check("批次归一 普通本科批→本科批", config.normalize_batch("普通本科批") == "本科批")

    # 6. 清洗器拒收缺来源行
    bad = validators.Record(data={"province": "江西", "year": 2024, "batch": "本科批",
                                  "subject_type": "物理类", "score": 448},
                            source_name="", source_url="", year=2024, doc_type="batch_score_line")
    check("清洗器拒收缺来源", validators.clean([bad]).rejected_count == 1)

    # 7. 去重
    same = [validators.Record(data={"province": "江西", "year": 2024, "batch": "本科批",
                                    "subject_type": "物理类", "score": 448},
                              source_name="X", source_url="http://x", year=2024,
                              doc_type="batch_score_line")] * 2
    check("业务主键去重", validators.clean(same).valid_count == 1)

    print("-" * 60)
    print(f"  结果：{'全部通过' if failed == 0 else f'{failed} 项失败'}")
    print("=" * 60)
    return 1 if failed else 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="智选志愿 · 江西高考数据采集")
    ap.add_argument("--only", default=None, help="仅运行指定模块（逗号分隔）")
    ap.add_argument("--offline", action="store_true", help="不联网，使用种子/基准值")
    ap.add_argument("--limit", type=int, default=None, help="限制抽样数量（school/charter）")
    ap.add_argument("--sleep", type=float, default=None,
                    help="覆盖单站请求间隔秒数（默认 2.0；长任务可调低，如 0.6）")
    ap.add_argument("--fieldmap", action="store_true", help="打印字段→来源→URL→解析方式")
    ap.add_argument("--export-seeds", action="store_true", help="导出种子为 JSON")
    ap.add_argument("--selftest", action="store_true", help="离线自检")
    args = ap.parse_args()

    if args.fieldmap:
        print_fieldmap()
        return
    if args.export_seeds:
        export_seeds()
        return
    if args.selftest:
        sys.exit(selftest())

    only = [g.strip() for g in args.only.split(",")] if args.only else None
    logger.info("===== 江西高考数据采集启动（offline=%s）=====", args.offline)
    stats, report = run(only=only, offline=args.offline, limit=args.limit, sleep=args.sleep)

    print("\n" + "=" * 60)
    print("采集结果摘要")
    print("=" * 60)
    for dt, cr in sorted(stats.items()):
        print(f"  {dt:22s} 有效={cr.valid_count:6d}  拒收={cr.rejected_count:4d}")
    print("-" * 60)
    print(f"  校验项通过: {report['summary']['checks_passed']}/{report['summary']['checks_total']}"
          f"  准确率: {report['summary']['accuracy_rate']}")
    print(f"  输出目录  : {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
