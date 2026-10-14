#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""张分支数据接入 · 第一步：**先比后灌** 增量比对（只读）。

对每个 (我方表 ↔ 张产物) 组合，按**业务键**把两侧数据分成四类：

    ┌──────────────┬────────────────────────────────────────────┐
    │ 重复         │ 键相同 且 比对字段值相同                    │
    │ 冲突         │ 键相同 但 比对字段值不同  ← 必须先裁决      │
    │ 张独有       │ 张有、我方无 ← **潜在增量**（接入的价值所在）│
    │ 我方独有     │ 我方有、张无 ← 说明我方更全，张不能覆盖我方  │
    └──────────────┴────────────────────────────────────────────┘

**只读**：不写库、不改产物。结论落 JSON + 控制台摘要。

用法：
    python compare_zhang_branch.py [--zhang DIR] [--json OUT] [--dsn DSN]

约定（已实测，见 data/张分支数据接入规范_徐.md §3）：
  · 院校码 / 专业码两侧均为**国标码**，可直接 join
  · 我方 `pathway` 主键是 VARCHAR 编码，张用 `pathway_name` ⇒ 走 R4 反查表
  · 我方 `school_major_score` 存 id ⇒ 比对时 join 回 `school.code` / `major.code`
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import psycopg
except ImportError:  # pragma: no cover
    print("需要 psycopg：pip install 'psycopg[binary]'", file=sys.stderr)
    raise

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DSN = os.getenv(
    "ZHIXUAN_DATABASE_URL",
    "postgresql://zhixuan:change-me@127.0.0.1:5432/zhixuan",
).replace("postgresql+psycopg://", "postgresql://")


# ─────────────────────────── 产物 ↔ 我方表 对照 ─────────────────────────── #
# table    : 我方表名
# files    : 张产物相对 data/ 的路径（按序合并）
# zkey     : 张侧业务键字段
# okey     : 我方侧业务键字段（SQL 别名，与 zkey 等长、一一对应）
# sql      : 我方侧取键（+比对值）的 SQL
# compare  : 需要比值的字段 {张字段: 我方字段}（值不同 → 冲突）
# note     : 阻塞/口径说明

PAIRS: list[dict] = [
    dict(
        table="school",
        files=["output/school.json", "jiangxi/output/school.json"],
        zkey=("code",), okey=("code",),
        sql="""select code, name, province, level, type, ownership
                from school where code is not null and code <> ''""",
        compare={"name": "name", "province": "province", "level": "level",
                 "type": "type", "ownership": "ownership"},
    ),
    dict(
        table="major",
        files=["output/major.json"],
        zkey=("code",), okey=("code",),
        sql="select code, name, category, first_class, degree from major where code is not null and code <> ''",
        compare={"name": "name"},
    ),
    dict(
        table="score_segment",
        files=["output/score_segment.json", "jiangxi/output/score_segment.json"],
        zkey=("province", "year", "subject_type", "score"),
        okey=("province", "year", "subject_type", "score"),
        sql="select province,year,subject_type,score,cumulative_rank from score_segment",
        compare={"cumulative_rank": "cumulative_rank"},
    ),
    dict(
        table="school_major_score",
        files=["output/school_major_score.json", "jiangxi/output/school_major_score.json"],
        zkey=("province", "year", "school_code", "major_code", "subject_type", "batch"),
        okey=("province", "year", "school_code", "major_code", "subject_type", "batch"),
        sql="""select sms.province, sms.year, s.code as school_code, m.code as major_code,
                       sms.subject_type, sms.batch, sms.min_score, sms.avg_score,
                       sms.min_rank, sms.plan_count
                from school_major_score sms
                left join school s on s.id = sms.school_id
                left join major  m on m.id = sms.major_id""",
        compare={"min_score": "min_score", "min_rank": "min_rank", "plan_count": "plan_count"},
        note="B-1/B-3/B-6c 阻塞；2024 豫赣 subject_type 整列空 ⇒ 键天然对不上",
    ),
    dict(
        table="enrollment_rule",
        files=["output/enrollment_rule.json"],
        zkey=("school_code", "year"), okey=("school_code", "year"),
        sql="""select s.code as school_code, er.year
                from enrollment_rule er join school s on s.id = er.school_id""",
        compare={},
    ),
    dict(
        table="school_profile",
        files=["output/school_profile.json", "jiangxi/output/school_profile.json"],
        zkey=("school_code",), okey=("school_code",),
        sql="""select s.code as school_code, sp.established_year, sp.faculty_count
                from school_profile sp join school s on s.id = sp.school_id""",
        compare={},
        note="我方 school_profile **无 year 列** ⇒ 键只能到 school_code",
    ),
    dict(
        table="school_life",
        files=["output/school_life.json"],
        zkey=("school_name", "category", "content"), okey=("school_name", "category", "content"),
        sql="""select s.name as school_name, sl.category, sl.content
                from school_life sl join school s on s.id = sl.school_id""",
        compare={},
        note="我方 reliability 全为 'official'，张为 high/medium/low ⇒ 枚举需收敛（R2）",
    ),
    dict(
        table="pathway",
        files=["output/pathway.json", "jiangxi/output/pathway.json"],
        zkey=("name",), okey=("name",),
        sql="select name from pathway",
        compare={},
    ),
    dict(
        table="pathway_eligibility",
        files=["output/pathway_eligibility.json", "jiangxi/output/pathway_eligibility.json"],
        zkey=("province", "pathway_name", "rule_type"),
        okey=("province", "pathway_name", "rule_type"),
        sql="""select pe.province, p.name as pathway_name, pe.rule_type
                from pathway_eligibility pe join pathway p on p.id = pe.pathway_id""",
        compare={},
        note="张用 pathway_name ⇒ 需 R4 映射（未命中显式报错）",
    ),
    dict(
        table="pathway_region",
        files=["output/pathway_region.json", "jiangxi/output/pathway_region.json"],
        zkey=("province", "pathway_name", "county_name"),
        okey=("province", "pathway_name", "county_name"),
        sql="""select pr.province, p.name as pathway_name, pr.county_name
                from pathway_region pr join pathway p on p.id = pr.pathway_id""",
        compare={},
        note="我方仅河南 91 条；张江西 137 条含「苏区专项计划」⇒ 字典未命中",
    ),
    dict(
        table="subject_requirement",
        files=["jiangxi/output/subject_requirement.json"],
        zkey=("school_name", "group_name", "year"), okey=("school_name", "group_name", "year"),
        sql="""select s.name as school_name, sr.group_code as group_name, sr.year
                from subject_requirement sr left join school s on s.id = sr.school_id""",
        compare={},
        note="我方空表 ⇒ 张全部为潜在增量；键需 R1（school_name→id）",
    ),
    dict(
        table="discipline_eval",
        files=["output/discipline_eval.json"],
        zkey=("school_name", "discipline_name", "round"),
        okey=("school_name", "discipline_name", "round"),
        sql="""select s.name as school_name, de.discipline_name, de.round
                from discipline_eval de join school s on s.id = de.school_id""",
        compare={},
        note="我方空表；但 grade NOT NULL 而张 389/409 无 grade ⇒ N26 待裁",
    ),
    dict(
        table="knowledge_doc",
        files=["output/knowledge_doc.json", "jiangxi/output/knowledge_doc.json"],
        zkey=("title",), okey=("title",),
        sql="select title from knowledge_doc",
        compare={},
        note="我方空表；接入范围待 ④/② 定",
    ),
    dict(
        table="pathway_score",
        files=["output/pathway_score.json"],
        zkey=("province", "year", "school_code", "pathway_name"),
        okey=("province", "year", "school_code", "pathway_name"),
        sql="""select ps.province, ps.year, s.code as school_code, p.name as pathway_name
                from pathway_score ps
                join school s on s.id = ps.school_id
                join pathway p on p.id = ps.pathway_id""",
        compare={},
        note="我方空表；但 major_id 语义错位 ⇒ 同 school_major_score 阻塞",
    ),
]

# 我方表按产物的 canonical 名字（用于「我方无对应表」的判断）
OUR_TABLES = {
    "school", "major", "score_segment", "school_major_score", "enrollment_rule",
    "school_profile", "school_life", "pathway", "pathway_eligibility",
    "pathway_region", "subject_requirement", "discipline_eval", "knowledge_doc",
    "knowledge_chunk", "pathway_score", "source", "province_exam_rule",
}

# 张有、我方**无对应表**（结构缺口）
NO_TABLE = {
    "output/batch_score_line.json": "批次控制线（B-5/N14 已登记缺口）",
    "jiangxi/output/batch_score_line.json": "批次控制线（同上）",
    "jiangxi/output/province_stat.json": "报名/实考/录取人数（非志愿必需）",
    "jiangxi/output/schedule.json": "志愿填报时间安排",
    "jiangxi/output/group_admission.json": "院校专业组投档线（我方无组级维度）",
    "jiangxi/output/school_plan.json": "招生计划（我方仅河南，且无对应表）",
    "jiangxi/output/supplement.json": "征集志愿（同上）",
    "output/pathway_time.json": "途径时间（我方 pathway.apply_time 已有字段）",
    "jiangxi/output/reject_report.json": "张自身流水线拒收记录（非数据）",
    "output/load_report.json": "张自身入库报告（非数据）",
}

SKIP = {
    "output/reject_report.json", "output/validation_report.json",
    "jiangxi/output/reject_report.json", "jiangxi/output/validation_report.json",
    "output/load_report.json", "output/数据校验报告.md",
    "output/subject_requirement.json",  # 不存在，防呆
}


def load_zrows(base: Path, files: list[str]) -> tuple[list[dict], list[dict]]:
    """读取张产物（按序合并），返回 (记录列表, 每文件条数)。"""
    rows: list[dict] = []
    per: list[dict] = []
    for rel in files:
        p = base / "data" / rel
        if not p.exists():
            per.append({"file": rel, "n": 0, "missing": True})
            continue
        doc = json.loads(p.read_text(encoding="utf-8"))
        recs = doc if isinstance(doc, list) else next(
            (v for v in doc.values() if isinstance(v, list)), [])
        per.append({"file": rel, "n": len(recs), "missing": False})
        rows.extend(recs)
    return rows, per


def zkey_of(row: dict, fields: tuple[str, ...]) -> tuple:
    out = []
    for f in fields:
        v = row.get(f)
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        out.append("" if v is None else str(v).strip())
    return tuple(out)


def norm(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zhang", default=r"C:/Users/lenovo/.pg16/zhang_data",
                    help="张分支导出的根目录（其下有 data/）")
    ap.add_argument("--json", default="", help="比对结果 JSON 落盘路径")
    ap.add_argument("--dsn", default=DEFAULT_DSN)
    args = ap.parse_args()

    base = Path(args.zhang)
    if not (base / "data").is_dir():
        print(f"✗ 找不到 {base / 'data'}", file=sys.stderr)
        return 2

    report: dict = {"zhang_root": str(base), "generated_from": "compare_zhang_branch.py",
                    "pairs": [], "no_table": [], "totals": {}}
    t_dup = t_conf = t_zonly = t_oonly = 0

    with psycopg.connect(args.dsn, connect_timeout=15) as conn:
        cur = conn.cursor()
        for spec in PAIRS:
            zrows, per = load_zrows(base, spec["files"])
            if not zrows and all(p["n"] == 0 for p in per):
                continue

            cur.execute(spec["sql"])
            cols = [d.name for d in cur.description]
            orows = [dict(zip(cols, r)) for r in cur.fetchall()]

            zmap: dict[tuple, dict] = {}
            for r in zrows:
                zmap.setdefault(zkey_of(r, spec["zkey"]), r)
            omap: dict[tuple, dict] = {}
            for r in orows:
                omap.setdefault(tuple(norm(r.get(k)) for k in spec["okey"]), r)

            inter = set(zmap) & set(omap)
            zonly = set(zmap) - set(omap)
            oonly = set(omap) - set(zmap)

            conf: list[dict] = []
            for k in inter:
                zr, orr = zmap[k], omap[k]
                bad = {}
                for zf, of in spec.get("compare", {}).items():
                    a, b = norm(zr.get(zf)), norm(orr.get(of))
                    if a != b:
                        bad[zf] = {"zhang": a, "ours": b}
                if bad:
                    conf.append({"key": list(k), "diff": bad})

            dup = len(inter) - len(conf)
            t_dup += dup
            t_conf += len(conf)
            t_zonly += len(zonly)
            t_oonly += len(oonly)

            rep = {
                "table": spec["table"], "files": per,
                "zhang_rows": len(zrows), "our_rows": len(orows),
                "zhang_keys": len(zmap), "our_keys": len(omap),
                "dup": dup, "conflict": len(conf),
                "zhang_only": len(zonly), "our_only": len(oonly),
                "conflict_sample": conf[:10],
                "zhang_only_sample": [list(k) for k in sorted(zonly)[:10]],
                "note": spec.get("note", ""),
            }
            report["pairs"].append(rep)

            flag = "★增量" if len(zonly) > 0 else ""
            print(f"\n▌ {spec['table']:<22} 张 {len(zrows):>6} ｜ 我方 {len(orows):>7}  {flag}")
            print(f"   键: 张 {len(zmap):>6} ｜ 我方 {len(omap):>7}  "
                  f"｜ 重复 {dup:>6} ｜ 冲突 {len(conf):>5} "
                  f"｜ 张独有 {len(zonly):>6} ｜ 我方独有 {len(oonly):>6}")
            if spec.get("note"):
                print(f"   ⚠ {spec['note']}")
            for c in conf[:5]:
                print(f"   ⚠ 冲突 {c['key']}: {json.dumps(c['diff'], ensure_ascii=False)}")
            if zonly:
                for k in sorted(zonly)[:5]:
                    print(f"   ➕ 张独有 {list(k)}")

        # 我方无对应表
        print("\n" + "=" * 74)
        print("### 张有产出、我方无对应表（结构缺口，不接入）")
        for rel, why in NO_TABLE.items():
            p = base / "data" / rel
            n = ""
            if p.exists():
                doc = json.loads(p.read_text(encoding="utf-8"))
                recs = doc if isinstance(doc, list) else next(
                    (v for v in doc.values() if isinstance(v, list)), [])
                n = f"{len(recs)} 条"
            print(f"   · {rel:<44} {n:<10} {why}")
            report["no_table"].append({"file": rel, "rows": n, "why": why})

    report["totals"] = {"dup": t_dup, "conflict": t_conf,
                        "zhang_only": t_zonly, "our_only": t_oonly}
    print("\n" + "=" * 74)
    print(f"合计：重复 {t_dup} ｜ 冲突 {t_conf} ｜ **张独有 {t_zonly}** ｜ 我方独有 {t_oonly}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已落盘 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
