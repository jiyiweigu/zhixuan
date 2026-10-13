"""志愿方案的保存 / 命名 / 编辑 / 删除接口（tasks.md 6.6，产品书 6.1.7）。

契约说明：docs/api-contract.md 第 5 节只定义了 POST /api/plans（方案生成，由
app/api/v1/plans.py 实现）；本文件的 5 个 /api/user/plans 接口依据产品书 6.1.7
新增，已在 PR 描述中提请队长补入契约（变更流程见 api-contract.md 末节）。

鉴权：产品书 6.1.7 标注 Auth: yes，全部接口要求登录：
- 未登录 / 令牌失效 → code 1002（get_current_user 抛出）；
- 访问他人方案 → code 1003（服务层校验归属）；
- 方案不存在 → code 1001。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.response import ok
from app.db.session import get_db
from app.models.user import User
from app.schemas.core import SavedPlanWrite
from app.services import user_plans as user_plans_service

router = APIRouter(prefix="/user/plans", tags=["志愿方案管理"])


@router.get("", summary="我的方案列表")
def list_saved_plans(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """返回当前用户已保存的方案摘要（最近更新在前），不含 items。"""
    return ok({"items": user_plans_service.list_plans(db, user.id)})


@router.post("", summary="保存方案")
def create_saved_plan(
    payload: SavedPlanWrite,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """保存一套方案（命名 + 倾向 + 志愿条目），返回新方案的 plan_id。"""
    return ok(user_plans_service.create_plan(db, user.id, payload))


@router.get("/{plan_id}", summary="打开方案")
def get_saved_plan(
    plan_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """重新打开已保存的方案，逐字段还原保存时的内容。"""
    return ok(user_plans_service.get_plan(db, user.id, plan_id))


@router.put("/{plan_id}", summary="重命名或编辑方案")
def update_saved_plan(
    plan_id: str,
    payload: SavedPlanWrite,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """整体替换方案内容，改名与改条目共用；编辑后同时刷新 updated_at。"""
    user_plans_service.update_plan(db, user.id, plan_id, payload)
    return ok(None)


@router.delete("/{plan_id}", summary="删除方案")
def delete_saved_plan(
    plan_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """删除方案；再次打开同一 plan_id 将返回 1001。"""
    user_plans_service.delete_plan(db, user.id, plan_id)
    return ok(None)
