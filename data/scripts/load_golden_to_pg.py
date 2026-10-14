#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Golden Layer 灌库器（③ 数据工程 · Step 2「入库」）

把 `data/staged_golden/*.jsonl` 按**外键依赖顺序**灌进 PostgreSQL。

分工说明
--------
- 「建表 / Alembic」= ② 已闭环（31 表已在库）。
- 「让库里有数据」= ③ 本脚本（MEMORY 铁律）。
- 本脚本**只 INSERT，不 DDL、不建表、不改结构**。

安全设计
--------
- **默认 dry-run**：只校验、只打印，不写库。
- `--commit` 才真正写；写前若目标表**非空**则中止（除非 `--force`），避免重复灌。
- 全程**单事务**：任一行失败 → 整体回滚。
- **不猜**：`source_id` / `school_id` / `major_id` 解析不到的行不会出现在 golden 层，
  它们已在 `_ledger.json` 里登记（转换阶段就被剔除）。

用法
----
    PY="C:/Users/lenovo/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
    "C:/Users/lenovo/.pg16/pyenv/python.exe" "C:/Users/lenovo/.pg16/pg_service.py" start   # 先起库
    "$PY" data/scripts/load_golden_to_pg.py                # dry-run
    "$PY" data/scripts/load_golden_to_pg.py --commit       # 真正灌
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "data" / "staged_golden"

DSN = os.getenv(
    "ZHIXUAN_DATABASE_URL",
    "postgresql://zhixuan:change-me@127.0.0.1:5432/zhixuan",
).replace("postgresql+psycopg://", "postgresql://")

# 表 → (插入列白名单, json 列, 是否显式给 id)
SPEC: dict[str, tuple[tuple[str, ...], tuple[str, ...], bool]] = {
    "source": (("id", "source_name", "source_url", "year", "source_type", "fetched_at"), (), True),
    "school": (("id", "name", "code", "province", "city", "level", "type",
                "ownership", "website", "intro"), (), True),
    "major": (("id", "name", "code", "category", "first_class", "degree", "tuition",
               "ownership", "duration", "campus", "is_category", "single_subject_req",
               "language_req", "gender_req", "interview_required"), (), True),
    "score_segment": (("province", "year", "subject_type", "score",
                       "cumulative_rank", "source_id"), (), False),
    "school_major_score": (("school_id", "major_id", "province", "year", "batch",
                            "pathway_id", "subject_type", "min_score", "min_rank",
                            "avg_score", "plan_count", "source_id"), (), False),
    "pathway": (("id", "name", "category", "batch", "target_group", "apply_time",
                 "description", "priority", "data_status", "year", "source_id"), (), False),
    "pathway_region": (("pathway_id", "province", "county_name", "county_code",
                        "year", "source_id"), (), False),
    "pathway_eligibility": (("pathway_id", "province", "rule_type", "rule_desc",
                             "params", "year", "source_id"), ("params",), False),
    "province_exam_rule": (("province", "year", "batch", "mode", "volunteer_count",
                            "majors_per_group", "has_adjust", "admit_method", "ratio",
                            "tie_rule", "mutex_groups", "collect_count", "source_id",
                            "province_code", "batch_code", "exam_type"), ("mutex_groups",), False),
    "enrollment_rule": (("school_id", "year", "content", "subject_req", "health_req",
                         "foreign_lang_req", "source_id"), (), False),
    "school_profile": (("school_id", "tuition_range", "accommodation_fee", "campus_list",
                        "established_year", "master_phd_points", "first_class_major_count",
                        "faculty_count", "student_faculty_ratio", "source_id"),
                       ("campus_list", "master_phd_points"), False),
    "school_life": (("school_id", "category", "content", "source_type", "source_name",
                     "source_url", "year", "reliability"), (), False),
}
ORDER = list(SPEC)


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="真正写库（默认 dry-run）")
    ap.add_argument("--force", action="store_true", help="目标表非空时也继续")
    ap.add_argument("--truncate", action="store_true",
                    help="灌前先清空这 12 张表（⚠ 破坏性；仅用于可重跑的试点库重灌）")
    args = ap.parse_args()

    try:
        import psycopg
    except ImportError:
        print("✗ 缺少 psycopg。请先："
              'pip install --no-index --find-links=C:/Users/lenovo/.pg16/_wheels "psycopg[binary]"')
        return 2

    print(f"DSN: {DSN.replace('change-me', '***')}")
    print(f"Golden: {GOLDEN}\n")

    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            # 0) 前置检查
            nonempty = []
            for t in ORDER:
                cur.execute(f'select count(*) from "{t}"')
                n = cur.fetchone()[0]
                if n:
                    nonempty.append((t, n))
            if args.truncate and args.commit:
                print("⚠ --truncate：将清空以下 12 张表后重灌（破坏性，仅限可重跑的试点库）")
                cur.execute('TRUNCATE TABLE ' + ", ".join(f'"{t}"' for t in ORDER)
                            + " RESTART IDENTITY CASCADE")
                nonempty = []
            if nonempty:
                print("⚠ 目标表已有数据：")
                for t, n in nonempty:
                    print(f"    {t:22s} {n}")
                if not args.force:
                    print("\n✗ 中止（避免重复灌）。确认覆盖请加 --truncate（清空重灌）")
                    return 3

            # 1) 逐表插入
            total = 0
            for t in ORDER:
                cols, json_cols, has_id = SPEC[t]
                recs = read_jsonl(GOLDEN / f"{t}.jsonl")
                if not recs:
                    print(f"  {t:22s}      0 行（跳过）")
                    continue
                placeholders = ", ".join(["%s"] * len(cols))
                # created_at / updated_at 在库里 NOT NULL 且无默认值 ⇒ 统一补 now()
                all_cols = tuple(cols) + ("created_at", "updated_at")
                sql = (f'INSERT INTO "{t}" ({", ".join(f""" "{c}" """ for c in all_cols)}) '
                       f"VALUES ({placeholders}, now(), now())")
                rows = []
                for r in recs:
                    vals = []
                    for c in cols:
                        v = r.get(c)
                        if c in json_cols and v is not None and not isinstance(v, str):
                            v = json.dumps(v, ensure_ascii=False)
                        elif c in json_cols and v is None:
                            v = "[]" if c == "mutex_groups" else "null"
                        vals.append(v)
                    rows.append(tuple(vals))
                if args.commit:
                    cur.executemany(sql, rows)
                print(f"  {t:22s} {len(rows):>7} 行{'  [已写]' if args.commit else '  [dry-run]'}")
                total += len(rows)

            # 2) 显式 id 的表 → 推进序列
            if args.commit:
                for t in ORDER:
                    if SPEC[t][2]:
                        cur.execute(
                            f"select setval(pg_get_serial_sequence('{t}','id'), "
                            f"coalesce((select max(id) from \"{t}\"), 1))")
                conn.commit()

            # 3) 结果核对
            print(f"\n合计 {total} 行{'（已提交）' if args.commit else '（dry-run，未写）'}")
            if args.commit:
                print("\n=== 库内实际行数 ===")
                for t in ORDER:
                    cur.execute(f'select count(*) from "{t}"')
                    print(f"  {t:22s} {cur.fetchone()[0]:>7}")
                # 外键抽样校验（FK 是否悬空）
                print("\n=== 外键悬空检查 ===")
                checks = [
                    ("school_major_score.school_id", 'select count(*) from school_major_score s '
                     'left join school o on o.id=s.school_id where o.id is null'),
                    ("school_major_score.major_id", 'select count(*) from school_major_score s '
                     'left join major m on m.id=s.major_id where m.id is null'),
                    ("score_segment.source_id", 'select count(*) from score_segment s '
                     'left join source o on o.id=s.source_id where o.id is null'),
                    ("pathway_region.source_id", 'select count(*) from pathway_region s '
                     'left join source o on o.id=s.source_id where o.id is null'),
                ]
                for label, q in checks:
                    cur.execute(q)
                    n = cur.fetchone()[0]
                    print(f"  {label:32s} 悬空 {n}")
        if not args.commit:
            conn.rollback()
    return 0


if __name__ == "__main__":
    sys.exit(main())
