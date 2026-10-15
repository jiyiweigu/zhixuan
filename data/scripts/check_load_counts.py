"""装载对账：逐表比对数据库行数，并核对两类「悬空外键」。

用法：
    python data/scripts/check_load_counts.py backend/.runtime/zhixuan.db

期望值基线来自 2026-10-15 全量装载验收（见 docs/装载验收报告_20261015.md）；
合并数据集更新后应先刷新本表再对账。

悬空外键（指向不存在行）必须为 0：合并侧已按「宁可缺、不可猜」把院校库/专业库外
的引用置 NULL 并如实计数——非 NULL 的外键就应当必然命中，这是可复跑验收的核心断言。
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

# 表 -> 期望行数（2026-10-15 全量装载验收基线；口径为「实际入库数」）
# pathway_eligibility：数据 11 行，其中 1 行 general-batch 引用缺失按红线跳过 → 入库 10
EXPECTED: dict[str, int] = {
    "source": 291,
    "pathway": 26,
    "pathway_region": 91,
    "pathway_eligibility": 10,
    "province_exam_rule": 7,
    "school": 1367,
    "major": 938,
    "score_segment": 11694,
    "school_major_score": 116036,
}

# 悬空外键检查：(表, 列, 被引表) —— 期望 0
DANGLING: list[tuple[str, str, str]] = [
    ("school_major_score", "school_id", "school"),
    ("school_major_score", "major_id", "major"),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="装载行数与悬空外键对账")
    parser.add_argument("db", type=Path, help="SQLite 数据库路径")
    args = parser.parse_args(argv)

    con = sqlite3.connect(args.db)
    bad = 0
    for table, expected in EXPECTED.items():
        actual = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        delta = actual - expected
        print(f"{'OK ' if delta == 0 else '★  '}{table}: expected={expected} actual={actual} delta={delta}")
        if delta != 0:
            bad += 1

    for table, col, ref in DANGLING:
        dangling = con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {col} IS NOT NULL "
            f"AND {col} NOT IN (SELECT id FROM {ref})"
        ).fetchone()[0]
        print(f"{'OK ' if dangling == 0 else '★  '}悬空外键 {table}.{col} -> {ref}: {dangling}（期望 0）")
        if dangling:
            bad += 1

    null_school = con.execute(
        "SELECT COUNT(*) FROM school_major_score WHERE school_id IS NULL"
    ).fetchone()[0]
    null_major = con.execute(
        "SELECT COUNT(*) FROM school_major_score WHERE major_id IS NULL"
    ).fetchone()[0]
    print(
        f"\n如实留空（'宁可缺、不可猜'）：school_id NULL {null_school} 行"
        f"（院校库外/改名）、major_id NULL {null_major} 行（试验班/职业本科等）"
    )
    if bad:
        print(f"\n{bad} 项不符合预期")
        return 1
    print("\n对账全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
