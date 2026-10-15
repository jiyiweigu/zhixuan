"""专业基础库导入（``major``，845 个专业 + 93 个专业类 = **938 行**）。

数据文件：``data/majors/majors.json``（键 ``majors`` / ``classes``；文件级 ``meta`` 自带
来源三要素：教育部《普通高等学校本科专业目录（2025年）》，教高函〔2025〕3 号）。

业务键：``code``
--------------
专业用 6–9 位国标代码（后缀 T=特设 / K=国控 / TK=兼具，脚本不剥离），专业类用 4 位代码；
实测 938 行代码与名称**均无重复**（含「专业类 vs 专业」之间也不重名），故直接以 ``code``
为幂等键、``name`` 为业务键双保险。

为什么专业类也落 ``major`` 表
------------------------------
产品端会把「按专业类招生」当成一个可检索、可填报的条目（录取分里 ``major_name`` 就大量
是「××类」），故 93 个专业类作为 ``is_category=True`` 的行一并落库，与 845 个专业共用一张表、
一套检索接口。**专业与专业类的从属关系由代码前缀表达**（专业 ``080901`` → 专业类 ``0809``），
不额外落列；需要时可 ``code`` 前 4 位 join。

字段映射（``category`` 存**学科门类**，与 ``/api/majors?category=`` 的精确匹配语义一致）
------------------------------------------------------------------------------
``name`` ← ``name`` / ``class_name``；``code`` ← ``code`` / ``class_code``；
``category`` ← ``menlei``（12 个门类之一，非专业类名）；``degree`` ← ``degree_note``
（如「可授经济学或管理学学士学位」，缺则留空）；``is_category`` ← 专业类 True。
``first_class`` / ``intro`` / 学费等约束字段本文件没有 → 留空，等 ③ 的画像数据（tasks.md 2.5）。

未落库的字段（如实上报，不静默）
--------------------------------
- ``is_special``（493 行特设）、``is_state_controlled``（154 行国控）、``code_len``、
  ``code_type``：``major`` 表无对应列，仅在报告中说明；
- 12 个 ``menlei``（学科门类本身）：不是可填报条目，不入库，仅用于给专业打 ``category``。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base_data import Major
from app.services.importers import (
    ImportReport,
    SourceRegistry,
    load_dataset,
    rows_of,
    text_of,
)

_WRITABLE = ("name", "code", "category", "degree")


def _row_pairs(payload: dict[str, Any]) -> list[tuple[dict[str, Any], bool]]:
    """返回 ``[(行, 是否专业类)]``；专业类在前，专业在后（稳定顺序，便于复核）。"""
    pairs: list[tuple[dict[str, Any], bool]] = []
    for row in rows_of(payload, "classes"):
        pairs.append(({**row, "name": row.get("class_name"), "code": row.get("class_code")}, True))
    for row in rows_of(payload, "majors"):
        pairs.append((dict(row), False))
    return pairs


def import_majors(db: Session, path: Path, registry: SourceRegistry) -> ImportReport:
    report = ImportReport(dataset="major")
    payload = load_dataset(path)
    if payload is None:
        report.missing_file = str(path)
        return report

    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else None

    special = 0
    controlled = 0
    classes = 0
    for row, is_class in _row_pairs(payload):
        report.read += 1

        name = text_of(row, "name")
        code = text_of(row, "code")
        if not name or not code:
            report.skip("missing_name_or_code")
            continue

        menlei = text_of(row, "menlei")
        if not menlei:
            # category 是检索的精确匹配键，缺门类会让该行筛不出来 → 跳过并上报
            report.skip("missing_category")
            continue

        # 来源随记录登记（major 属基础字典，表内无 source_id 列）；用文件级 meta 解析
        if registry.resolve(row, meta) is None:
            report.skip("unresolvable_source")
            continue

        if row.get("is_special"):
            special += 1
        if row.get("is_state_controlled"):
            controlled += 1
        if is_class:
            classes += 1

        degree = text_of(row, "degree_note")
        values = {
            "name": name,
            "code": code,
            "category": menlei,
            "degree": degree,
        }

        existing = db.scalar(select(Major).where(Major.code == code))
        if existing is None:
            same_name = db.scalar(select(Major).where(Major.name == name))
            if same_name is not None:
                # 同名不同码：数据自相矛盾，跳过上报，不覆盖既有行
                report.skip("name_conflict")
                continue
            entity = Major(**values, is_category=is_class)
            db.add(entity)
            report.created += 1
            continue

        changed = False
        for field in _WRITABLE:
            value = values[field]
            # 已落库的画像类补充（如 intro / first_class）不因本文件缺列而被清空
            if value and getattr(existing, field) != value:
                setattr(existing, field, value)
                changed = True
        if bool(existing.is_category) != is_class:
            existing.is_category = is_class
            changed = True

        if changed:
            report.updated += 1
        else:
            report.unchanged += 1

    db.flush()
    report.note(f"数据文件：{path}（业务键 code；专业类 {classes} 行 is_category=True）")
    report.note("category 存学科门类（menlei）；专业与专业类的从属关系由 code 前 4 位表达")
    if special or controlled:
        report.note(
            f"is_special（特设）{special} 行、is_state_controlled（国控）{controlled} 行："
            "major 表无对应列，未落库（如实登记，待裁决是否加列）"
        )
    return report
