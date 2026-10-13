"""报考约束接口（产品书 6.2.6–6.2.9；契约 8.3–8.6）。

- ``GET  /api/provinces/{code}/rules``      省份志愿模式模板（契约 8.3）
- ``POST /api/eligibility/check``           批量资格校验，游客可用（契约 8.4）
- ``POST /api/user/eligibility/check``      同上，需登录，可写回档案（契约 8.5）
- ``GET  /api/majors/{id}/requirements``   专业选科 / 身体 / 学费一次取全（契约 8.6）

判定逻辑全部在 ``app/engine/constraints.py``（纯函数）；本层只做参数解析与调用。
规则数据缺失 → 校验接口返回 ``3001``，不得静默放行；只读接口如实返回
``data_status`` / ``missing_rule_sets``。

入参口径（契约 8.3/8.6）：``code`` 与 ``province`` 均为**两位省级行政区划代码**
（河南 ``41``、江西 ``36``）。服务层兼容历史入参的省名，避免老调用方直接失败。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.response import ok
from app.db.session import get_db
from app.models.constants import BATCH_DISPLAY_UG, EXAM_TYPE_NORMAL
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
    year: int = Query(..., ge=2000, le=2100, description="规则年份（必填）"),
    batch: str = Query(default=BATCH_DISPLAY_UG, max_length=32, description="批次展示名，如 本科批"),
    exam_type: str = Query(default=EXAM_TYPE_NORMAL, max_length=8, description="普通 / 艺术 / 体育"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """省份志愿模式模板（契约 8.3）：方案生成器与志愿表渲染的唯一依据。

    ``code`` 为两位省代码（河南 ``41`` / 江西 ``36``）。无对应版本时仍返回 200，
    ``data_status: unavailable``、``rule: null``，不返回虚构模板。
    """
    return ok(constraint_service.province_rules(db, code, year, batch, exam_type=exam_type))


@router.post("/eligibility/check", summary="志愿单位批量资格校验（游客可用）")
def check_eligibility(
    payload: EligibilityCheckRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """整张志愿表一次扫（契约 8.4）：≤100 个志愿单位，逐条返回三档结果。"""
    return ok(constraint_service.check_eligibility(db, payload))


@user_router.post("/eligibility/check", summary="志愿单位批量资格校验（登录，可写回档案）")
def check_eligibility_logged_in(
    payload: EligibilityCheckRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """同 8.4，额外返回 ``updated_profile``（写回 accept_adjustment 等字段，契约 8.5）。"""
    return ok(constraint_service.check_eligibility(db, payload, user=user))


@router.get("/majors/{major_id}/requirements", summary="专业选科 / 身体 / 学费要求")
def get_major_requirements(
    major_id: int,
    province: str = Query(..., max_length=20, description="两位省级行政区划代码，如 41"),
    year: int = Query(..., ge=2000, le=2100, description="规则年份（必填）"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """专业要求一次取全（契约 8.6），避免前端拼接多个接口。"""
    return ok(constraint_service.major_requirements(db, major_id, province, year))
