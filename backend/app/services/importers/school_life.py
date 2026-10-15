"""院校生活信息导入（``school_life``，多行一校）。

数据文件：``data/schools/school_life_rows.json``（键 ``records``，实测 911 行）。
业务键：``(school_id, category, content)`` —— 实测该三元组零重复；
``(school_id, category)`` 有 253 组重复（同校同类多条），故不能只按类别做键。

来源与可靠性
------------
本表**自带来源三要素**（``source_name`` / ``source_url`` / ``year``）与可靠性标注：
③ 本轮全部为官网来源（``reliability=official``），故前端无需折叠；
``source_type`` 用中文（``官方``）→ 经跨层词表归一为 ``official``，未收录的取值留空并计数。

覆盖范围（照 ③ 的 meta 如实登记，不补）
--------------------------------------
仅「校园环境」（占地 / 建筑面积）与「图书馆」（馆藏）两类可从官网简介页稳定采到；
宿舍 / 食堂 / 交通三类官网承载极少（命中率 8% / 2%），需非官方来源（涉及合规与可信度，
待裁决）或逐校后勤网采集，本轮**如实留空**。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base_data import School
from app.models.constants import RELIABILITY_UNOFFICIAL, RELIABILITY_VALUES
from app.models.school_profile import SchoolLife
from app.services.importers import (
    ImportReport,
    SourceRegistry,
    int_of,
    load_dataset,
    rows_of,
    text_of,
)
from app.services.importers.vocab import source_type_of

_WRITABLE = ("source_type", "source_name", "source_url", "year", "reliability")


def import_school_life(db: Session, path: Path, registry: SourceRegistry) -> ImportReport:
    report = ImportReport(dataset="school_life")
    payload = load_dataset(path)
    if payload is None:
        report.missing_file = str(path)
        return report

    unknown_source_type = 0
    for row in rows_of(payload, "records"):
        report.read += 1

        school_id = int_of(row, "school_id")
        category = text_of(row, "category")
        content = text_of(row, "content")
        if school_id is None or not category or not content:
            report.skip("missing_school_category_or_content")
            continue
        if db.get(School, school_id) is None:
            report.skip("unknown_school_id")
            continue

        # 来源三要素缺一不入库（本表虽无 source_id 外键，仍逐行登记到 source 表）
        if registry.resolve(row) is None:
            report.skip("unresolvable_source")
            continue

        raw_type = text_of(row, "source_type")
        source_type = source_type_of(raw_type) or ""
        if raw_type and not source_type:
            unknown_source_type += 1

        reliability = text_of(row, "reliability") or RELIABILITY_UNOFFICIAL
        if reliability not in RELIABILITY_VALUES:
            report.skip("reliability_not_in_vocabulary")
            continue

        year = int_of(row, "year")
        if year is None:
            report.skip("missing_year")
            continue

        existing = db.scalar(
            select(SchoolLife).where(
                SchoolLife.school_id == school_id,
                SchoolLife.category == category,
                SchoolLife.content == content,
            )
        )
        values: dict[str, Any] = {
            "source_type": source_type,
            "source_name": text_of(row, "source_name"),
            "source_url": text_of(row, "source_url"),
            "year": year,
            "reliability": reliability,
        }

        if existing is None:
            db.add(SchoolLife(school_id=school_id, category=category, content=content, **values))
            report.created += 1
            continue

        changed = False
        for field, value in values.items():
            if value not in (None, "") and getattr(existing, field) != value:
                setattr(existing, field, value)
                changed = True
        if changed:
            report.updated += 1
        else:
            report.unchanged += 1

    db.flush()
    report.note(f"数据文件：{path}（业务键 school_id + category + content）")
    report.note(
        "本轮仅覆盖「校园环境」「图书馆」两类（官网简介页可采）；"
        "宿舍 / 食堂 / 交通待非官方来源或逐校后勤网采集，如实留空"
    )
    if unknown_source_type:
        report.note(f"source_type 未收录取值 {unknown_source_type} 行，已留空（不编造码位）")
    return report
