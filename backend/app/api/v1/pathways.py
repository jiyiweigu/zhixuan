"""升学途径目录、路径资格自检、专项实施区域判定与途径区域名单接口。

契约：docs/api-contract.md 第 3 节（``/pathways``、``/pathways/{id}``、
``/pathways/region-check``、``/pathways/eligibility-check``）与
6.1 节（``/pathways/{id}/regions``）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_optional_user
from app.core.response import BizError, ok
from app.db.session import get_db
from app.models.user import User
from app.schemas.core import EligibilityRequest
from app.services import eligibility as eligibility_service
from app.services import pathways as pathways_service
from app.services import profile as profile_service

router = APIRouter(prefix="/pathways", tags=["升学途径"])


@router.get("", summary="升学途径目录")
def list_pathways(
    category: str | None = Query(default=None, description="按分类过滤，如 专项计划"),
    priority: str | None = Query(default=None, description="按优先级过滤：P0 / P1 / P2"),
    status: str | None = Query(default=None, description="按状态过滤，如 数据规划中"),
) -> dict[str, Any]:
    return ok(
        pathways_service.list_pathways(category=category, priority=priority, status=status)
    )


@router.get("/region-check", summary="专项实施区域判定")
def region_check(
    province: str = Query(default="河南", description="省份"),
    county: str = Query(default="", description="县名"),
) -> dict[str, Any]:
    """按省份与县名返回所属专项实施范围（tasks.md 4.3）。"""
    return ok(eligibility_service.check_region(province, county))


@router.post("/eligibility-check", summary="路径资格自检")
def eligibility_check(
    payload: EligibilityRequest,
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """游客可用（tasks.md 4.5）。判定由确定性规则引擎完成，不含模型参与（design.md D6）。

    已登录时，请求中未显式提供的户籍 / 学籍 / 专项标记会回落到档案中保存的值，
    因此档案里标记过专项的用户无需重复填写（tasks.md 3.5）。
    """
    if user is None:
        return ok(eligibility_service.evaluate(payload))

    saved = profile_service.get_saved(db, user.id)
    merged = profile_service.merge_saved(payload, saved, profile_service.ELIGIBILITY_FIELDS)
    return ok(eligibility_service.evaluate(EligibilityRequest(**merged)))


@router.get("/{pathway_id}/regions", summary="途径实施区域名单")
def pathway_regions(
    pathway_id: str,
    province: str = Query(default="", description="按省份过滤，缺省返回全部试点省份"),
) -> dict[str, Any]:
    """契约 6.1：Auth no；仅专项计划类途径有实施区域名单，其余返回 ``unavailable``。

    名单未核验时如实返回 ``data_status: schema_only``，不输出可报考结论。
    """
    if pathways_service.get_pathway(pathway_id) is None:
        raise BizError(f"途径不存在：{pathway_id}")
    return ok(pathways_service.regions_of(pathway_id, province))


@router.get("/{pathway_id}", summary="升学途径详情")
def get_pathway(pathway_id: str) -> dict[str, Any]:
    detail = pathways_service.get_pathway(pathway_id)
    if detail is None:
        raise BizError(f"途径不存在：{pathway_id}")
    return ok(detail)
