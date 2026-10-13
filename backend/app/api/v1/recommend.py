"""冲稳保推荐与方案风险体检接口。

契约：docs/api-contract.md 6.1 节。

- ``POST /api/recommend``        Auth: no   按省份 / 科目 / 分数位次返回冲稳保推荐，不落库；
- ``POST /api/plan/risk-check``  Auth: yes  对调用方给出的志愿条目做风险体检，**不重新生成**方案。

两者与 ``POST /api/plans`` 共用 ``app/services/plans.py`` 的分档、排序与风险规则，
因此三处结论口径必然一致；差异只在于鉴权与是否落库。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user
from app.core.response import ok
from app.models.user import User
from app.schemas.core import RecommendRequest, RiskCheckRequest
from app.services import plans as plans_service

router = APIRouter(tags=["推荐与风险体检"])


@router.post("/recommend", summary="冲稳保推荐（游客可用，不落库）")
def recommend(payload: RecommendRequest) -> dict[str, Any]:
    """契约 6.1：Auth no；结果必须带来源与免责声明（由 build_plan 统一附加）。"""
    return ok(plans_service.build_plan(payload.to_plan_request()))


@router.post("/plan/risk-check", summary="志愿方案风险体检")
def risk_check(
    payload: RiskCheckRequest,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """契约 6.1：Auth yes；请求 ``{profile, items[]}``，返回 ``{risks[]}``。

    每条风险含级别、类型、目标、说明与规则来源；无风险时返回空数组，不返回无来源的结论。
    """
    return ok({"risks": plans_service.check_risks(payload.profile, payload.items)})
