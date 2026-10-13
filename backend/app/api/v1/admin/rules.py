"""管理端·报考约束规则维护（产品书 6.6；契约 8.7 / 8.8 的七组）。

- ``GET/POST /province-rules``            ``PUT /province-rules/{rule_id}``
- ``GET/POST /subject-requirements``      ``PUT /subject-requirements/{rule_id}``
- ``GET/POST /physical-restrictions``     ``PUT /physical-restrictions/{rule_id}``
- ``GET/POST /admission-requirements``    ``PUT /admission-requirements/{rule_id}``
- ``GET/POST /major-tuition``             ``PUT /major-tuition/{rule_id}``
- ``GET/PUT  /rule-dataset-status``
- ``POST     /rule-datasets/import``

所有规则**必须带 ``year``**（2025 / 2026 并存），缺 year 或来源 → 4001（6.6 / 7.6）；
``data_status=available`` 不允许手工设置（契约 8.8），由导入覆盖率校验自动得出。
GET 统一返回分页 ``{items, total, page, page_size}``，支持
``province_code`` / ``year`` / ``batch`` / ``data_status`` 过滤。
写方法沿用 REST 惯例 ``PUT /xxx/{rule_id}``（与 admin/pathways.py 一致）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_admin
from app.core.response import ok
from app.db.session import get_db
from app.models.constants import EXAM_TYPE_NORMAL
from app.models.knowledge import AdminUser
from app.schemas.admin import (
    AdmissionRequirementWriteRequest,
    MajorTuitionWriteRequest,
    PhysicalRestrictionWriteRequest,
    ProvinceRuleWriteRequest,
    RuleDatasetImportRequest,
    RuleDatasetStatusWriteRequest,
    SubjectRequirementWriteRequest,
)
from app.services import rule_admin as rule_admin_service

router = APIRouter(tags=["管理端·报考约束规则"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _page(page: int, page_size: int) -> dict[str, int]:
    return {"page": page, "page_size": page_size}


# --------------------------------------------------------------------------- #
# 省份志愿模式模板
# --------------------------------------------------------------------------- #
@router.get("/province-rules", summary="省份志愿模式模板列表（分页）")
def list_province_rules(
    province_code: str = Query(default="", description="两位省代码，如 41"),
    province: str = Query(default="", description="省名，如 河南"),
    year: int | None = Query(default=None, ge=2000, le=2100),
    batch: str = Query(default="", description="批次展示名或 batch_code"),
    data_status: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        rule_admin_service.list_province_rules(
            db, province_code=province_code, province=province, year=year,
            batch=batch, data_status=data_status, **_page(page, page_size),
        )
    )


@router.post("/province-rules", summary="新建省份志愿模式模板（必须带 year + 来源）")
def create_province_rule(
    payload: ProvinceRuleWriteRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """缺 year 或来源 → 4001。"""
    return ok(rule_admin_service.create_province_rule(db, payload, admin, client_ip=_client_ip(request)))


@router.put("/province-rules/{rule_id}", summary="修改省份志愿模式模板")
def update_province_rule(
    rule_id: int,
    payload: ProvinceRuleWriteRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rule_admin_service.update_province_rule(
        db, rule_id, payload, admin, client_ip=_client_ip(request)
    )
    return ok(None)


# --------------------------------------------------------------------------- #
# 选科要求
# --------------------------------------------------------------------------- #
@router.get("/subject-requirements", summary="选科要求列表（分页）")
def list_subject_requirements(
    province_code: str = Query(default=""),
    province: str = Query(default=""),
    year: int | None = Query(default=None, ge=2000, le=2100),
    major_id: int | None = Query(default=None),
    data_status: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        rule_admin_service.list_subject_requirements(
            db, province_code=province_code, province=province, year=year,
            major_id=major_id, data_status=data_status, **_page(page, page_size),
        )
    )


@router.post("/subject-requirements", summary="新建选科要求（必须带 year + 来源）")
def create_subject_requirement(
    payload: SubjectRequirementWriteRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        rule_admin_service.create_subject_requirement(db, payload, admin, client_ip=_client_ip(request))
    )


@router.put("/subject-requirements/{rule_id}", summary="修改选科要求")
def update_subject_requirement(
    rule_id: int,
    payload: SubjectRequirementWriteRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rule_admin_service.update_subject_requirement(
        db, rule_id, payload, admin, client_ip=_client_ip(request)
    )
    return ok(None)


# --------------------------------------------------------------------------- #
# 身体条件限制
# --------------------------------------------------------------------------- #
@router.get("/physical-restrictions", summary="身体条件限制列表（分页）")
def list_physical_restrictions(
    province_code: str = Query(default=""),
    province: str = Query(default=""),
    year: int | None = Query(default=None, ge=2000, le=2100),
    condition: str = Query(default=""),
    data_status: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        rule_admin_service.list_physical_restrictions(
            db, province_code=province_code, province=province, year=year,
            condition=condition, data_status=data_status, **_page(page, page_size),
        )
    )


@router.post("/physical-restrictions", summary="新建身体条件限制（level 仅 reject/not_suitable）")
def create_physical_restriction(
    payload: PhysicalRestrictionWriteRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        rule_admin_service.create_physical_restriction(db, payload, admin, client_ip=_client_ip(request))
    )


@router.put("/physical-restrictions/{rule_id}", summary="修改身体条件限制")
def update_physical_restriction(
    rule_id: int,
    payload: PhysicalRestrictionWriteRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rule_admin_service.update_physical_restriction(
        db, rule_id, payload, admin, client_ip=_client_ip(request)
    )
    return ok(None)


# --------------------------------------------------------------------------- #
# 章程要求（契约 8.8）
# --------------------------------------------------------------------------- #
@router.get("/admission-requirements", summary="章程要求列表（分页）")
def list_admission_requirements(
    province_code: str = Query(default=""),
    year: int | None = Query(default=None, ge=2000, le=2100),
    major_id: int | None = Query(default=None),
    data_status: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        rule_admin_service.list_admission_requirements(
            db, province_code=province_code, year=year, major_id=major_id,
            data_status=data_status, **_page(page, page_size),
        )
    )


@router.post("/admission-requirements", summary="新建章程要求（单科/语种/性别/面试/政审/体测）")
def create_admission_requirement(
    payload: AdmissionRequirementWriteRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        rule_admin_service.create_admission_requirement(db, payload, admin, client_ip=_client_ip(request))
    )


@router.put("/admission-requirements/{rule_id}", summary="修改章程要求")
def update_admission_requirement(
    rule_id: int,
    payload: AdmissionRequirementWriteRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rule_admin_service.update_admission_requirement(
        db, rule_id, payload, admin, client_ip=_client_ip(request)
    )
    return ok(None)


# --------------------------------------------------------------------------- #
# 专业学费（契约 8.8）
# --------------------------------------------------------------------------- #
@router.get("/major-tuition", summary="专业学费列表（分页）")
def list_major_tuitions(
    province_code: str = Query(default=""),
    year: int | None = Query(default=None, ge=2000, le=2100),
    major_id: int | None = Query(default=None),
    data_status: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        rule_admin_service.list_major_tuitions(
            db, province_code=province_code, year=year, major_id=major_id,
            data_status=data_status, **_page(page, page_size),
        )
    )


@router.post("/major-tuition", summary="新建专业学费（按省/年/院校/专业）")
def create_major_tuition(
    payload: MajorTuitionWriteRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        rule_admin_service.create_major_tuition(db, payload, admin, client_ip=_client_ip(request))
    )


@router.put("/major-tuition/{rule_id}", summary="修改专业学费")
def update_major_tuition(
    rule_id: int,
    payload: MajorTuitionWriteRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rule_admin_service.update_major_tuition(
        db, rule_id, payload, admin, client_ip=_client_ip(request)
    )
    return ok(None)


# --------------------------------------------------------------------------- #
# 规则集状态（契约 8.8 GET/PUT）
# --------------------------------------------------------------------------- #
@router.get("/rule-dataset-status", summary="规则集 data_status 列表（分页）")
def list_rule_dataset_status(
    province_code: str = Query(default=""),
    year: int | None = Query(default=None, ge=2000, le=2100),
    batch: str = Query(default=""),
    data_status: str = Query(default="", description="按状态过滤"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        rule_admin_service.list_rule_dataset_status(
            db, province_code=province_code, year=year, batch=batch,
            status=data_status, **_page(page, page_size),
        )
    )


@router.put("/rule-dataset-status", summary="更新规则集说明/状态（available 不允许手工设置）")
def upsert_rule_dataset_status(
    payload: RuleDatasetStatusWriteRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """``status=available`` 提交会被拒（1001），只能由导入覆盖率校验自动得出（契约 8.8）。"""
    return ok(
        rule_admin_service.upsert_rule_dataset_status(
            db, payload, admin, client_ip=_client_ip(request)
        )
    )


# --------------------------------------------------------------------------- #
# 批量导入（契约 8.8 POST）
# --------------------------------------------------------------------------- #
@router.post("/rule-datasets/import", summary="批量导入规则 JSON（≤500 条，整批事务）")
def import_rule_dataset(
    payload: RuleDatasetImportRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """任一项校验失败整批回滚；成功后按覆盖率重算对应的 ``rule_dataset_status``。"""
    return ok(
        rule_admin_service.import_rule_dataset(db, payload, admin, client_ip=_client_ip(request))
    )
