"""途径与资格规则维护接口（产品书 6.6.6–6.6.8；tasks.md 8.6）。

- ``GET/POST /pathways``、``PUT /pathways/{pathway_id}``   途径字典维护
- ``GET/POST /pathway-rules``、``PUT /pathway-rules/{rule_id}``  资格规则维护（**强制附来源**）
- ``GET /pathway-regions``                                专项实施区域名单（只读）

「未填来源无法保存规则」是 8.6 的验收条件：新增 / 修改规则时
``source`` 三要素缺一即返回 4001，规则不入库（见 services/source_guard.py）。

产品书 6.6 把写方法写成 ``GET/POST/PUT /pathways``，未给出 PUT 的资源定位方式；
本实现采用 REST 惯例 ``PUT /pathways/{id}`` 与 ``PUT /pathway-rules/{id}``，
已在 PR 描述中提请队长确认。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_admin
from app.core.response import ok
from app.db.session import get_db
from app.models.knowledge import AdminUser
from app.schemas.admin import PathwayRuleWriteRequest, PathwayWriteRequest
from app.services import pathway_admin as pathway_admin_service

router = APIRouter(tags=["管理端·途径与规则"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


# --------------------------------------------------------------------------- #
# 途径字典
# --------------------------------------------------------------------------- #
@router.get("/pathways", summary="途径字典列表")
def list_pathways(
    category: str = Query(default="", description="按分类过滤"),
    priority: str = Query(default="", description="按优先级过滤：P0 / P1 / P2"),
    data_status: str = Query(default="", description="按数据状态过滤：ready / planned"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        pathway_admin_service.list_pathways(
            db, category=category, priority=priority, data_status=data_status
        )
    )


@router.post("/pathways", summary="新建途径")
def create_pathway(
    payload: PathwayWriteRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ok(pathway_admin_service.create_pathway(db, payload, admin, client_ip=_client_ip(request)))


@router.put("/pathways/{pathway_id}", summary="修改途径")
def update_pathway(
    pathway_id: str,
    payload: PathwayWriteRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    pathway_admin_service.update_pathway(
        db, pathway_id, payload, admin, client_ip=_client_ip(request)
    )
    return ok(None)


# --------------------------------------------------------------------------- #
# 资格规则
# --------------------------------------------------------------------------- #
@router.get("/pathway-rules", summary="资格规则列表")
def list_rules(
    pathway_id: str = Query(default="", description="按途径过滤"),
    province: str = Query(default="", description="按适用省份过滤"),
    rule_type: str = Query(default="", description="按规则类型过滤：户籍 / 学籍 / 区域 / 成绩"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    items = pathway_admin_service.list_rules(
        db, pathway_id=pathway_id, province=province, rule_type=rule_type
    )
    return ok({"items": items})


@router.post("/pathway-rules", summary="新建资格规则（强制附来源）")
def create_rule(
    payload: PathwayRuleWriteRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """缺来源 → 4001；途径不存在 → 1001。"""
    return ok(pathway_admin_service.create_rule(db, payload, admin, client_ip=_client_ip(request)))


@router.put("/pathway-rules/{rule_id}", summary="修改资格规则（强制附来源）")
def update_rule(
    rule_id: int,
    payload: PathwayRuleWriteRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """缺来源 → 4001；规则或途径不存在 → 1001。"""
    pathway_admin_service.update_rule(db, rule_id, payload, admin, client_ip=_client_ip(request))
    return ok(None)


# --------------------------------------------------------------------------- #
# 专项实施区域（只读）
# --------------------------------------------------------------------------- #
@router.get("/pathway-regions", summary="专项实施区域名单")
def list_regions(
    pathway_id: str = Query(default="", description="按途径过滤"),
    province: str = Query(default="", description="按省份过滤"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ok({"items": pathway_admin_service.list_regions(db, pathway_id=pathway_id, province=province)})
