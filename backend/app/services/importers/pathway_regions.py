"""专项计划实施区域名单导入（``pathway_region``）。

数据文件：``data/dictionaries/pathway-regions.json``（91 行 = 国家专项 38 县 + 高校专项 53 县）
业务键：``(pathway_id, province, county_name, year)``。

``county_code`` 是硬需求（产品书第 6 章：``home_county_code`` 精确匹配优先于县名），
文件内 53/53 命中行政区划码，故不允许整列为空——单行缺码时跳过并上报。

省名需归一：③ 写 ``河南省``，库表与其余表统一用 ``河南``。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.pathway import Pathway, PathwayRegion
from app.services.importers import (
    ImportReport,
    SourceRegistry,
    int_of,
    load_dataset,
    rows_of,
    text_of,
)
from app.services.importers.vocab import province_name_of


def import_pathway_regions(
    db: Session, path: Path, registry: SourceRegistry
) -> ImportReport:
    report = ImportReport(dataset="pathway_region")
    payload = load_dataset(path)
    if payload is None:
        report.missing_file = str(path)
        return report

    for row in rows_of(payload, "regions"):
        report.read += 1

        pathway_id = text_of(row, "pathway_id")
        county_name = text_of(row, "county_name")
        county_code = text_of(row, "county_code")
        province = province_name_of(text_of(row, "province"))
        year = int_of(row, "year")

        if not pathway_id or not county_name:
            report.skip("missing_id_or_county")
            continue
        if province is None:
            report.skip("province_not_in_vocabulary")
            continue
        if not county_code:
            report.skip("missing_county_code")
            continue
        if year is None:
            report.skip("missing_year")
            continue
        if db.get(Pathway, pathway_id) is None:
            # 外键不满足：先把途径补进来，再导区域
            report.skip("pathway_fk_missing")
            continue

        source = registry.resolve(row)
        if source is None:
            report.skip("unresolvable_source")
            continue

        existing = db.scalar(
            select(PathwayRegion).where(
                PathwayRegion.pathway_id == pathway_id,
                PathwayRegion.province == province,
                PathwayRegion.county_name == county_name,
                PathwayRegion.year == year,
            )
        )

        if existing is None:
            db.add(
                PathwayRegion(
                    pathway_id=pathway_id,
                    province=province,
                    county_name=county_name,
                    county_code=county_code,
                    year=year,
                    source_id=source.id,
                )
            )
            report.created += 1
            continue

        if existing.county_code != county_code or existing.source_id != source.id:
            existing.county_code = county_code
            existing.source_id = source.id
            report.updated += 1
        else:
            report.unchanged += 1

    db.flush()
    report.note(f"数据文件：{path}")
    return report
