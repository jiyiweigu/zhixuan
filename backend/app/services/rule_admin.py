"""报考约束规则维护（产品书 6.6；契约 8.7/8.8 的七组接口）。

七组对应 8.7 的六张逻辑表，均由 ⑤ 号管理端维护、③ 号填数据：

- ``province-rules``           省份志愿模式模板
- ``subject-requirements``     选科要求
- ``physical-restrictions``    身体条件限制
- ``admission-requirements``   单科 / 语种 / 性别 / 面试 / 政审 / 体测等章程要求
- ``major-tuition``            按省份 / 年份 / 院校 / 专业维度的学费
- ``rule-dataset-status``      各规则集的 ``data_status``
- ``rule-datasets/import``     批量导入 JSON 规则项（单次 ≤500，整批事务）

**硬约束**（8.5 风险清单「规则数据带 year 但被覆盖成最新一份」的应对）：

1. 每条规则**必须带 ``year``**，2025 与 2026 并存，缺 year → 4001；
2. 必须附官方来源（``source`` 三要素缺一 → 4001；导入不接受 ``example.invalid`` 演示源）；
3. 写操作全部留痕（tasks.md 8.1）；
4. ``data_status=available`` **不允许手工设置**，只能由导入/维护覆盖率校验自动得出
   （契约 8.8 硬约束），写入后由 :func:`recompute_dataset_status` 重算。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.response import BizError
from app.models.audit import (
    ACTION_CONSTRAINT_RULE_CREATE,
    ACTION_CONSTRAINT_RULE_UPDATE,
)
from app.models.constants import (
    DATA_STATUS_AVAILABLE,
    DATA_STATUS_UNAVAILABLE,
    DATASET_ADMISSION_REQUIREMENT,
    DATASET_MAJOR_TUITION,
    DATASET_PHYSICAL_RESTRICTION,
    DATASET_PROVINCE_EXAM_RULE,
    DATASET_SUBJECT_REQUIREMENT,
    DATASET_VALUES,
    EXAM_TYPE_NORMAL,
    batch_code_of,
    province_code_of,
    province_name_of,
)
from app.models.constraints import (
    AdmissionRequirement,
    MajorTuition,
    PhysicalRestriction,
    ProvinceExamRule,
    RuleDatasetStatus,
    SubjectRequirement,
)
from app.models.knowledge import AdminUser
from app.models.source import Source
from app.services import audit as audit_service
from app.services import source_guard
from app.services.constraints import DEFAULT_BATCH, dataset_presence

__all__ = [
    "create_admission_requirement",
    "create_major_tuition",
    "create_physical_restriction",
    "create_province_rule",
    "create_subject_requirement",
    "import_rule_dataset",
    "list_admission_requirements",
    "list_major_tuitions",
    "list_physical_restrictions",
    "list_province_rules",
    "list_rule_dataset_status",
    "list_subject_requirements",
    "recompute_dataset_status",
    "upsert_rule_dataset_status",
    "update_admission_requirement",
    "update_major_tuition",
    "update_physical_restriction",
    "update_province_rule",
    "update_subject_requirement",
]

PAGE_SIZE_MAX = 100
DEMO_SOURCE_HOST = "example.invalid"


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
# 契约 8.8 公共设施：分页包、省份归一、data_status 自动重算
# --------------------------------------------------------------------------- #
def paginate(
    items: Sequence[dict[str, Any]], page: int = 1, page_size: int = 20
) -> dict[str, Any]:
    """契约 8.8：GET 统一返回 ``{items, total, page, page_size}``。"""
    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 20), 1), PAGE_SIZE_MAX)
    start = (page - 1) * page_size
    return {
        "items": list(items[start : start + page_size]),
        "total": len(items),
        "page": page,
        "page_size": page_size,
    }


def _province_pair(province_code: str = "", province: str = "") -> tuple[str, str]:
    """归一 ``(province_code, province_name)``，两侧任一为空即可由另一侧推导。"""
    code = province_code_of(province_code or province)
    name = str(province or "").strip() or province_name_of(code)
    return code, name


def _status_key(payload: Any, province_code: str, year: int) -> tuple[str, int, str, str]:
    """从写请求取 ``(province_code, year, batch_code, exam_type)``，用于重算状态。"""
    batch = getattr(payload, "batch", "") or getattr(payload, "batch_code", "")
    return (
        province_code,
        int(year or 0),
        batch_code_of(batch),
        str(getattr(payload, "exam_type", "") or EXAM_TYPE_NORMAL),
    )


def recompute_dataset_status(
    db: Session,
    dataset: str,
    province_code: str,
    year: int,
    batch_code: str = "",
    exam_type: str = EXAM_TYPE_NORMAL,
) -> RuleDatasetStatus:
    """按"表里是否真的有该省该年的记录"重算规则集状态（契约 8.8）。

    ``available`` 由覆盖率自动得出，**不接受管理端手工设置**：

    - 无记录 → ``unavailable``；
    - 有记录 → ``available``（来源完整性由 ``source_guard`` 在写入时已保证）。

    本函数幂等：已存在同键记录则原地更新 ``status`` / ``note`` / ``updated_at``。
    """
    present = dataset_presence(db, dataset, province_code, year, batch_code)
    status = DATA_STATUS_AVAILABLE if present else DATA_STATUS_UNAVAILABLE
    note = "由导入/维护覆盖率校验自动得出（契约 8.8：available 不允许手工设置）"

    row = db.scalars(
        select(RuleDatasetStatus).where(
            RuleDatasetStatus.province_code == province_code,
            RuleDatasetStatus.year == year,
            RuleDatasetStatus.batch_code == batch_code,
            RuleDatasetStatus.exam_type == exam_type,
            RuleDatasetStatus.dataset == dataset,
        )
    ).first()
    if row is None:
        row = RuleDatasetStatus(
            province_code=province_code,
            year=year,
            batch_code=batch_code,
            exam_type=exam_type,
            dataset=dataset,
        )
        db.add(row)
    row.status = status
    row.note = note
    db.flush()
    return row


def _codes_with_status(
    db: Session, dataset: str, status: str, *, with_batch: bool
) -> set[tuple[Any, ...]]:
    """取该数据集在指定 ``data_status`` 下的 (province_code, year[, batch_code]) 集合。"""
    rows = db.scalars(
        select(RuleDatasetStatus).where(
            RuleDatasetStatus.dataset == dataset,
            RuleDatasetStatus.status == status,
        )
    ).all()
    if with_batch:
        return {(row.province_code, row.year, row.batch_code) for row in rows}
    return {(row.province_code, row.year) for row in rows}


def _reject_manual_available(status: str) -> None:
    """契约 8.8：``available`` 只能由覆盖率校验得出，手工设置直接拒绝。"""
    if status == DATA_STATUS_AVAILABLE:
        raise BizError(
            "参数错误：data_status=available 必须由导入覆盖率/完整性校验得出，不允许手工设置"
        )


def _reject_demo_source(source: Any) -> None:
    """契约 8.8：导入不接受演示来源 ``example.invalid``。"""
    url = str(getattr(source, "source_url", "") or "")
    if DEMO_SOURCE_HOST in url:
        raise BizError(f"参数错误：导入不接受演示来源（含 {DEMO_SOURCE_HOST} 的 URL）")



# --------------------------------------------------------------------------- #
# 省份志愿模式模板
# --------------------------------------------------------------------------- #
def province_rule_item(row: ProvinceExamRule, source: Source | None = None) -> dict[str, Any]:
    return {
        "rule_id": row.id,
        "province_code": row.province_code,
        "province": row.province,
        "year": row.year,
        "batch_code": row.batch_code,
        "batch": row.batch,
        "exam_type": row.exam_type,
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
    db: Session,
    *,
    province_code: str = "",
    province: str = "",
    year: int | None = None,
    batch: str = "",
    data_status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """省份模板列表（契约 8.8）：支持 province_code / year / batch / data_status 过滤。"""
    code, name = _province_pair(province_code, province)
    stmt = select(ProvinceExamRule)
    if code:
        stmt = stmt.where(ProvinceExamRule.province_code == code)
    elif name:
        stmt = stmt.where(ProvinceExamRule.province == name)
    if year:
        stmt = stmt.where(ProvinceExamRule.year == year)
    if batch.strip():
        stmt = stmt.where(ProvinceExamRule.batch_code == batch_code_of(batch))

    rows = list(
        db.scalars(
            stmt.order_by(ProvinceExamRule.province_code.asc(), ProvinceExamRule.year.desc())
        ).all()
    )
    if data_status.strip():
        allowed = _codes_with_status(db, DATASET_PROVINCE_EXAM_RULE, data_status.strip(), with_batch=True)
        rows = [
            row for row in rows
            if (row.province_code, row.year, row.batch_code) in allowed
        ]

    sources = _sources_of(db, [row.source_id for row in rows])
    items = [province_rule_item(row, sources.get(row.source_id)) for row in rows]
    return paginate(items, page, page_size)


def create_province_rule(
    db: Session, payload: Any, admin: AdminUser, *, client_ip: str = ""
) -> dict[str, Any]:
    year, source = _require_year_and_source(db, payload)
    province_code, province_name = _province_pair(payload.province_code, payload.province)
    batch = str(payload.batch).strip()
    batch_code = str(getattr(payload, "batch_code", "") or "").strip() or batch_code_of(batch)
    exam_type = str(getattr(payload, "exam_type", "") or EXAM_TYPE_NORMAL)
    row = ProvinceExamRule(
        province_code=province_code,
        province=province_name,
        year=year,
        batch=batch,
        batch_code=batch_code,
        exam_type=exam_type,
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
        detail={"province_code": province_code, "year": year, "batch_code": batch_code,
                "exam_type": exam_type, "source_name": source.source_name},
        client_ip=client_ip,
    )
    recompute_dataset_status(
        db, DATASET_PROVINCE_EXAM_RULE, province_code, year, batch_code, exam_type
    )
    db.commit()
    return {"rule_id": row.id}


def update_province_rule(
    db: Session, rule_id: int, payload: Any, admin: AdminUser, *, client_ip: str = ""
) -> None:
    row = _load(db, ProvinceExamRule, rule_id, "省份规则")
    year, source = _require_year_and_source(db, payload)
    province_code, province_name = _province_pair(payload.province_code, payload.province)
    batch = str(payload.batch).strip()
    batch_code = str(getattr(payload, "batch_code", "") or "").strip() or batch_code_of(batch)
    exam_type = str(getattr(payload, "exam_type", "") or EXAM_TYPE_NORMAL)
    row.province_code = province_code
    row.province = province_name
    row.year = year
    row.batch = batch
    row.batch_code = batch_code
    row.exam_type = exam_type
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
        detail={"province_code": province_code, "year": year, "batch_code": batch_code},
        client_ip=client_ip,
    )
    recompute_dataset_status(
        db, DATASET_PROVINCE_EXAM_RULE, province_code, year, batch_code, exam_type
    )
    db.commit()


# --------------------------------------------------------------------------- #
# 选科要求
# --------------------------------------------------------------------------- #
def subject_requirement_item(row: SubjectRequirement, source: Source | None = None) -> dict[str, Any]:
    return {
        "rule_id": row.id,
        "province_code": row.province_code,
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
    db: Session,
    *,
    province_code: str = "",
    province: str = "",
    year: int | None = None,
    major_id: int | None = None,
    data_status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    code, name = _province_pair(province_code, province)
    stmt = select(SubjectRequirement)
    if code:
        stmt = stmt.where(SubjectRequirement.province_code == code)
    elif name:
        stmt = stmt.where(SubjectRequirement.province == name)
    if year:
        stmt = stmt.where(SubjectRequirement.year == year)
    if major_id:
        stmt = stmt.where(SubjectRequirement.major_id == major_id)
    rows = list(db.scalars(stmt.order_by(SubjectRequirement.id.asc())).all())
    if data_status.strip():
        allowed = _codes_with_status(db, DATASET_SUBJECT_REQUIREMENT, data_status.strip(), with_batch=False)
        rows = [row for row in rows if (row.province_code, row.year) in allowed]
    sources = _sources_of(db, [row.source_id for row in rows])
    return paginate(
        [subject_requirement_item(row, sources.get(row.source_id)) for row in rows],
        page,
        page_size,
    )


def create_subject_requirement(
    db: Session, payload: Any, admin: AdminUser, *, client_ip: str = ""
) -> dict[str, Any]:
    year, source = _require_year_and_source(db, payload)
    province_code, province_name = _province_pair(payload.province_code, payload.province)
    row = SubjectRequirement(
        province_code=province_code,
        province=province_name,
        year=year,
        batch=str(payload.batch).strip(),
        school_id=payload.school_id,
        group_code=payload.group_code,
        major_id=payload.major_id,
        first_subject=str(payload.first_subject).strip(),
        secondary_subjects=list(payload.secondary_subjects or []),
        logic=payload.logic,
        source_id=source.id,
    )
    db.add(row)
    db.flush()
    audit_service.record_audit(
        db, admin, ACTION_CONSTRAINT_RULE_CREATE,
        target_type="subject_requirement", target_id=row.id,
        detail={"province_code": province_code, "year": year, "major_id": row.major_id,
                "source_name": source.source_name},
        client_ip=client_ip,
    )
    recompute_dataset_status(
        db, DATASET_SUBJECT_REQUIREMENT, province_code, year, batch_code_of(payload.batch)
    )
    db.commit()
    return {"rule_id": row.id}


def update_subject_requirement(
    db: Session, rule_id: int, payload: Any, admin: AdminUser, *, client_ip: str = ""
) -> None:
    row = _load(db, SubjectRequirement, rule_id, "选科要求")
    year, source = _require_year_and_source(db, payload)
    province_code, province_name = _province_pair(payload.province_code, payload.province)
    row.province_code = province_code
    row.province = province_name
    row.year = year
    row.batch = str(payload.batch).strip()
    row.school_id = payload.school_id
    row.group_code = payload.group_code
    row.major_id = payload.major_id
    row.first_subject = str(payload.first_subject).strip()
    row.secondary_subjects = list(payload.secondary_subjects or [])
    row.logic = payload.logic
    row.source_id = source.id
    audit_service.record_audit(
        db, admin, ACTION_CONSTRAINT_RULE_UPDATE,
        target_type="subject_requirement", target_id=rule_id,
        detail={"province_code": province_code, "year": year, "major_id": row.major_id},
        client_ip=client_ip,
    )
    recompute_dataset_status(
        db, DATASET_SUBJECT_REQUIREMENT, province_code, year, batch_code_of(payload.batch)
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
        "province_code": row.province_code,
        "province": row.province,
        "year": row.year,
        "source": _citation_of(source),
    }


def list_physical_restrictions(
    db: Session,
    *,
    province_code: str = "",
    province: str = "",
    year: int | None = None,
    condition: str = "",
    data_status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    code, name = _province_pair(province_code, province)
    stmt = select(PhysicalRestriction)
    if code:
        stmt = stmt.where(
            (PhysicalRestriction.province_code == code) | (PhysicalRestriction.province_code == "")
        )
    elif name:
        stmt = stmt.where(
            (PhysicalRestriction.province == name) | (PhysicalRestriction.province == "")
        )
    if year:
        stmt = stmt.where(PhysicalRestriction.year == year)
    if condition.strip():
        stmt = stmt.where(PhysicalRestriction.condition == condition.strip())
    rows = list(db.scalars(stmt.order_by(PhysicalRestriction.id.asc())).all())
    if data_status.strip():
        allowed = _codes_with_status(db, DATASET_PHYSICAL_RESTRICTION, data_status.strip(), with_batch=False)
        rows = [row for row in rows if (row.province_code, row.year) in allowed]
    sources = _sources_of(db, [row.source_id for row in rows])
    return paginate(
        [physical_restriction_item(row, sources.get(row.source_id)) for row in rows],
        page,
        page_size,
    )


def create_physical_restriction(
    db: Session, payload: Any, admin: AdminUser, *, client_ip: str = ""
) -> dict[str, Any]:
    year, source = _require_year_and_source(db, payload)
    province_code, province_name = _province_pair(payload.province_code, payload.province)
    row = PhysicalRestriction(
        condition=payload.condition.strip(),
        threshold=payload.threshold.strip(),
        major_category=payload.major_category.strip(),
        major_code=payload.major_code.strip(),
        level=payload.level,
        detail=payload.detail,
        province_code=province_code,
        province=province_name,
        year=year,
        source_id=source.id,
    )
    db.add(row)
    db.flush()
    audit_service.record_audit(
        db, admin, ACTION_CONSTRAINT_RULE_CREATE,
        target_type="physical_restriction", target_id=row.id,
        detail={"condition": row.condition, "level": row.level, "year": year,
                "province_code": province_code, "source_name": source.source_name},
        client_ip=client_ip,
    )
    recompute_dataset_status(
        db, DATASET_PHYSICAL_RESTRICTION, province_code, year, batch_code_of(DEFAULT_BATCH)
    )
    db.commit()
    return {"rule_id": row.id}


def update_physical_restriction(
    db: Session, rule_id: int, payload: Any, admin: AdminUser, *, client_ip: str = ""
) -> None:
    row = _load(db, PhysicalRestriction, rule_id, "身体条件限制")
    year, source = _require_year_and_source(db, payload)
    province_code, province_name = _province_pair(payload.province_code, payload.province)
    row.condition = payload.condition.strip()
    row.threshold = payload.threshold.strip()
    row.major_category = payload.major_category.strip()
    row.major_code = payload.major_code.strip()
    row.level = payload.level
    row.detail = payload.detail
    row.province_code = province_code
    row.province = province_name
    row.year = year
    row.source_id = source.id
    audit_service.record_audit(
        db, admin, ACTION_CONSTRAINT_RULE_UPDATE,
        target_type="physical_restriction", target_id=rule_id,
        detail={"condition": row.condition, "level": row.level, "year": year},
        client_ip=client_ip,
    )
    recompute_dataset_status(
        db, DATASET_PHYSICAL_RESTRICTION, province_code, year, batch_code_of(DEFAULT_BATCH)
    )
    db.commit()


# --------------------------------------------------------------------------- #
# 章程要求（契约 8.7 admission_requirement）
# --------------------------------------------------------------------------- #
def admission_requirement_item(
    row: AdmissionRequirement, source: Source | None = None
) -> dict[str, Any]:
    return {
        "rule_id": row.id,
        "province_code": row.province_code,
        "year": row.year,
        "school_id": row.school_id,
        "major_id": row.major_id,
        "requirement_type": row.requirement_type,
        "requirement_value": row.requirement_value or {},
        "level": row.level,
        "detail": row.detail,
        "source": _citation_of(source),
    }


def list_admission_requirements(
    db: Session,
    *,
    province_code: str = "",
    year: int | None = None,
    major_id: int | None = None,
    data_status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    stmt = select(AdmissionRequirement)
    if province_code.strip():
        stmt = stmt.where(AdmissionRequirement.province_code == province_code.strip())
    if year:
        stmt = stmt.where(AdmissionRequirement.year == year)
    if major_id:
        stmt = stmt.where(AdmissionRequirement.major_id == major_id)
    rows = list(db.scalars(stmt.order_by(AdmissionRequirement.id.asc())).all())
    if data_status.strip():
        allowed = _codes_with_status(db, DATASET_ADMISSION_REQUIREMENT, data_status.strip(), with_batch=False)
        rows = [row for row in rows if (row.province_code, row.year) in allowed]
    sources = _sources_of(db, [row.source_id for row in rows])
    return paginate(
        [admission_requirement_item(row, sources.get(row.source_id)) for row in rows],
        page,
        page_size,
    )


def _build_admission_requirement(db: Session, payload: Any, source: Source, year: int) -> dict[str, Any]:
    province_code, _name = _province_pair(payload.province_code, payload.province)
    return {
        "province_code": province_code,
        "year": year,
        "school_id": payload.school_id,
        "major_id": payload.major_id,
        "requirement_type": payload.requirement_type,
        "requirement_value": dict(payload.requirement_value or {}),
        "level": payload.level,
        "detail": payload.detail,
        "source_id": source.id,
    }


def create_admission_requirement(
    db: Session, payload: Any, admin: AdminUser, *, client_ip: str = ""
) -> dict[str, Any]:
    year, source = _require_year_and_source(db, payload)
    row = AdmissionRequirement(**_build_admission_requirement(db, payload, source, year))
    db.add(row)
    db.flush()
    audit_service.record_audit(
        db, admin, ACTION_CONSTRAINT_RULE_CREATE,
        target_type="admission_requirement", target_id=row.id,
        detail={"province_code": row.province_code, "year": year,
                "requirement_type": row.requirement_type, "source_name": source.source_name},
        client_ip=client_ip,
    )
    recompute_dataset_status(
        db, DATASET_ADMISSION_REQUIREMENT, row.province_code, year, batch_code_of(DEFAULT_BATCH)
    )
    db.commit()
    return {"rule_id": row.id}


def update_admission_requirement(
    db: Session, rule_id: int, payload: Any, admin: AdminUser, *, client_ip: str = ""
) -> None:
    row = _load(db, AdmissionRequirement, rule_id, "章程要求")
    year, source = _require_year_and_source(db, payload)
    for field, value in _build_admission_requirement(db, payload, source, year).items():
        setattr(row, field, value)
    audit_service.record_audit(
        db, admin, ACTION_CONSTRAINT_RULE_UPDATE,
        target_type="admission_requirement", target_id=rule_id,
        detail={"province_code": row.province_code, "year": year,
                "requirement_type": row.requirement_type},
        client_ip=client_ip,
    )
    recompute_dataset_status(
        db, DATASET_ADMISSION_REQUIREMENT, row.province_code, year, batch_code_of(DEFAULT_BATCH)
    )
    db.commit()


# --------------------------------------------------------------------------- #
# 专业学费（契约 8.7 major_tuition）
# --------------------------------------------------------------------------- #
def major_tuition_item(row: MajorTuition, source: Source | None = None) -> dict[str, Any]:
    return {
        "rule_id": row.id,
        "province_code": row.province_code,
        "year": row.year,
        "school_id": row.school_id,
        "major_id": row.major_id,
        "amount": row.amount,
        "currency": row.currency,
        "period": row.period,
        "ownership": row.ownership,
        "note": row.note,
        "source": _citation_of(source),
    }


def list_major_tuitions(
    db: Session,
    *,
    province_code: str = "",
    year: int | None = None,
    major_id: int | None = None,
    data_status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    stmt = select(MajorTuition)
    if province_code.strip():
        stmt = stmt.where(MajorTuition.province_code == province_code.strip())
    if year:
        stmt = stmt.where(MajorTuition.year == year)
    if major_id:
        stmt = stmt.where(MajorTuition.major_id == major_id)
    rows = list(db.scalars(stmt.order_by(MajorTuition.id.asc())).all())
    if data_status.strip():
        allowed = _codes_with_status(db, DATASET_MAJOR_TUITION, data_status.strip(), with_batch=False)
        rows = [row for row in rows if (row.province_code, row.year) in allowed]
    sources = _sources_of(db, [row.source_id for row in rows])
    return paginate(
        [major_tuition_item(row, sources.get(row.source_id)) for row in rows], page, page_size
    )


def _build_major_tuition(payload: Any, source: Source, year: int) -> dict[str, Any]:
    province_code, _name = _province_pair(payload.province_code, payload.province)
    return {
        "province_code": province_code,
        "year": year,
        "school_id": payload.school_id,
        "major_id": payload.major_id,
        "amount": payload.amount,
        "currency": payload.currency,
        "period": payload.period,
        "ownership": payload.ownership,
        "note": payload.note,
        "source_id": source.id,
    }


def create_major_tuition(
    db: Session, payload: Any, admin: AdminUser, *, client_ip: str = ""
) -> dict[str, Any]:
    year, source = _require_year_and_source(db, payload)
    row = MajorTuition(**_build_major_tuition(payload, source, year))
    db.add(row)
    db.flush()
    audit_service.record_audit(
        db, admin, ACTION_CONSTRAINT_RULE_CREATE,
        target_type="major_tuition", target_id=row.id,
        detail={"province_code": row.province_code, "year": year, "major_id": row.major_id,
                "amount": row.amount, "source_name": source.source_name},
        client_ip=client_ip,
    )
    recompute_dataset_status(
        db, DATASET_MAJOR_TUITION, row.province_code, year, batch_code_of(DEFAULT_BATCH)
    )
    db.commit()
    return {"rule_id": row.id}


def update_major_tuition(
    db: Session, rule_id: int, payload: Any, admin: AdminUser, *, client_ip: str = ""
) -> None:
    row = _load(db, MajorTuition, rule_id, "专业学费")
    year, source = _require_year_and_source(db, payload)
    for field, value in _build_major_tuition(payload, source, year).items():
        setattr(row, field, value)
    audit_service.record_audit(
        db, admin, ACTION_CONSTRAINT_RULE_UPDATE,
        target_type="major_tuition", target_id=rule_id,
        detail={"province_code": row.province_code, "year": year, "major_id": row.major_id},
        client_ip=client_ip,
    )
    recompute_dataset_status(
        db, DATASET_MAJOR_TUITION, row.province_code, year, batch_code_of(DEFAULT_BATCH)
    )
    db.commit()


# --------------------------------------------------------------------------- #
# 规则集状态（契约 8.7 rule_dataset_status；8.8 GET/PUT）
# --------------------------------------------------------------------------- #
def rule_dataset_status_item(row: RuleDatasetStatus) -> dict[str, Any]:
    return {
        "rule_id": row.id,
        "province_code": row.province_code,
        "year": row.year,
        "batch_code": row.batch_code,
        "exam_type": row.exam_type,
        "dataset": row.dataset,
        "status": row.status,
        "note": row.note,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_rule_dataset_status(
    db: Session,
    *,
    province_code: str = "",
    year: int | None = None,
    batch: str = "",
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    stmt = select(RuleDatasetStatus)
    if province_code.strip():
        stmt = stmt.where(RuleDatasetStatus.province_code == province_code.strip())
    if year:
        stmt = stmt.where(RuleDatasetStatus.year == year)
    if batch.strip():
        stmt = stmt.where(RuleDatasetStatus.batch_code == batch_code_of(batch))
    if status.strip():
        stmt = stmt.where(RuleDatasetStatus.status == status.strip())
    rows = list(db.scalars(stmt.order_by(RuleDatasetStatus.id.asc())).all())
    return paginate([rule_dataset_status_item(row) for row in rows], page, page_size)


def upsert_rule_dataset_status(
    db: Session, payload: Any, admin: AdminUser, *, client_ip: str = ""
) -> dict[str, Any]:
    """更新规则集说明／状态（契约 8.8 ``PUT /rule-dataset-status``）。

    ``status=available`` 会被拒绝（1001）——它只能由导入覆盖率校验自动得出。
    """
    _reject_manual_available(payload.status)
    year = source_guard.require_year(payload.year)
    batch_code = str(payload.batch_code or "").strip() or batch_code_of(DEFAULT_BATCH)
    exam_type = str(payload.exam_type or EXAM_TYPE_NORMAL)
    row = db.scalars(
        select(RuleDatasetStatus).where(
            RuleDatasetStatus.province_code == payload.province_code.strip(),
            RuleDatasetStatus.year == year,
            RuleDatasetStatus.batch_code == batch_code,
            RuleDatasetStatus.exam_type == exam_type,
            RuleDatasetStatus.dataset == payload.dataset,
        )
    ).first()
    if row is None:
        row = RuleDatasetStatus(
            province_code=payload.province_code.strip(),
            year=year,
            batch_code=batch_code,
            exam_type=exam_type,
            dataset=payload.dataset,
        )
        db.add(row)
    row.status = payload.status
    row.note = payload.note
    audit_service.record_audit(
        db, admin, ACTION_CONSTRAINT_RULE_UPDATE,
        target_type="rule_dataset_status", target_id=row.id,
        detail={"province_code": row.province_code, "year": year,
                "dataset": row.dataset, "status": row.status},
        client_ip=client_ip,
    )
    db.commit()
    return {"rule_id": row.id, "status": row.status}


# --------------------------------------------------------------------------- #
# 批量导入（契约 8.8 POST /rule-datasets/import）
# --------------------------------------------------------------------------- #
#: dataset → (模型, 该逻辑表的字段构造器名)
_IMPORT_BUILDERS: dict[str, str] = {
    DATASET_PROVINCE_EXAM_RULE: "province_exam_rule",
    DATASET_SUBJECT_REQUIREMENT: "subject_requirement",
    DATASET_PHYSICAL_RESTRICTION: "physical_restriction",
    DATASET_ADMISSION_REQUIREMENT: "admission_requirement",
    DATASET_MAJOR_TUITION: "major_tuition",
}


def _item_source(db: Session, item: Mapping[str, Any], default_year: int):
    """从导入项读取来源三要素并 upsert（契约 8.8：不接受来源缺失与演示来源）。"""
    year = int(item.get("year") or default_year or 0)
    source_guard.require_source(item.get("source_name"), item.get("source_url"), year)
    stub = type(
        "SourceStub",
        (),
        {
            "source_name": item.get("source_name"),
            "source_url": item.get("source_url"),
            "year": year,
            "source_type": item.get("source_type"),
        },
    )()
    _reject_demo_source(stub)
    return year, source_guard.ensure_source(db, stub)


def _build_import_row(
    db: Session, dataset: str, item: Mapping[str, Any], payload: Any
) -> Any:
    """把一条导入项构造成对应模型（不落库；校验失败抛异常 → 整批回滚）。"""
    year, source = _item_source(db, item, payload.year)
    province_code = str(item.get("province_code") or payload.province_code).strip()
    batch_code = str(item.get("batch_code") or payload.batch_code or "").strip() or batch_code_of(DEFAULT_BATCH)
    exam_type = str(item.get("exam_type") or payload.exam_type or EXAM_TYPE_NORMAL)

    if dataset == DATASET_PROVINCE_EXAM_RULE:
        batch = str(item.get("batch") or batch_code)
        return ProvinceExamRule(
            province_code=province_code,
            province=str(item.get("province") or province_name_of(province_code)),
            year=year,
            batch=batch,
            batch_code=batch_code,
            exam_type=exam_type,
            mode=str(item.get("mode") or "group"),
            volunteer_count=int(item.get("volunteer_count") or 0),
            majors_per_group=item.get("majors_per_group"),
            has_adjust=bool(item.get("has_adjust")),
            admit_method=str(item.get("admit_method") or "parallel"),
            ratio=str(item.get("ratio") or "1:1"),
            tie_rule=str(item.get("tie_rule") or ""),
            mutex_groups=list(item.get("mutex_groups") or []),
            collect_count=item.get("collect_count"),
            source_id=source.id,
        )
    if dataset == DATASET_SUBJECT_REQUIREMENT:
        return SubjectRequirement(
            province_code=province_code,
            province=str(item.get("province") or province_name_of(province_code)),
            year=year,
            batch=str(item.get("batch") or ""),
            school_id=item.get("school_id"),
            group_code=item.get("group_code"),
            major_id=item.get("major_id"),
            first_subject=str(item.get("first_subject") or ""),
            secondary_subjects=list(item.get("secondary_subjects") or []),
            logic=str(item.get("logic") or "all"),
            source_id=source.id,
        )
    if dataset == DATASET_PHYSICAL_RESTRICTION:
        return PhysicalRestriction(
            condition=str(item.get("condition") or ""),
            threshold=str(item.get("threshold") or ""),
            major_category=str(item.get("major_category") or ""),
            major_code=str(item.get("major_code") or ""),
            level=str(item.get("level") or ""),
            detail=str(item.get("detail") or ""),
            province_code=province_code,
            province=str(item.get("province") or province_name_of(province_code)),
            year=year,
            source_id=source.id,
        )
    if dataset == DATASET_ADMISSION_REQUIREMENT:
        return AdmissionRequirement(
            province_code=province_code,
            year=year,
            school_id=item.get("school_id"),
            major_id=item.get("major_id"),
            requirement_type=str(item.get("requirement_type") or ""),
            requirement_value=dict(item.get("requirement_value") or {}),
            level=str(item.get("level") or "reject"),
            detail=str(item.get("detail") or ""),
            source_id=source.id,
        )
    if dataset == DATASET_MAJOR_TUITION:
        amount = item.get("amount")
        return MajorTuition(
            province_code=province_code,
            year=year,
            school_id=item.get("school_id"),
            major_id=item.get("major_id"),
            amount=None if amount is None else float(amount),
            currency=str(item.get("currency") or "CNY"),
            period=str(item.get("period") or "year"),
            ownership=str(item.get("ownership") or ""),
            note=str(item.get("note") or ""),
            source_id=source.id,
        )
    raise BizError(f"参数错误：不支持的 dataset：{dataset}")


def import_rule_dataset(
    db: Session, payload: Any, admin: AdminUser, *, client_ip: str = ""
) -> dict[str, Any]:
    """批量导入规则项（契约 8.8）：单次 ≤500，全批事务，任一项失败整批回滚。

    两段式：先**全量构造并校验**（不落库），再统一 ``add``；任一项抛错即回滚。
    """
    if payload.dataset not in _IMPORT_BUILDERS:
        raise BizError(f"参数错误：dataset 只能是 {' / '.join(DATASET_VALUES)}")
    items = list(payload.items or [])
    if len(items) > 500:
        raise BizError("参数错误：单次导入不得超过 500 条")
    if not items:
        raise BizError("参数错误：items 不能为空")

    try:
        rows = [_build_import_row(db, payload.dataset, item, payload) for item in items]
        for row in rows:
            db.add(row)
        db.flush()
        recompute_dataset_status(
            db,
            payload.dataset,
            payload.province_code.strip(),
            int(payload.year or 0),
            str(payload.batch_code or "").strip() or batch_code_of(DEFAULT_BATCH),
            str(payload.exam_type or EXAM_TYPE_NORMAL),
        )
    except Exception:
        db.rollback()
        raise

    audit_service.record_audit(
        db, admin, ACTION_CONSTRAINT_RULE_CREATE,
        target_type=f"rule_dataset:{payload.dataset}", target_id=0,
        detail={"province_code": payload.province_code, "year": payload.year,
                "created": len(rows)},
        client_ip=client_ip,
    )
    db.commit()
    return {
        "dataset": payload.dataset,
        "created": len(rows),
        "updated": 0,
        "rejected": 0,
        "errors": [],
    }
