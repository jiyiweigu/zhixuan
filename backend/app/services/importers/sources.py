"""来源登记表导入（``source``）。

数据文件：``data/sources/source-table.json``（15 条，2026-10-12 版）
业务键：``(source_name, source_url, year)``——与 ``source_guard.ensure_source`` 判重口径一致。

⚠️ 本表必须**先于**其余数据集导入：所有事实表的 ``source_id`` 外键都指向它。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.source import Source
from app.services.importers import ImportReport, SourceTriplet, load_dataset, rows_of, text_of
from app.services.importers import int_of
from app.services.importers.vocab import source_type_of


def _to_source(payload: SourceTriplet) -> Source:
    return Source(
        source_name=payload.source_name,
        source_url=payload.source_url,
        year=payload.year,
        source_type=payload.source_type,
    )


def import_sources(db: Session, path: Path) -> ImportReport:
    report = ImportReport(dataset="source")
    payload = load_dataset(path)
    if payload is None:
        report.missing_file = str(path)
        return report

    for row in rows_of(payload, "sources"):
        report.read += 1
        name = text_of(row, "source_name")
        url = text_of(row, "source_url")
        year = int_of(row, "year")

        if not name or not url or year is None:
            report.skip("missing_source_triplet")
            continue

        raw_type = text_of(row, "source_type")
        normalized_type = source_type_of(raw_type)
        if raw_type and normalized_type is None:
            report.skip("source_type_not_in_vocabulary")
            continue

        existing = db.scalar(
            select(Source).where(
                Source.source_name == name,
                Source.source_url == url,
                Source.year == year,
            )
        )

        if existing is None:
            db.add(
                _to_source(
                    SourceTriplet(
                        source_name=name, source_url=url, year=year, source_type=normalized_type
                    )
                )
            )
            report.created += 1
            continue

        if normalized_type and existing.source_type != normalized_type:
            existing.source_type = normalized_type
            report.updated += 1
        else:
            report.unchanged += 1

    db.flush()
    report.note(f"数据文件：{path}")
    return report
