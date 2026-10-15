"""途径资格规则导入（``pathway_eligibility``）。

数据文件：``data/dictionaries/pathway-eligibility.json``（11 条）
业务键：``(pathway_id, province, rule_type)``——文件内该组合无重复。

⚠️ 两个必须显式处理的问题（均上报，不静默）：

1. 规则行**没有 year 字段**，而 ``pathway_eligibility.year`` 是 NOT NULL。
   年份从其引用的 ``source`` 记录取（来源表里哪一年登记的，规则就落在哪一年）——
   可追溯，非编造。
2. 规则 ``general-batch`` 引用的途径 **不在** ③ 自己的 26 类字典里
   （字典用 ``normal-batch``）→ 外键不满足，跳过并上报 ③。

``placeholders`` 是占位骨架（``source_id`` 为 null），刻意不导入，单独计数。
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.pathway import Pathway, PathwayEligibility
from app.services.importers import (
    ImportReport,
    SourceRegistry,
    load_dataset,
    rows_of,
    text_of,
)
from app.services.importers.vocab import province_name_of


def _params_of(row: dict) -> dict:
    value = row.get("params")
    return value if isinstance(value, dict) else {}


def import_eligibility(db: Session, path: Path, registry: SourceRegistry) -> ImportReport:
    report = ImportReport(dataset="pathway_eligibility")
    payload = load_dataset(path)
    if payload is None:
        report.missing_file = str(path)
        return report

    placeholders = payload.get("placeholders")
    if isinstance(placeholders, list) and placeholders:
        report.note(f"占位骨架 placeholders {len(placeholders)} 条：无来源，按设计不入库")

    for row in rows_of(payload, "rules"):
        report.read += 1

        pathway_id = text_of(row, "pathway_id")
        rule_type = text_of(row, "rule_type")
        raw_province = text_of(row, "province")
        province = province_name_of(raw_province) or raw_province

        if not pathway_id or not rule_type:
            report.skip("missing_pathway_or_rule_type")
            continue

        if db.get(Pathway, pathway_id) is None:
            report.skip("pathway_fk_missing")
            continue

        year = registry.year_for(row)
        if year is None:
            report.skip("missing_year")
            continue

        source = registry.resolve(row)
        if source is None:
            report.skip("unresolvable_source")
            continue

        existing = db.scalar(
            select(PathwayEligibility).where(
                PathwayEligibility.pathway_id == pathway_id,
                PathwayEligibility.province == province,
                PathwayEligibility.rule_type == rule_type,
            )
        )

        params = _params_of(row)
        rule_desc = text_of(row, "rule_desc")

        if existing is None:
            db.add(
                PathwayEligibility(
                    pathway_id=pathway_id,
                    province=province,
                    rule_type=rule_type,
                    rule_desc=rule_desc,
                    params=params,
                    year=year,
                    source_id=source.id,
                )
            )
            report.created += 1
            continue

        changed = False
        if rule_desc and existing.rule_desc != rule_desc:
            existing.rule_desc = rule_desc
            changed = True
        if json.dumps(existing.params or {}, sort_keys=True) != json.dumps(
            params, sort_keys=True
        ):
            existing.params = params
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
