"""报考约束规则维护（产品书 6.6；v1.1 新增三组规则接口）。

三组对应 7.6 的三张表，均由 ⑤ 号管理端维护、③ 号填数据：

- ``province-rules``          省份志愿模式模板
- ``subject-requirements``    选科要求
- ``physical-restrictions``   身体条件限制

**硬约束**（8.5 风险清单「规则数据带 year 但被覆盖成最新一份」的应对）：

1. 每条规则**必须带 ``year``**，2025 与 2026 并存，缺 year → 4001；
2. 必须附官方来源（``source`` 三要素缺一 → 4001）；
3. 写操作全部留痕（tasks.md 8.1）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.response import BizError
from app.models.audit import (
    ACTION_CONSTRAINT_RULE_CREATE,
    ACTION_CONSTRAINT_RULE_UPDATE,
)
from app.models.constraints import (
    PhysicalRestriction,
    ProvinceExamRule,
    SubjectRequirement,
)
from app.models.knowledge import AdminUser
from app.models.source import Source
from app.services import audit as audit_service
from app.services import source_guard

__all__ = [
    "create_physical_restriction",
    "create_province_rule",
    "create_subject_requirement",
    "list_physical_restrictions",
    "list_province_rules",
    "list_subject_requirements",
    "update_physical_restriction",
    "update_province_rule",
    "update_subject_requirement",
]


def _citation_of(source: Source | None) -> dict[str, Any]:
    if source is None:
        return {"source_name": "", "source_url": "", "year": 0}
    return {
        "source_name": source.source_name,
        "source_url": source.source_url,
        "year": source.year,
    }


def _sources_of(db: Session, source_ids: list[int]) -> dict[int, Source]:
    ids = sorted({sid for sid in source_ids if sid})
    if not ids:
        return {}
    return {row.id: row for row in db.scalars(select(Source).where(Source.id.in_(ids))).all()}


def _require_year_and_source(db: Session, payload: Any) -> tuple[int, Source]:
    """校验 source 三要素与 year；缺一返回 4001（与 6.6 一致）。"""
    source_guard.require_source(
        payload.source.source_name, payload.source.source_url, payload.source.year
    )
    year = source_guard.require_year(payload.year or payload.source.year)
    source = source_guard.ensure_source(db, payload.source)
    return year, source


def _load(db: Session, model: Any, rule_id: int, label: str):
    row = db.get(model, rule_id)
    if row is None:
        raise BizError(f"参数错误：{label}不存在：{rule_id}")
    return row


# --------------------------------------------------------------------------- #
# 省份志愿模式模板
# --------------------------------------------------------------------------- #
def province_rule_item(row: ProvinceExamRule, source: Source | None = None) -> dict[str, Any]:
    return {
        "rule_id": row.id,
        "province": row.province,
        "year": row.year,
        "batch": row.batch,
        "mode": row.mode,
        "volunteer_count": row.volunteer_count,
        "majors_per_group": row.majors_per_group,
        "has_adjust": row.has_adjust,
        "admit_method": row.admit_method,
        "ratio": row.ratio,
        "tie_rule": row.tie_rule,
        "mutex_groups": list(row.mutex_groups or []),
        "collect_count": row.collect_count,
        "source": _citation_of(source),
    }


def list_province_rules(
    db: Session, *, province: str = "", year: int | None = None
) -> list[dict[str, Any]]:
    stmt = select(ProvinceExamRule)
    if province.strip():
        stmt = stmt.where(ProvinceExamRule.province == province.strip())
    if year:
        stmt = stmt.where(ProvinceExamRule.year == year)
    rows = list(
        db.scalars(stmt.order_by(ProvinceExamRule.province.asc(), ProvinceExamRule.year.desc())).all()
    )
    sources = _sources_of(db, [row.source_id for row in rows])
    return [province_rule_item(row, sources.get(row.source_id)) for row in rows]


def create_province_rule(
    db: Session, payload: Any, admin: AdminUser, *, client_ip: str = ""
) -> dict[str, Any]:
    year, source = _require_year_and_source(db, payload)
    row = ProvinceExamRule(
        province=payload.province.strip(),
        year=year,
        batch=payload.batch.strip(),
        mode=payload.mode,
        volunteer_count=payload.volunteer_count,
        majors_per_group=payload.majors_per_group,
        has_adjust=payload.has_adjust,
        admit_method=payload.admit_method,
        ratio=payload.ratio,
        tie_rule=payload.tie_rule,
        mutex_groups=list(payload.mutex_groups or []),
        collect_count=payload.collect_count,
        source_id=source.id,
    )
    db.add(row)
    db.flush()
    audit_service.record_audit(
        db, admin, ACTION_CONSTRAINT_RULE_CREATE,
        target_type="province_exam_rule", target_id=row.id,
        detail={"province": row.province, "year": year, "batch": row.batch,
                "source_name": source.source_name},
        client_ip=client_ip,
    )
    db.commit()
    return {"rule_id": row.id}


def update_province_rule(
    db: Session, rule_id: int, payload: Any, admin: AdminUser, *, client_ip: str = ""
) -> None:
    row = _load(db, ProvinceExamRule, rule_id, "省份规则")
    year, source = _require_year_and_source(db, payload)
    row.province = payload.province.strip()
    row.year = year
    row.batch = payload.batch.strip()
    row.mode = payload.mode
    row.volunteer_count = payload.volunteer_count
    row.majors_per_group = payload.majors_per_group
    row.has_adjust = payload.has_adjust
    row.admit_method = payload.admit_method
    row.ratio = payload.ratio
    row.tie_rule = payload.tie_rule
    row.mutex_groups = list(payload.mutex_groups or [])
    row.collect_count = payload.collect_count
    row.source_id = source.id
    audit_service.record_audit(
        db, admin, ACTION_CONSTRAINT_RULE_UPDATE,
        target_type="province_exam_rule", target_id=rule_id,
        detail={"province": row.province, "year": year, "batch": row.batch},
        client_ip=client_ip,
    )
    db.commit()


# --------------------------------------------------------------------------- #
# 选科要求
# --------------------------------------------------------------------------- #
def subject_requirement_item(row: SubjectRequirement, source: Source | None = None) -> dict[str, Any]:
    return {
        "rule_id": row.id,
        "province": row.province,
        "year": row.year,
        "batch": row.batch,
        "school_id": row.school_id,
        "group_code": row.group_code,
        "major_id": row.major_id,
        "first_subject": row.first_subject,
        "secondary_subjects": list(row.secondary_subjects or []),
        "logic": row.logic,
        "source": _citation_of(source),
    }


def list_subject_requirements(
    db: Session, *, province: str = "", year: int | None = None, major_id: int | None = None
) -> list[dict[str, Any]]:
    stmt = select(SubjectRequirement)
    if province.strip():
        stmt = stmt.where(SubjectRequirement.province == province.strip())
    if year:
        stmt = stmt.where(SubjectRequirement.year == year)
    if major_id:
        stmt = stmt.where(SubjectRequirement.major_id == major_id)
    rows = list(db.scalars(stmt.order_by(SubjectRequirement.id.asc())).all())
    sources = _sources_of(db, [row.source_id for row in rows])
    return [subject_requirement_item(row, sources.get(row.source_id)) for row in rows]


def create_subject_requirement(
    db: Session, payload: Any, admin: AdminUser, *, client_ip: str = ""
) -> dict[str, Any]:
    year, source = _require_year_and_source(db, payload)
    row = SubjectRequirement(
        province=payload.province.strip(),
        year=year,
        batch=payload.batch.strip(),
        school_id=payload.school_id,
        group_code=payload.group_code,
        major_id=payload.major_id,
        first_subject=payload.first_subject.strip(),
        secondary_subjects=list(payload.secondary_subjects or []),
        logic=payload.logic,
        source_id=source.id,
    )
    db.add(row)
    db.flush()
    audit_service.record_audit(
        db, admin, ACTION_CONSTRAINT_RULE_CREATE,
        target_type="subject_requirement", target_id=row.id,
        detail={"province": row.province, "year": year, "major_id": row.major_id,
                "source_name": source.source_name},
        client_ip=client_ip,
    )
    db.commit()
    return {"rule_id": row.id}


def update_subject_requirement(
    db: Session, rule_id: int, payload: Any, admin: AdminUser, *, client_ip: str = ""
) -> None:
    row = _load(db, SubjectRequirement, rule_id, "选科要求")
    year, source = _require_year_and_source(db, payload)
    row.province = payload.province.strip()
    row.year = year
    row.batch = payload.batch.strip()
    row.school_id = payload.school_id
    row.group_code = payload.group_code
    row.major_id = payload.major_id
    row.first_subject = payload.first_subject.strip()
    row.secondary_subjects = list(payload.secondary_subjects or [])
    row.logic = payload.logic
    row.source_id = source.id
    audit_service.record_audit(
        db, admin, ACTION_CONSTRAINT_RULE_UPDATE,
        target_type="subject_requirement", target_id=rule_id,
        detail={"province": row.province, "year": year, "major_id": row.major_id},
        client_ip=client_ip,
    )
    db.commit()


# --------------------------------------------------------------------------- #
# 身体条件限制
# --------------------------------------------------------------------------- #
def physical_restriction_item(row: PhysicalRestriction, source: Source | None = None) -> dict[str, Any]:
    return {
        "rule_id": row.id,
        "condition": row.condition,
        "threshold": row.threshold,
        "major_category": row.major_category,
        "major_code": row.major_code,
        "level": row.level,
        "detail": row.detail,
        "province": row.province,
        "year": row.year,
        "source": _citation_of(source),
    }


def list_physical_restrictions(
    db: Session, *, province: str = "", year: int | None = None, condition: str = ""
) -> list[dict[str, Any]]:
    stmt = select(PhysicalRestriction)
    if province.strip():
        stmt = stmt.where(PhysicalRestriction.province == province.strip())
    if year:
        stmt = stmt.where(PhysicalRestriction.year == year)
    if condition.strip():
        stmt = stmt.where(PhysicalRestriction.condition == condition.strip())
    rows = list(db.scalars(stmt.order_by(PhysicalRestriction.id.asc())).all())
    sources = _sources_of(db, [row.source_id for row in rows])
    return [physical_restriction_item(row, sources.get(row.source_id)) for row in rows]


def create_physical_restriction(
    db: Session, payload: Any, admin: AdminUser, *, client_ip: str = ""
) -> dict[str, Any]:
    year, source = _require_year_and_source(db, payload)
    row = PhysicalRestriction(
        condition=payload.condition.strip(),
        threshold=payload.threshold.strip(),
        major_category=payload.major_category.strip(),
        major_code=payload.major_code.strip(),
        level=payload.level,
        detail=payload.detail,
        province=payload.province.strip(),
        year=year,
        source_id=source.id,
    )
    db.add(row)
    db.flush()
    audit_service.record_audit(
        db, admin, ACTION_CONSTRAINT_RULE_CREATE,
        target_type="physical_restriction", target_id=row.id,
        detail={"condition": row.condition, "level": row.level, "year": year,
                "source_name": source.source_name},
        client_ip=client_ip,
    )
    db.commit()
    return {"rule_id": row.id}


def update_physical_restriction(
    db: Session, rule_id: int, payload: Any, admin: AdminUser, *, client_ip: str = ""
) -> None:
    row = _load(db, PhysicalRestriction, rule_id, "身体条件限制")
    year, source = _require_year_and_source(db, payload)
    row.condition = payload.condition.strip()
    row.threshold = payload.threshold.strip()
    row.major_category = payload.major_category.strip()
    row.major_code = payload.major_code.strip()
    row.level = payload.level
    row.detail = payload.detail
    row.province = payload.province.strip()
    row.year = year
    row.source_id = source.id
    audit_service.record_audit(
        db, admin, ACTION_CONSTRAINT_RULE_UPDATE,
        target_type="physical_restriction", target_id=rule_id,
        detail={"condition": row.condition, "level": row.level, "year": year},
        client_ip=client_ip,
    )
    db.commit()
