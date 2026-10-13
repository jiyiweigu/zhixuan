"""志愿方案接口。

契约：docs/api-contract.md 第 5 节（Auth: yes）。
响应中 strategy / priority / tiers / quota / shortage / excluded / risks / summary /
data_status / disclaimer 为新增字段，已在 PR 描述中提请补入契约。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.response import ok
from app.db.session import get_db
from app.models.user import User
from app.schemas.core import PlanRequest
from app.services import plans as plans_service
from app.services import profile as profile_service

router = APIRouter(prefix="/plans", tags=["志愿方案"])


@router.post("", summary="生成志愿方案")
def create_plan(
    payload: PlanRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """生成冲—稳—保方案，标注每档依据并给出风险预警（tasks.md 6.3、6.4、6.5）。

    契约标注该接口 Auth: yes，故需登录；登录用户若未显式提供 strategy / priority /
    偏好专业 / 偏好城市 / 是否服从调剂，则沿用档案中保存的偏好（tasks.md 3.5）。
    """
    saved = profile_service.get_saved(db, user.id)
    merged = profile_service.merge_saved(
        payload,
        profile_service.saved_preferences(saved),
        profile_service.PREFERENCE_FIELDS,
    )
    return ok(plans_service.build_plan(PlanRequest(**merged)))
