"""招生章程要点导入（``enrollment_rule``，按 (院校, 年份) 一行）。

数据文件：``data/schools/enrollment_rule_rows.json``（键 ``records``，实测 2,683 行；
``(school_id, year)`` 零重复 → 业务键；年份分布 2023 / 2024 / 2025）。

⚠️ 口径注意（照 ③ 的 meta，装配时必须保留限定语）
------------------------------------------------
本数据集是把 **Gaokao-Compass 招生计划数据集的专业级字段聚合到院校级**，
**并未采招生章程原文**：
- ``health_req``（体检要求）来自「专业备注」，聚合后**只适用于部分专业**，
  原文已带「仅部分专业」限定，本导入器**原样保留**，不得改写成全校统一要求；
- ``subject_req``（选科要求）同理；老高考年份（河南 ≤2024、江西 ≤2023）无选科概念，
  该字段为空属正常；
- ``content`` 并非章程原文，多数行为空。

因此前端展示时必须带上「仅部分专业」的限定语与来源，不得表述为院校统一规定。

来源：全部行 ``source_id = SRC-GAOAKAO-COMPASS``（渠道登记），
``source_url`` 指向省考试院（署名口径合规）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base_data import EnrollmentRule, School
from app.services.importers import (
    ImportReport,
    SourceRegistry,
    int_of,
    load_dataset,
    rows_of,
    text_of,
)

_TEXT_FIELDS = ("content", "subject_req", "health_req", "foreign_lang_req")


def import_enrollment_rules(db: Session, path: Path, registry: SourceRegistry) -> ImportReport:
    report = ImportReport(dataset="enrollment_rule")
    payload = load_dataset(path)
    if payload is None:
        report.missing_file = str(path)
        return report

    caveated = 0
    for row in rows_of(payload, "records"):
        report.read += 1

        school_id = int_of(row, "school_id")
        year = int_of(row, "year")
        if school_id is None or year is None:
            report.skip("missing_school_id_or_year")
            continue
        if db.get(School, school_id) is None:
            report.skip("unknown_school_id")
            continue

        source = registry.resolve(row)
        if source is None:
            report.skip("unresolvable_source")
            continue

        values: dict[str, Any] = {field: text_of(row, field) for field in _TEXT_FIELDS}
        if not any(values.values()):
            # 四个正文字段全空 → 该行没有可展示内容，跳过上报而不是落一行空记录
            report.skip("empty_rule_row")
            continue
        if "仅部分专业" in values["health_req"]:
            caveated += 1

        existing = db.scalar(
            select(EnrollmentRule).where(
                EnrollmentRule.school_id == school_id, EnrollmentRule.year == year
            )
        )
        if existing is None:
            db.add(EnrollmentRule(school_id=school_id, year=year, source_id=source.id, **values))
            report.created += 1
            continue

        changed = False
        for field, value in values.items():
            if value and getattr(existing, field) != value:
                setattr(existing, field, value)
                changed = True
        if existing.source_id != source.id:
            existing.source_id = source.id
            changed = True

        if changed:
            report.updated += 1
        else:
            report.unchanged += 1

    db.flush()
    report.note(f"数据文件：{path}（业务键 school_id + year）")
    report.note(
        "本表是「招生计划专业备注」聚合到院校级，**非招生章程原文**；"
        "体检 / 选科要求只适用于部分专业，展示时必须带「仅部分专业」限定语"
    )
    if caveated:
        report.note(f"其中 {caveated} 行原文已含「仅部分专业」限定，原样保留")
    return report
