"""院校画像导入（``school_profile``，一校一行）。

数据文件：``data/schools/school_profile_rows.json``（键 ``records``，实测 1,348 行，
``school_id`` 无重复 → 业务键即 ``school_id``，与表上的唯一约束一致）。

字段口径（严格照 ③ 的 meta，不推断）
------------------------------------
- ``tuition_range``：招生计划学费按校聚合的 min-max（如 ``5000-75000``），数值直出；
- ``established_year`` / ``faculty_count`` / ``first_class_major_count`` /
  ``student_faculty_ratio`` / ``campus_list`` / ``master_phd_points``：官网「学校简介」页正则抽取；
- ``accommodation_fee``：官网简介页不载 → 全表留空，**不填占位**；
- 正则抽不到一律留空（``null`` / ``""`` / ``[]``），本导入器不做任何补全。

两道防护
--------
1. ``school_id`` 必须在 ``school`` 表存在，否则跳过并上报 ``unknown_school_id``
   （③ 的 id 是位置耦合的，未知 id 绝不降级成 NULL 硬塞）；
2. ``campus_list`` / ``master_phd_points`` 是 JSON 列，形状必须符合同步给前端的契约：
   ``[{name,address,city}]`` 与 ``{master,phd}``；形状不符的元素丢弃并在报告里计数，
   不把脏形状写进库。

空值不覆盖既有值：字段为空（``""`` / ``None`` / ``[]``）时保留库内已有值，
避免「一次重跑把先前补到的数据抹掉」。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.base_data import School
from app.models.school_profile import SchoolProfile
from app.services.importers import (
    ImportReport,
    SourceRegistry,
    int_of,
    load_dataset,
    rows_of,
    text_of,
)

# 可直接落库的标量字段（school_id / source_id 单独处理，JSON 列单独规范）
_SCALAR = (
    "tuition_range",
    "accommodation_fee",
    "established_year",
    "first_class_major_count",
    "faculty_count",
    "student_faculty_ratio",
)
_JSON_LIST = "campus_list"
_JSON_DICT = "master_phd_points"


def _campus_list(value: Any) -> tuple[list[dict[str, str]], int]:
    """规范校区列表为 ``[{name,address,city}]``；返回 (结果, 丢弃元素数)。"""
    if not isinstance(value, list):
        return [], 0
    out: list[dict[str, str]] = []
    dropped = 0
    for item in value:
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            dropped += 1
            continue
        out.append(
            {
                "name": str(item.get("name") or "").strip(),
                "address": str(item.get("address") or "").strip(),
                "city": str(item.get("city") or "").strip(),
            }
        )
    return out, dropped


def _points(value: Any) -> dict[str, int] | None:
    """规范硕博点数为 ``{master,phd}``；形状不符返回 None（宁可缺，不猜）。"""
    if not isinstance(value, dict):
        return None
    master = value.get("master")
    phd = value.get("phd")
    if master is None and phd is None:
        return None
    out: dict[str, int] = {}
    for key, raw in (("master", master), ("phd", phd)):
        if raw is None:
            continue
        try:
            out[key] = int(raw)
        except (TypeError, ValueError):
            return None
    return out or None


def import_school_profiles(db: Session, path: Path, registry: SourceRegistry) -> ImportReport:
    report = ImportReport(dataset="school_profile")
    payload = load_dataset(path)
    if payload is None:
        report.missing_file = str(path)
        return report

    dropped_campus = 0
    for row in rows_of(payload, "records"):
        report.read += 1

        school_id = int_of(row, "school_id")
        if school_id is None:
            report.skip("missing_school_id")
            continue
        if db.get(School, school_id) is None:
            report.skip("unknown_school_id")
            continue

        source = registry.resolve(row)
        if source is None:
            report.skip("unresolvable_source")
            continue

        campus, dropped = _campus_list(row.get(_JSON_LIST))
        dropped_campus += dropped
        points = _points(row.get(_JSON_DICT))

        values: dict[str, Any] = {field: text_of(row, field) for field in _SCALAR}
        for field in ("established_year", "first_class_major_count", "faculty_count"):
            values[field] = int_of(row, field)

        existing = (
            db.query(SchoolProfile).filter(SchoolProfile.school_id == school_id).one_or_none()
        )

        if existing is None:
            entity = SchoolProfile(school_id=school_id, source_id=source.id)
            for field, value in values.items():
                if value not in (None, ""):
                    setattr(entity, field, value)
            if campus:
                entity.campus_list = campus
            if points:
                entity.master_phd_points = points
            db.add(entity)
            report.created += 1
            continue

        changed = False
        for field, value in values.items():
            if value not in (None, "") and getattr(existing, field) != value:
                setattr(existing, field, value)
                changed = True
        if campus and existing.campus_list != campus:
            existing.campus_list = campus
            changed = True
        if points and existing.master_phd_points != points:
            existing.master_phd_points = points
            changed = True
        if existing.source_id != source.id:
            existing.source_id = source.id
            changed = True

        if changed:
            report.updated += 1
        else:
            report.unchanged += 1

    db.flush()
    report.note(f"数据文件：{path}（业务键 school_id，一校一行）")
    report.note(
        "住宿费 accommodation_fee 全表留空（官网简介页不载，待招生章程专项采集）；"
        "空值不覆盖库内既有值"
    )
    if dropped_campus:
        report.note(f"campus_list 中形状不符的元素丢弃 {dropped_campus} 个（仅接受 {{name,address,city}}）")
    return report
