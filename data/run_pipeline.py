"""
智选志愿 · 河南高考数据采集主流水线。

用法：
    cd data
    python run_pipeline.py            # 全量采集
    python run_pipeline.py --segment  # 仅采集一分一段

输出（data/output/）：
    score_segment.json / .csv
    school.json / .csv
    school_major_score.json / .csv
    pathway.json / .csv
    pathway_region.json / .csv
    major.json / .csv
    validation_report.json
    reject_report.json
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# 确保可从 data/ 目录直接运行
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.collectors import base
from data.collectors.c_segment import collect_all as collect_segment
from data.collectors.c_school import collect_schools
from data.collectors.c_admission import collect_all as collect_admission
from data.collectors.c_region import collect_regions
from data.collectors.c_pathway import collect_pathways, collect_majors
from data.collectors.c_line import collect_all as collect_line
from data.collectors.c_batch_line import collect_all as collect_batch_line
from data.collectors.c_policy_doc import collect_all as collect_policy
from data.collectors.c_eligibility import collect_all as collect_eligibility
from data.collectors.c_zhangcheng import collect_all as collect_zhangcheng
from data.collectors.c_profile import collect_all as collect_profile
from data.collectors.c_pathway_score import collect_all as collect_pathway_score
from data.collectors.c_discipline import collect_all as collect_discipline
from data.collectors.c_life import collect_all as collect_life
from data.collectors.c_plan import collect_all as collect_plan
from data.cleaners.normalize import clean_records, CleanResult

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")


# ---------------------------------------------------------------------------
# 采集
# ---------------------------------------------------------------------------
# 采集器分组：一组对应一个 --only 选项；组内顺序决定去重优先级（先到先得）
COLLECTOR_GROUPS = {
    "segment":     [collect_segment],
    "school":      [collect_schools],
    "admission":   [collect_admission, collect_plan],
    "region":      [collect_regions],
    "pathway":     [collect_pathways, collect_majors],
    "eligibility": [collect_eligibility],
    "profile":     [collect_profile],
    # D-4 专项计划录取分（国家/地方/高校专项，按院校专业组）
    "pathway_score": [collect_pathway_score],
    # D-9 学科评估（第四轮公开汇总 + 在线增量）
    "discipline": [collect_discipline],
    # D-11 生活信息（院校简介中的宿舍/食堂/交通/校区段落）
    "life": [collect_life],
    # 注：D-10 招生计划数（collect_plan）与 D-2 录取分同产 school_major_score
    #     doc_type，必须并入 admission 组同一次运行，否则单独跑会把另一方覆盖为空。
    # 批次线：政府公告静态正文为主来源（可解析），平台结构化表为兜底/交叉验证
    "batch":       [collect_batch_line, collect_line],
    "policy":      [collect_policy],
    "zhangcheng":  [collect_zhangcheng],
}
DEFAULT_ORDER = ["segment", "school", "admission", "region", "pathway",
                 "eligibility", "profile", "pathway_score", "discipline",
                 "life", "batch",
                 "policy", "zhangcheng"]


def run_collectors(only: str | None, batch_no: str,
                   limit: int | None = None) -> dict[str, list]:
    """运行采集器，返回 {doc_type: RawRecord[]}。

    多产出采集器（batch/policy/zhangcheng 同时产出 knowledge_doc 等）
    只调用一次，按每条记录自身的 doc_type 归档。
    only 支持逗号分隔的多个分组，如 "batch,policy,eligibility"。
    limit 仅作用于支持该参数的采集器（admission/profile/zhangcheng），用于抽样。
    """
    if only:
        groups = [g.strip() for g in only.split(",") if g.strip()]
        invalid = [g for g in groups if g not in COLLECTOR_GROUPS]
        if invalid:
            raise SystemExit(f"--only 含未知分组：{invalid}；可选 {list(COLLECTOR_GROUPS)}")
    else:
        groups = DEFAULT_ORDER

    funcs: list = []
    for g in groups:
        funcs.extend(COLLECTOR_GROUPS[g])

    results: dict[str, list] = defaultdict(list)
    for fn in funcs:
        name = getattr(fn, "__name__", str(fn))
        logger.info("===== collecting: %s =====", name)
        t0 = time.time()
        try:
            recs = _invoke(fn, batch_no, limit)
            for r in recs:
                results[r.doc_type].append(r)
            logger.info("  %s: %d records in %.1fs", name, len(recs), time.time() - t0)
        except Exception as e:                          # noqa: BLE001
            logger.exception("collector %s failed: %s", name, e)
    return dict(results)


def _invoke(fn, batch_no: str, limit: int | None):
    """按采集器签名决定是否传入 limit。"""
    import inspect
    if limit is not None and "limit" in inspect.signature(fn).parameters:
        return fn(batch_no, limit=limit)
    return fn(batch_no)


# ---------------------------------------------------------------------------
# 清洗
# ---------------------------------------------------------------------------
def run_clean(all_records: dict[str, list]) -> dict[str, CleanResult]:
    """对每个 doc_type 分别清洗。"""
    cleaned: dict[str, CleanResult] = {}
    for doc_type, recs in all_records.items():
        logger.info("===== cleaning: %s (%d) =====", doc_type, len(recs))
        cleaned[doc_type] = clean_records(recs)
    return cleaned


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------
def write_outputs(cleaned: dict[str, CleanResult]) -> dict[str, dict]:
    """写出 JSON + CSV，返回统计。"""
    stats: dict[str, dict] = {}
    all_valid: list[dict] = []
    all_rejected: list[dict] = []

    for doc_type, cr in cleaned.items():
        rows = cr.valid
        # JSON
        json_path = OUTPUT_DIR / f"{doc_type}.json"
        json_path.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # CSV（列头取所有行字段的并集，兼容不同来源字段不一致）
        csv_path = OUTPUT_DIR / f"{doc_type}.csv"
        if rows:
            keys: list[str] = []
            seen: set[str] = set()
            for r in rows:
                for k in r.keys():
                    if k not in seen:
                        seen.add(k)
                        keys.append(k)
            with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=keys, restval="")
                w.writeheader()
                w.writerows(rows)
        else:
            csv_path.write_text("", encoding="utf-8")

        stats[doc_type] = {
            "valid": len(rows),
            "rejected": cr.rejected_count,
            "json": str(json_path),
            "csv": str(csv_path),
        }
        all_valid.extend(rows)
        all_rejected.extend(cr.rejected)
        logger.info("output %s: valid=%d rejected=%d", doc_type, len(rows), cr.rejected_count)

    # 拒收报告
    (OUTPUT_DIR / "reject_report.json").write_text(
        json.dumps(all_rejected, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return stats


# ---------------------------------------------------------------------------
# 校验报告
# ---------------------------------------------------------------------------
def build_validation_report(cleaned: dict[str, CleanResult],
                            stats: dict[str, dict]) -> dict:
    """生成数据校验报告（JSON）。"""
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "province": "河南",
        "summary": {
            "total_valid": sum(cr.valid_count for cr in cleaned.values()),
            "total_rejected": sum(cr.rejected_count for cr in cleaned.values()),
            "doc_types": len(cleaned),
        },
        "by_doc_type": stats,
        "checks": [],
    }

    # 校验项
    checks = report["checks"]

    # 1. 来源三要素覆盖率（清洗后应为 100%）
    for doc_type, cr in cleaned.items():
        valid = cr.valid
        missing_src = sum(
            1 for r in valid
            if not r.get("source_name") or not r.get("source_url") or not r.get("year")
        )
        checks.append({
            "item": f"{doc_type} 来源三要素覆盖率",
            "required": "100%",
            "actual": f"{(len(valid)-missing_src)/len(valid)*100:.1f}%" if valid else "N/A",
            "pass": missing_src == 0 and len(valid) > 0,
        })

    # 2. score_segment 完整性
    seg = cleaned.get("score_segment")
    if seg and seg.valid:
        years = defaultdict(set)
        for r in seg.valid:
            years[r["year"]].add(r["subject_type"])
        expected = {2023: {"文科", "理科"}, 2024: {"文科", "理科"}, 2025: {"历史类", "物理类"}}
        complete = all(years[y] >= s for y, s in expected.items())
        checks.append({
            "item": "一分一段表年份/科类覆盖",
            "required": "2023-2024 文/理, 2025 历史/物理",
            "actual": {str(y): sorted(list(s)) for y, s in years.items()},
            "pass": complete,
        })
        # 分数范围
        scores = [r["score"] for r in seg.valid]
        checks.append({
            "item": "一分一段分数范围",
            "required": "0-750",
            "actual": f"{min(scores)}-{max(scores)}",
            "pass": 0 <= min(scores) and max(scores) <= 750,
        })
        # 位次单调性（同一科类同年，分数越高位次越小）
        mono_ok = True
        for y, subs in years.items():
            for sub in subs:
                rows = sorted(
                    [r for r in seg.valid if r["year"] == y and r["subject_type"] == sub],
                    key=lambda r: r["score"], reverse=True,
                )
                ranks = [r["cumulative_rank"] for r in rows]
                if ranks != sorted(ranks):
                    mono_ok = False
        checks.append({
            "item": "一分一段位次单调性（同分及以上累计）",
            "required": "分数降序时位次升序",
            "actual": "通过" if mono_ok else "存在异常",
            "pass": mono_ok,
        })

    # 3. school 数量
    sch = cleaned.get("school")
    if sch:
        checks.append({
            "item": "院校库数量",
            "required": "河南约 150-200 所",
            "actual": f"{sch.valid_count} 所",
            "pass": sch.valid_count >= 100,
        })
        missing_code = sum(1 for r in sch.valid if not r.get("code"))
        checks.append({
            "item": "院校代码覆盖率",
            "required": "100%",
            "actual": f"{(sch.valid_count-missing_code)/sch.valid_count*100:.1f}%" if sch.valid_count else "N/A",
            "pass": missing_code == 0,
        })

    # 4. pathway 数量
    pw = cleaned.get("pathway")
    if pw:
        checks.append({
            "item": "途径字典数量",
            "required": "26 类",
            "actual": f"{pw.valid_count} 类",
            "pass": pw.valid_count == 26,
        })

    # 5. pathway_region 数量
    pr = cleaned.get("pathway_region")
    if pr:
        by_pathway = defaultdict(int)
        for r in pr.valid:
            by_pathway[r["pathway_name"]] += 1
        checks.append({
            "item": "专项县名单覆盖",
            "required": "国家专项38县/高校专项53县（地方专项=全省农村，无县名单）",
            "actual": dict(by_pathway),
            "pass": (by_pathway.get("国家专项计划", 0) == 38
                     and by_pathway.get("高校专项计划", 0) == 53),
        })

    # 6. batch_score_line 三年覆盖
    bl = cleaned.get("batch_score_line")
    if bl and bl.valid:
        by_year = defaultdict(set)
        for r in bl.valid:
            by_year[r["year"]].add(r["subject_type"])
        checks.append({
            "item": "批次控制线年份覆盖",
            "required": "2023/2024/2025 三年",
            "actual": {str(y): sorted(s) for y, s in sorted(by_year.items())},
            "pass": set(by_year) >= {2023, 2024, 2025},
        })

    # 7. knowledge_doc 数量
    kd = cleaned.get("knowledge_doc")
    if kd:
        by_type = defaultdict(int)
        for r in kd.valid:
            by_type[r.get("doc_category") or r.get("doc_type", "?")] += 1
        checks.append({
            "item": "知识库文档（政策/分数线/章程）",
            "required": ">=6 篇",
            "actual": dict(by_type),
            "pass": kd.valid_count >= 6,
        })

    # 8. 录取分覆盖（2025 专业组级）
    sms = cleaned.get("school_major_score")
    if sms and sms.valid:
        y2025 = [r for r in sms.valid if r["year"] == 2025 and r.get("group_code")]
        schools_2025 = len({r.get("school_code") or r.get("school_name") for r in y2025})
        checks.append({
            "item": "录取分 2025 专业组级覆盖",
            "required": ">=30 校（含 group_code）",
            "actual": f"{schools_2025} 校 / {len(y2025)} 条",
            "pass": schools_2025 >= 30,
        })

    # 9. 章程覆盖
    er = cleaned.get("enrollment_rule")
    if er:
        schools = len({r.get("school_name") for r in er.valid})
        checks.append({
            "item": "招生章程覆盖",
            "required": ">=20 校",
            "actual": f"{schools} 校 / {er.valid_count} 条",
            "pass": schools >= 20,
        })

    # 10. 专项计划录取分覆盖（D-4）
    ps = cleaned.get("pathway_score")
    if ps and ps.valid:
        pathways = sorted({r.get("pathway_name") for r in ps.valid})
        schools = len({r.get("school_name") for r in ps.valid})
        with_group = sum(1 for r in ps.valid if r.get("group_code"))
        checks.append({
            "item": "专项计划录取分覆盖（D-4）",
            "required": "国家/地方专项各≥1 校，含院校专业组",
            "actual": f"{schools} 校 / {ps.valid_count} 条 / 专项组 {with_group} 条 / {pathways}",
            "pass": schools >= 2 and "国家专项计划" in pathways
                    and "地方专项计划" in pathways,
        })

    # 11. 学科评估覆盖（D-9）
    de = cleaned.get("discipline_eval")
    if de and de.valid:
        schools = len({r.get("school_name") for r in de.valid})
        grades = sorted({r.get("grade") for r in de.valid if r.get("grade")})
        checks.append({
            "item": "学科评估覆盖（D-9）",
            "required": ">=5 校且含等级",
            "actual": f"{schools} 校 / {de.valid_count} 条 / 等级 {grades[:6]}",
            "pass": schools >= 5 and len(grades) >= 2,
        })

    # 12. 招生计划数覆盖（D-10）
    sms_plan = cleaned.get("school_major_score")
    if sms_plan and sms_plan.valid:
        with_plan = [r for r in sms_plan.valid if r.get("plan_count")]
        schools = len({r.get("school_name") for r in with_plan})
        checks.append({
            "item": "招生计划数覆盖（D-10）",
            "required": ">=30 校含 plan_count",
            "actual": f"{schools} 校 / {len(with_plan)} 条",
            "pass": schools >= 30,
        })

    # 13. 生活信息覆盖（D-11）
    sl = cleaned.get("school_life")
    if sl and sl.valid:
        schools = len({r.get("school_name") for r in sl.valid})
        cats = sorted({r.get("category") for r in sl.valid if r.get("category")})
        checks.append({
            "item": "生活信息覆盖（D-11）",
            "required": ">=3 校且含宿舍/食堂/交通等类别",
            "actual": f"{schools} 校 / {sl.valid_count} 条 / {cats}",
            "pass": schools >= 3 and len(cats) >= 1,
        })

    # 总体通过率
    passed = sum(1 for c in checks if c["pass"])
    report["summary"]["checks_passed"] = passed
    report["summary"]["checks_total"] = len(checks)
    report["summary"]["accuracy_rate"] = f"{passed/len(checks)*100:.1f}%" if checks else "N/A"
    return report


# ---------------------------------------------------------------------------
# 从既有产出加载（离线，不联网）
# ---------------------------------------------------------------------------
SKIP_JSON = {"validation_report.json", "reject_report.json", "load_report.json"}


def load_output_as_cleaned() -> dict[str, CleanResult]:
    """把 data/output/*.json 重新读入并清洗，返回 {doc_type: CleanResult}。

    用于「不重新联网采集，直接把已产出的数据入库/复算校验」。
    """
    cleaned: dict[str, CleanResult] = {}
    for jf in sorted(OUTPUT_DIR.glob("*.json")):
        if jf.name in SKIP_JSON:
            continue
        try:
            rows = json.loads(jf.read_text(encoding="utf-8"))
        except Exception as e:                          # noqa: BLE001
            logger.warning("读取 %s 失败：%s", jf.name, e)
            continue
        if not isinstance(rows, list):
            continue
        recs = [
            base.RawRecord(
                # 注意：year 必须保留在 data 内（部分校验器读 data["year"]）
                data={k: v for k, v in r.items()
                      if k not in ("source_name", "source_url", "doc_type")},
                source_name=r.get("source_name", ""),
                source_url=r.get("source_url", ""),
                year=int(r.get("year") or 0),
                doc_type=r.get("doc_type") or jf.stem,
            )
            for r in rows
        ]
        cleaned[jf.stem] = clean_records(recs)
    logger.info("从 output/ 载入 %d 个 doc_type", len(cleaned))
    return cleaned


def stats_of(cleaned: dict[str, CleanResult]) -> dict[str, dict]:
    return {
        dt: {"valid": cr.valid_count, "rejected": cr.rejected_count}
        for dt, cr in cleaned.items()
    }


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="智选志愿 · 河南数据采集流水线")
    parser.add_argument("--only", default=None,
                        help="仅运行指定采集器（可逗号分隔多个，如 batch,policy,eligibility）")
    parser.add_argument("--limit", type=int, default=None,
                        help="对支持抽样的采集器（admission/profile/zhangcheng）限制院校数")
    parser.add_argument("--load-db", action="store_true",
                        help="清洗后写入 PostgreSQL（需先执行 db/schema.sql 建表）")
    parser.add_argument("--from-output", action="store_true",
                        help="跳过联网采集，直接读 data/output/*.json 入库/复算校验")
    parser.add_argument("--dsn", default=None,
                        help="数据库连接串，默认 postgresql://postgres:postgres@localhost:5432/zhixuan")
    args = parser.parse_args()

    logger.info("===== 智选志愿 · 河南高考数据采集启动 =====")
    t_start = time.time()
    batch_no = base.now_batch("henan")

    if args.from_output:
        # 1'. 从既有产出载入（离线）
        cleaned = load_output_as_cleaned()
        stats = stats_of(cleaned)
    else:
        # 1. 采集
        raw = run_collectors(only=args.only, batch_no=batch_no, limit=args.limit)
        # 2. 清洗
        cleaned = run_clean(raw)
        # 3. 输出
        stats = write_outputs(cleaned)

    # 4. 校验报告
    report = build_validation_report(cleaned, stats)
    report_path = OUTPUT_DIR / "validation_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    elapsed = time.time() - t_start
    logger.info("===== 采集完成，耗时 %.1fs =====", elapsed)
    logger.info("校验报告: %s", report_path)
    logger.info("数据目录: %s", OUTPUT_DIR)

    # 5. 可选：写入数据库
    if args.load_db:
        from data.loaders import pg
        dsn = args.dsn or pg.DEFAULT_DSN
        logger.info("===== 写入数据库：%s =====", dsn)
        try:
            load_stats = pg.load_all(cleaned, dsn=dsn, batch_no=batch_no)
            logger.info("入库完成：成功 %d，失败 %d", load_stats["loaded"], load_stats["failed"])
            (OUTPUT_DIR / "load_report.json").write_text(
                json.dumps(load_stats, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:                    # noqa: BLE001
            logger.error("写入数据库失败（可只用 JSON/CSV 输出）：%s", e)

    # 打印摘要
    print("\n" + "=" * 60)
    print("采集结果摘要")
    print("=" * 60)
    for dt, s in stats.items():
        print(f"  {dt:25s} 有效={s['valid']:6d}  拒收={s['rejected']:4d}")
    print("-" * 60)
    print(f"  校验项通过: {report['summary']['checks_passed']}/{report['summary']['checks_total']}")
    print(f"  准确率: {report['summary']['accuracy_rate']}")
    print(f"  输出目录: {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
