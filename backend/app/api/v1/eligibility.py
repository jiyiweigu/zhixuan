"""报考约束接口（产品书 6.2.6–6.2.9）。

- ``GET  /api/provinces/{code}/rules``      省份志愿模式模板（6.2.6）
- ``POST /api/eligibility/check``           批量资格校验，游客可用（6.2.7）
- ``POST /api/user/eligibility/check``      同上，需登录，可写回档案（6.2.8）
- ``GET  /api/majors/{id}/requirements``   专业选科 / 身体 / 学费一次取全（6.2.9）

判定逻辑全部在 ``app/engine/constraints.py``（纯函数）；本层只做参数解析与调用。
规则数据缺失 → ``3001``，不得静默放行（8.5）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.response import ok
from app.db.session import get_db
from app.models.user import User
from app.schemas.constraints import EligibilityCheckRequest
from app.services import constraints as constraint_service

# 无前缀：路径按产品书原样书写
router = APIRouter(tags=["报考约束"])
# 登录态校验单独挂在 /user 下（6.2.8）
user_router = APIRouter(prefix="/user", tags=["报考约束"])


@router.get("/provinces/{code}/rules", summary="省份志愿模式模板")
def get_province_rules(
    code: str,
    year: int | None = Query(default=None, ge=2000, le=2100, description="规则年份"),
    batch: str = Query(default="本科批", max_length=32),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """省份志愿模式模板（6.2.6）：方案生成器与志愿表渲染的唯一依据。"""
    resolved_year = year or constraint_service.resolve_year(db, code)
    return ok(constraint_service.province_rules(db, code, resolved_year, batch))


@router.post("/eligibility/check", summary="志愿单位批量资格校验（游客可用）")
def check_eligibility(
    payload: EligibilityCheckRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """整张志愿表一次扫（6.2.7）：≤100 个志愿单位，逐条返回三档结果。"""
    return ok(constraint_service.check_eligibility(db, payload))


@user_router.post("/eligibility/check", summary="志愿单位批量资格校验（登录，可写回档案）")
def check_eligibility_logged_in(
    payload: EligibilityCheckRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """同 6.2.7，额外返回 ``updated_profile``（写回 accept_adjustment 等字段）。"""
    return ok(constraint_service.check_eligibility(db, payload, user=user))


@router.get("/majors/{major_id}/requirements", summary="专业选科 / 身体 / 学费要求")
def get_major_requirements(
    major_id: int,
    province: str = Query(default="河南", max_length=20),
    year: int | None = Query(default=None, ge=2000, le=2100),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """专业要求一次取全（6.2.9），避免前端拼接多个接口。"""
    resolved_year = year or constraint_service.resolve_year(db, province)
    return ok(constraint_service.major_requirements(db, major_id, province, resolved_year))
