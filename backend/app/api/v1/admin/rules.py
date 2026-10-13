"""管理端·报考约束规则维护（产品书 6.6；v1.1 新增三组）。

- ``GET/POST /province-rules``           ``PUT /province-rules/{id}``
- ``GET/POST /subject-requirements``     ``PUT /subject-requirements/{id}``
- ``GET/POST /physical-restrictions``    ``PUT /physical-restrictions/{id}``

三组都**必须带 ``year``**（2025 / 2026 并存），缺 year 或来源 → 4001（6.6 / 7.6）。
写方法沿用 REST 惯例 ``PUT /xxx/{id}``（与 admin/pathways.py 一致）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_admin
from app.core.response import ok
from app.db.session import get_db
from app.models.knowledge import AdminUser
from app.schemas.admin import (
    PhysicalRestrictionWriteRequest,
    ProvinceRuleWriteRequest,
    SubjectRequirementWriteRequest,
)
from app.services import rule_admin as rule_admin_service

router = APIRouter(tags=["管理端·报考约束规则"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


# --------------------------------------------------------------------------- #
# 省份志愿模式模板
# --------------------------------------------------------------------------- #
@router.get("/province-rules", summary="省份志愿模式模板列表")
def list_province_rules(
    province: str = Query(default=""),
    year: int | None = Query(default=None, ge=2000, le=2100),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ok({"items": rule_admin_service.list_province_rules(db, province=province, year=year)})


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
@router.get("/subject-requirements", summary="选科要求列表")
def list_subject_requirements(
    province: str = Query(default=""),
    year: int | None = Query(default=None, ge=2000, le=2100),
    major_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        {
            "items": rule_admin_service.list_subject_requirements(
                db, province=province, year=year, major_id=major_id
            )
        }
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
@router.get("/physical-restrictions", summary="身体条件限制列表")
def list_physical_restrictions(
    province: str = Query(default=""),
    year: int | None = Query(default=None, ge=2000, le=2100),
    condition: str = Query(default=""),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        {
            "items": rule_admin_service.list_physical_restrictions(
                db, province=province, year=year, condition=condition
            )
        }
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
