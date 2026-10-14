#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""张分支数据接入 · 第三步：把 `data/staged_golden_zhang/*.jsonl` **追加**进库。

与 `load_golden_to_pg.py` 的区别（为什么不复用）：

    load_golden_to_pg.py            load_zhang_to_pg.py（本脚本）
    ───────────────────────────     ────────────────────────────────────
    我方自有产物、**一次性覆盖**     张分支增量、**追加**
    表非空即中止（防重复灌）         按**业务键幂等**去重，可反复跑
    12 表硬编码 SPEC                只接本轮 5 张表
    --truncate 清空重灌             **不提供 truncate**（只增不删）

幂等键（每次跑都按此对比库内现状，命中即跳过 ⇒ 二次执行必然 0 行）：

    source                 (source_name, source_url, year)
    pathway_region         (pathway_id, province, county_name, year)
    pathway_eligibility    (pathway_id, province, rule_type, year)
    enrollment_rule        (school.code, year)      ← 我方 school 存在同 code 多行
    subject_requirement    (province, year, school_id, group_code, first_subject,
                            secondary_subjects::text, logic)

用法：
    python load_zhang_to_pg.py              # dry-run，只报将写入多少行
    python load_zhang_to_pg.py --commit     # 真正写库（单事务）
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
STAGED = ROOT / "data" / "staged_golden_zhang"
DEFAULT_DSN = os.getenv(
    "ZHIXUAN_DATABASE_URL",
    "postgresql://zhixuan:change-me@127.0.0.1:5432/zhixuan",
).replace("postgresql+psycopg://", "postgresql://")

# 表 → (插入列, json 列, 是否显式给 id)
SPEC: dict[str, tuple[tuple[str, ...], tuple[str, ...], bool]] = {
    "source": (("id", "source_name", "source_url", "year", "source_type", "fetched_at"),
               (), True),
    "pathway_region": (("pathway_id", "province", "county_name", "county_code",
                        "year", "source_id"), (), False),
    "pathway_eligibility": (("pathway_id", "province", "rule_type", "rule_desc",
                             "params", "year", "source_id"), ("params",), False),
    "enrollment_rule": (("school_id", "year", "content", "subject_req", "health_req",
                         "foreign_lang_req", "source_id"), (), False),
    "subject_requirement": (("province", "province_code", "year", "batch", "school_id",
                             "group_code", "major_id", "first_subject",
                             "secondary_subjects", "logic", "source_id"),
                            ("secondary_subjects",), False),
}

ORDER = list(SPEC)          # source 必须第一（其余表 source_id 依赖它）

# 幂等键：库内取键的 SQL + 键列名（顺序与 zkey 一致）
KEYSQL: dict[str, str] = {
    "source": "select source_name, source_url, year from source",
    "pathway_region": "select pathway_id, province, county_name, year from pathway_region",
    "pathway_eligibility": "select pathway_id, province, rule_type, year from pathway_eligibility",
    "enrollment_rule": ("select s.code, er.year from enrollment_rule er "
                        "join school s on s.id = er.school_id"),
    "subject_requirement": ("select province, year, coalesce(school_id,-1), "
                            "coalesce(group_code,''), coalesce(first_subject,''), "
                            "coalesce(secondary_subjects::text,'[]'), logic "
                            "from subject_requirement"),
}

ZKEY: dict[str, tuple[str, ...]] = {
    "source": ("source_name", "source_url", "year"),
    "pathway_region": ("pathway_id", "province", "county_name", "year"),
    "pathway_eligibility": ("pathway_id", "province", "rule_type", "year"),
    "enrollment_rule": ("_code", "year"),
    "subject_requirement": ("province", "year", "_school_id", "group_code",
                            "first_subject", "_sec_text", "logic"),
}


def read_jsonl(p: Path) -> list[dict]:
    if not p.is_file():
        return []
    out = []
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def norm(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="真正写库（默认 dry-run）")
    ap.add_argument("--dsn", default=DEFAULT_DSN)
    args = ap.parse_args()

    print(f"DSN:    {args.dsn.replace('change-me', '***')}")
    print(f"Staged: {STAGED}\n")

    # 取学校码映射（enrollment_rule 幂等键需要 code）
    staged = {t: read_jsonl(STAGED / f"{t}.jsonl") for t in ORDER}
    if not any(staged.values()):
        print("✗ staged 目录为空，先跑 build_zhang_layer.py", file=sys.stderr)
        return 2

    conn = psycopg.connect(args.dsn, connect_timeout=20)
    try:
        cur = conn.cursor()

        cur.execute("select id, code from school")
        sid2code = {int(i): norm(c) for i, c in cur.fetchall()}

        # 0) 记录各表 id 水位（用于生成**精确**回滚脚本）
        watermark: dict[str, int] = {}
        for t in ORDER:
            cur.execute(f'select coalesce(max(id),0) from "{t}"')
            watermark[t] = int(cur.fetchone()[0])

        # 1) 库内已有键
        existing: dict[str, set[tuple]] = {}
        for t in ORDER:
            cur.execute(KEYSQL[t])
            existing[t] = {tuple(norm(x) for x in r) for r in cur.fetchall()}

        # 2) 逐表过滤
        to_insert: dict[str, list[dict]] = {}
        skipped: dict[str, int] = {}
        for t in ORDER:
            keep: list[dict] = []
            sk = 0
            seen_local: set[tuple] = set()
            for r in staged[t]:
                if t == "enrollment_rule":
                    r["_code"] = sid2code.get(int(r["school_id"]), "")
                if t == "subject_requirement":
                    r["_school_id"] = r.get("school_id") if r.get("school_id") is not None else -1
                    r["_sec_text"] = json.dumps(r.get("secondary_subjects") or [],
                                                ensure_ascii=False)
                k = tuple(norm(r.get(c)) for c in ZKEY[t])
                if k in existing[t] or k in seen_local:
                    sk += 1
                    continue
                seen_local.add(k)
                keep.append(r)
            to_insert[t] = keep
            skipped[t] = sk

        print("=== 幂等过滤结果 ===")
        for t in ORDER:
            print(f"  {t:22s} staged {len(staged[t]):>6} ｜ 跳过(已存在) {skipped[t]:>6} "
                  f"｜ **将写入 {len(to_insert[t]):>6}**")
        total = sum(len(v) for v in to_insert.values())
        print(f"\n合计将写入 {total} 行")

        if not args.commit:
            print("\n（dry-run，未写库。确认请加 --commit）")
            return 0

        # 3) 真正写入（单事务）
        new_src_ids = [r["id"] for r in to_insert["source"]]
        for t in ORDER:
            recs = to_insert[t]
            if not recs:
                continue
            cols, json_cols, _ = SPEC[t]
            all_cols = tuple(cols) + ("created_at", "updated_at")
            ph = ", ".join(["%s"] * len(cols))
            col_sql = ", ".join('"' + c + '"' for c in all_cols)
            sql = f'INSERT INTO "{t}" ({col_sql}) VALUES ({ph}, now(), now())'
            rows = []
            for r in recs:
                vals = []
                for c in cols:
                    v = r.get(c)
                    if c in json_cols and v is not None and not isinstance(v, str):
                        v = json.dumps(v, ensure_ascii=False)
                    elif c in json_cols and v is None:
                        v = "[]"
                    vals.append(v)
                rows.append(tuple(vals))
            cur.executemany(sql, rows)
            print(f"  ✓ {t:22s} 写入 {len(rows):>6} 行")

        # 4) 推进 source 序列
        if new_src_ids:
            cur.execute("select setval(pg_get_serial_sequence('source','id'), "
                        "coalesce((select max(id) from source),1))")
        conn.commit()
        print("\n✓ 已提交")

        # 5) 复核
        print("\n=== 库内实际行数 ===")
        for t in ORDER:
            cur.execute(f'select count(*) from "{t}"')
            print(f"  {t:22s} {cur.fetchone()[0]:>8}")
        print("\n=== 外键悬空检查（本轮相关）===")
        for label, q in [
            ("pathway_region.pathway_id",
             "select count(*) from pathway_region a left join pathway p on p.id=a.pathway_id where p.id is null"),
            ("pathway_region.source_id",
             "select count(*) from pathway_region a left join source s on s.id=a.source_id where s.id is null"),
            ("pathway_eligibility.pathway_id",
             "select count(*) from pathway_eligibility a left join pathway p on p.id=a.pathway_id where p.id is null"),
            ("pathway_eligibility.source_id",
             "select count(*) from pathway_eligibility a left join source s on s.id=a.source_id where s.id is null"),
            ("enrollment_rule.school_id",
             "select count(*) from enrollment_rule a left join school s on s.id=a.school_id where s.id is null"),
            ("enrollment_rule.source_id",
             "select count(*) from enrollment_rule a left join source s on s.id=a.source_id where s.id is null"),
            ("subject_requirement.source_id",
             "select count(*) from subject_requirement a left join source s on s.id=a.source_id where s.id is null"),
            ("subject_requirement.school_id(非空)",
             "select count(*) from subject_requirement a left join school s on s.id=a.school_id where a.school_id is not null and s.id is null"),
        ]:
            cur.execute(q)
            print(f"  {label:36s} 悬空 {cur.fetchone()[0]}")

        # 6) 回滚脚本（按 id 水位精确删，不依赖 source_id 范围）
        #    ⚠️ 本轮无新增（如幂等复跑）时**不覆盖**已有回滚脚本，
        #      否则会把上一次真正落库时的水位冲掉、脚本变成"删 0 行"。
        rb = STAGED / "_rollback.sql"
        if total == 0:
            print(f"\n本轮无新增行 ⇒ 不覆盖既有回滚脚本：{rb}")
            return 0
        lines = [
            "-- 张分支数据接入 · 精确回滚",
            "-- 原理：本轮新增行必然落在各表「写入前 max(id)」水位之上，",
            "--       故按 id > 水位 删除即可，不受 source_id 复用影响。",
            "-- 幂等：重复执行安全（删不到即 0 行）。",
            "BEGIN;",
        ]
        for t in reversed(ORDER):
            if len(to_insert[t]) == 0:
                lines.append(f"-- {t}: 本轮无新增，跳过")
                continue
            lines.append(f'DELETE FROM "{t}" WHERE id > {watermark[t]};   '
                         f'-- 本轮新增 {len(to_insert[t])} 行')
        lines.append("COMMIT;")
        rb.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\n回滚脚本已生成：{rb}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
