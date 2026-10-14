"""升学途径字典导入（``pathway``，核心 26 类）。

数据文件：``data/dictionaries/pathways-26.json``（26 条）
业务键：``id``（如 ``national-special``）——与 ``app/data/pathways/catalog.json`` 同源，
保证「文件」与「库表」不出现两套编号。

``data_status`` 需归一：③ 用 ``pending``（6 条）/ ``schema_only``（20 条），
跨层词表只有 available / partial / schema_only / unavailable。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.models.pathway import Pathway
from app.services.importers import (
    ImportReport,
    SourceRegistry,
    int_of,
    load_dataset,
    rows_of,
    text_of,
)
from app.services.importers.vocab import data_status_of

# 可直接落库的字段（id / year / source_id 单独处理）
_WRITABLE = ("name", "category", "batch", "target_group", "apply_time", "description", "priority")


def import_pathways(db: Session, path: Path, registry: SourceRegistry) -> ImportReport:
    report = ImportReport(dataset="pathway")
    payload = load_dataset(path)
    if payload is None:
        report.missing_file = str(path)
        return report

    for row in rows_of(payload, "pathways"):
        report.read += 1

        pathway_id = text_of(row, "id")
        name = text_of(row, "name")
        if not pathway_id or not name:
            report.skip("missing_id_or_name")
            continue

        raw_status = text_of(row, "data_status")
        status = data_status_of(raw_status)
        if status is None:
            report.skip("data_status_not_in_vocabulary")
            continue

        year = int_of(row, "year")
        if year is None:
            report.skip("missing_year")
            continue

        source = registry.resolve(row)
        if source is None:
            report.skip("unresolvable_source")
            continue

        existing = db.get(Pathway, pathway_id)
        if existing is None:
            entity = Pathway(
                id=pathway_id,
                name=name,
                year=year,
                data_status=status,
                source_id=source.id,
            )
            for field in _WRITABLE:
                if field != "name":
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
        if existing.data_status != status:
            existing.data_status = status
            changed = True
        if existing.year != year:
            existing.year = year
            changed = True
        if existing.source_id != source.id:
            existing.source_id = source.id
            changed = True

        if changed:
            report.updated += 1
        else:
            report.unchanged += 1

    db.flush()
    report.note(f"数据文件：{path}")
    return report
