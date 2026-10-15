#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""表结构 ↔ 数据产物 字段对齐核查（③ 数据工程）

用途：在灌数之前，逐表比对 ``backend/app/models/*.py`` 的 SQLAlchemy 模型
与 ``data/`` 下的产出 JSON，找出四类问题：

  1. 模型要、数据缺     → ② 需要放宽约束，或 ③ 需要补字段
  2. 数据有、模型无     → ② 需要加列，或灌数时丢弃
  3. **硬阻塞** NOT NULL 冲突 → 数据为空，且模型列**没有 default**。
     ORM 写入时不会补值，INSERT 必然 IntegrityError（灌数真失败）。
  4. **软警告** 空值但模型列带 ``default=`` → ORM 会用 Python 默认值
     （``''`` / ``0`` / 空 dict）填上，入库**不会失败**；但该字段
     全量为空属于**数据缺口**，产品上会显示为空，需 ③ 补采。

同时报告 ``source_id`` / ``major_id`` 这类外键的**类型是否一致**
（模型 int 自增主键 vs 数据字符串 id）。类型不符会引发两类后果：
  ① ORM 层写入报错；② 语义错位（如把"国标专业代码"塞进指向 ``major.id`` 的外键）。

用法::

    python data/scripts/check_schema_alignment.py            # 全量报告
    python data/scripts/check_schema_alignment.py --table major
    python data/scripts/check_schema_alignment.py --strict    # 有阻塞则退出码 1

退出码：0 = 无硬阻塞；1 = 存在硬阻塞（NOT NULL 无默认值 / 外键类型冲突，--strict 时）。
软警告不影响退出码。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = ROOT / "backend" / "app" / "models"

# 自动生成的时间戳字段，数据侧不必提供
AUTO_FIELDS = {"id", "created_at", "updated_at"}

# 表 → (数据文件, 数组键)。数组键为 None 表示顶层就是数组。
# 未列出的表视为「尚无数据」。
DATA_MAP: dict[str, tuple[str, str | None]] = {
    "school":              ("data/schools/schools_merged.json", "records"),
    "major":               ("data/majors/majors.json", "majors"),
    "school_major_score":  ("data/school_major_score/school_major_score_2025_河南.json", "scores"),
    "score_segment":       ("data/score_segment/score_segment_2025_河南.json", "segments"),
    "pathway":             ("data/dictionaries/pathways-26.json", "pathways"),
    "pathway_region":      ("data/dictionaries/pathway-regions.json", "regions"),
    "pathway_eligibility": ("data/dictionaries/pathway-eligibility.json", "rules"),
    "province_exam_rule":  ("data/dictionaries/province-exam-rule.json", "rules"),
    "source":              ("data/sources/source-table.json", "sources"),
}

# 表 → 责任方（见产品书 9.1 角色-模块矩阵）
OWNER = {
    "③": {
        "school", "major", "school_major_score", "score_segment", "source",
        "enrollment_rule", "discipline_eval", "pathway", "pathway_eligibility",
        "pathway_region", "pathway_score", "school_profile", "school_life",
        "knowledge_doc", "province_exam_rule",
    },
    "②": {
        "users", "profiles", "user_favorite", "user_plan", "qa_log",
        "review_task", "admin_user", "index_task", "admin_audit_log",
    },
    "④": {"knowledge_chunk"},
    "队长/算法": {"subject_requirement", "physical_restriction"},
}


def owner_of(table: str) -> str:
    for who, tables in OWNER.items():
        if table in tables:
            return who
    return "?"


# 表 → 中国语名（报告可读性）
TABLE_CN = {
    "school": "院校基础库", "major": "专业基础库",
    "school_major_score": "院校专业录取分", "score_segment": "一分一段表",
    "pathway": "升学途径字典", "pathway_region": "专项实施区域",
    "pathway_eligibility": "资格规则", "province_exam_rule": "省份志愿模式",
    "source": "来源登记表", "enrollment_rule": "招生章程规则",
    "discipline_eval": "学科评估", "school_profile": "院校画像",
    "school_life": "院校生活信息", "knowledge_doc": "知识文档",
    "subject_requirement": "选科要求", "physical_restriction": "体检限制",
    "pathway_score": "途径分数参考", "users": "用户", "profiles": "用户档案",
    "user_favorite": "收藏", "user_plan": "志愿方案", "qa_log": "问答日志",
    "review_task": "审核任务", "admin_user": "管理员", "index_task": "索引任务",
    "admin_audit_log": "管理审计日志", "knowledge_chunk": "知识切片",
}

RE_CLASS = re.compile(r"^class\s+(\w+)\s*\(Base\)", re.M)
RE_TABLE = re.compile(r'__tablename__\s*=\s*["\'](\w+)["\']')
RE_COL = re.compile(r"^\s{4}(\w+)\s*:\s*Mapped\[([^\]]+)\]", re.M)
RE_FK = re.compile(r'ForeignKey\(\s*["\'](\w+)\.(\w+)["\']')


def parse_models() -> dict[str, dict]:
    """扫描 models 目录，返回 {表名: {fields, not_null, fks, file}}。"""
    out: dict[str, dict] = {}
    for py in sorted(MODELS_DIR.glob("*.py")):
        if py.name == "__init__.py":
            continue
        text = py.read_text(encoding="utf-8")
        for m in RE_CLASS.finditer(text):
            cls = m.group(1)
            start = m.start()
            nxt = RE_CLASS.search(text, m.end())
            body = text[start: nxt.start() if nxt else len(text)]
            tm = RE_TABLE.search(body)
            if not tm:
                continue
            table = tm.group(1)
            fields: dict[str, dict] = {}
            for cm in RE_COL.finditer(body):
                name, typ = cm.group(1), cm.group(2)
                # 取该列附近的片段判断 ForeignKey / nullable
                seg = body[cm.start(): cm.start() + 400]
                line_end = seg.find("\n")
                decl = seg[: line_end if line_end > 0 else len(seg)]
                fk = RE_FK.search(decl)
                fields[name] = {
                    "type": typ.strip(),
                    "nullable": "None" in typ,
                    "fk": f"{fk.group(1)}.{fk.group(2)}" if fk else None,
                    # 列声明带 default=（ORM 层默认值）时，空值会被自动填充，不构成硬阻塞
                    "has_default": ("default=" in decl) or ("server_default" in decl),
                }
            out[table] = {"fields": fields, "file": py.name}
    return out


def load_data(path: Path, key: str | None) -> tuple[list[dict], str]:
    if not path.exists():
        return [], "文件不存在"
    with path.open(encoding="utf-8") as fh:
        d = json.load(fh)
    if key and isinstance(d, dict) and key in d:
        return d[key], "ok"
    if isinstance(d, list):
        return d, "ok"
    if isinstance(d, dict):
        for k in ("records", "scores", "segments", "majors", "schools",
                  "pathways", "regions", "rules", "sources", "items", "data"):
            if k in d and isinstance(d[k], list):
                return d[k], f"自动推断键={k}"
    return [], "未找到数组"


def null_rate(rows: list[dict], field: str) -> tuple[int, int]:
    miss = sum(
        1 for r in rows
        if r.get(field) is None or (isinstance(r.get(field), str) and not r[field].strip())
    )
    return miss, len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="表结构 ↔ 数据产物 字段对齐核查")
    ap.add_argument("--table", help="只看某张表")
    ap.add_argument("--strict", action="store_true", help="存在阻塞时退出码 1")
    args = ap.parse_args()

    models = parse_models()
    blockers: list[str] = []
    warnings: list[str] = []

    targets = [args.table] if args.table else sorted(DATA_MAP)
    print("=" * 78)
    print("表结构 ↔ 数据产物 字段对齐核查")
    print(f"模型来源: backend/app/models/  （共 {len(models)} 张表）")
    print("=" * 78)

    for table in targets:
        cn = TABLE_CN.get(table, "")
        model = models.get(table)
        if not model:
            print(f"\n[!] {table} {cn} —— 模型里未找到该表（检查 __tablename__）")
            continue

        rel, key = DATA_MAP.get(table, (None, None))
        if rel is None:
            print(f"\n[—] {table} {cn} —— 尚无数据产物（待任务）")
            continue

        rows, note = load_data(ROOT / rel, key)
        if not rows:
            print(f"\n[?] {table} {cn} —— 读取失败：{note} ({rel})")
            continue

        mfields = {k: v for k, v in model["fields"].items() if k not in AUTO_FIELDS}
        dfields = set(rows[0].keys())

        missing = sorted(set(mfields) - dfields)       # 模型要，数据缺
        extra = sorted(dfields - set(model["fields"]))  # 数据有，模型无
        null_conflicts = []   # 硬阻塞：无 default，INSERT 必失败
        soft_null = []        # 软警告：有 default，会被填充，但属数据缺口
        for f, meta in mfields.items():
            if meta["nullable"] or f not in dfields:
                continue
            miss, total = null_rate(rows, f)
            if miss:
                bucket = soft_null if meta.get("has_default") else null_conflicts
                bucket.append((f, miss, total))

        fk_conflicts = []
        for f, meta in mfields.items():
            if meta["fk"] and f in dfields:
                sample = next((r[f] for r in rows if r.get(f) is not None), None)
                if isinstance(sample, str):
                    fk_conflicts.append((f, meta["fk"], type(sample).__name__, sample))

        print(f"\n{'─' * 78}")
        print(f"[{table}] {cn}   数据 {len(rows)} 条  ← {rel}")
        print(f"  模型字段 {len(mfields)} 个 | 数据字段 {len(dfields)} 个")

        if missing:
            print(f"  ✗ 模型要、数据缺 ({len(missing)}): {', '.join(missing)}")
        if extra:
            print(f"  ＋ 数据有、模型无 ({len(extra)}): {', '.join(extra)}")
        if not missing and not extra:
            print("  ✅ 字段完全对齐")

        for f, miss, total in null_conflicts:
            msg = (f"  ⛔ 硬阻塞 NOT NULL: `{f}` 有 {miss}/{total} 行为空 "
                   f"({miss / total * 100:.1f}%)，模型列无 default → INSERT 必失败")
            print(msg)
            blockers.append(f"{table}.{f}")
        for f, miss, total in soft_null:
            msg = (f"  ⚠ 空值(有默认值): `{f}` 有 {miss}/{total} 行为空 "
                   f"({miss / total * 100:.1f}%) → 入库写默认值，不失败；但属数据缺口")
            print(msg)
            warnings.append(f"{table}.{f}")
        for f, fk, pytype, sample in fk_conflicts:
            msg = (f"  ⛔ 外键类型冲突: `{f}` 模型指向 {fk} (int)，"
                   f"数据是 {pytype} 如 {sample!r}")
            print(msg)
            blockers.append(f"{table}.{f}(type)")

    print(f"\n{'=' * 78}")
    nontrivial = [t for t in models if t not in DATA_MAP]
    by_owner: dict[str, list[str]] = {}
    for t in sorted(nontrivial):
        by_owner.setdefault(owner_of(t), []).append(f"{t}·{TABLE_CN.get(t, '')}")
    print(f"尚无数据产物的表（{len(nontrivial)} 张），按责任方分组:")
    for who in ("③", "④", "队长/算法", "②", "?"):
        if who in by_owner:
            tag = " ← ③ 待产出" if who == "③" else ""
            print(f"  [{who}]{tag} " + ", ".join(by_owner[who]))
    print()
    if blockers:
        print(f"⛔ 硬阻塞 {len(blockers)} 个: {', '.join(blockers)}")
        print("   → 需 ② / 队长裁决或 ③ 补数据后，灌数才能成功。")
    else:
        print("✅ 无硬阻塞")
    if warnings:
        print(f"⚠ 软警告 {len(warnings)} 个（会被默认值填充，不阻塞）: {', '.join(warnings)}")
        print("   → 属数据缺口，建议 ③ 补采；不影响先跑通灌数流程。")
    print("=" * 78)

    if args.strict and blockers:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
