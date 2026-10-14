"""院校基础库导入（``school``，1367 所「在豫招生」本科院校）。

数据文件：``data/schools/schools_merged.json``（键 ``records``）
业务键：**``name``**，不是 ``code``。

为什么不按国标代码去重
----------------------
实盘 1367 行里有 40 个国标代码被**多个独立招生实体**共用
（「北京大学 / 北京大学医学部」「上海交通大学 / 医学院」「厦门大学 / 马来西亚分校」…），
而全部记录 ``name`` 零重复。若按 ``code`` 去重会误丢 75 行真实数据，
且会把医学部、分校这类独立招生单位合并掉。

为什么显式采用 ③ 的 ``id`` 作主键
--------------------------------
实测（2026-10-13）：``schools_merged.json`` 的 ``id`` 恰为 1-based 行序号
（北京大学 51、清华大学 55、安徽财经大学 243），且该 id 被**下游录取分数据直接引用**
（``school_major_score.school_id``）。若依赖自增顺序，任何一行被跳过都会让后续 id
整体错位，而错位不会被任何约束发现。故直接落 ③ 的 id，把耦合**显式化**：
某行缺失只会造成该 id 缺失，不会牵连其他院校。

``school`` 属产品书 7.1 的基础字典，**表内不含 ``source_id``**；
来源按「随记录在 source 表登记」处理——逐条 ensure_source，但不写入 school 行。

字段缺失留空不推断：``type`` / ``website`` / ``intro`` 在 ③ 的任务 2.5 补齐前全为空。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base_data import School
from app.services.importers import (
    ImportReport,
    SourceRegistry,
    int_of,
    load_dataset,
    rows_of,
    text_of,
)

_WRITABLE = ("name", "code", "province", "city", "level", "type", "ownership", "website", "intro")


def import_schools(
    db: Session,
    path: Path,
    registry: SourceRegistry,
    *,
    key: str = "records",
) -> ImportReport:
    report = ImportReport(dataset="school")
    payload = load_dataset(path)
    if payload is None:
        report.missing_file = str(path)
        return report

    rows = rows_of(payload, key) or rows_of(payload, "schools")

    for row in rows:
        report.read += 1

        name = text_of(row, "name")
        if not name:
            report.skip("missing_name")
            continue

        province = text_of(row, "province")
        level = text_of(row, "level")
        if not province or not level:
            report.skip("missing_province_or_level")
            continue

        # 来源随记录在 source 表登记（school 表本身无 source_id 列）
        if registry.resolve(row) is None:
            report.skip("unresolvable_source")
            continue

        existing = db.scalar(select(School).where(School.name == name))

        if existing is None:
            # 显式采用 ③ 的 id（下游录取分按此 id 引用；见模块 docstring）
            school_id = int_of(row, "id")
            if school_id is not None:
                occupied = db.get(School, school_id)
                if occupied is not None:
                    # 同 id 不同名：数据自相矛盾，跳过上报，不覆盖也不改 id
                    report.skip("school_id_conflict")
                    continue

            entity = School(name=name, province=province, level=level)
            if school_id is not None:
                entity.id = school_id
            for field in _WRITABLE:
                if field not in {"name", "province", "level"}:
                    setattr(entity, field, text_of(row, field))
            db.add(entity)
            report.created += 1
            continue

        changed = False
        for field in _WRITABLE:
            value = text_of(row, field)
            if value and getattr(existing, field) != value:
                setattr(existing, field, value)
                changed = True

        if changed:
            report.updated += 1
        else:
            report.unchanged += 1

    db.flush()
    report.note(f"数据文件：{path}（业务键 name）")
    return report
