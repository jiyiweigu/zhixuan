"""志愿方案保存 / 命名 / 编辑 / 删除（tasks.md 6.6，产品书 6.1.7）。

与方案生成（app/services/plans.py）分属两层：生成是纯计算、不落库；
本模块只负责把用户确认后的方案持久化，并在重新打开时逐字段还原。

设计要点：
- 一个用户可保存多套方案，全部按 ``user_id`` 归属；跨用户访问一律拒绝，
  受保护接口已由 get_current_user 保证登录（未登录 1002），这里再兜一层 1003；
- ``items`` 原样存 JSON，不做结构改写：生成接口输出的条目结构可能随 6.3/6.4/6.5 演进，
  透传可保证"重新打开与保存时一致"，也避免两处结构各自漂移；
- 列表只回摘要（不含 items），避免列表接口随方案体量膨胀；
- 方案 ID 形如 ``plan_xxxxxxxxxxxx``，与 users.id 同风格（见 app/services/auth.py）。
"""

from __future__ import annotations

import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.response import BizCode, BizError
from app.db.base import utcnow
from app.models.user_data import UserPlan

PLAN_ID_PREFIX = "plan_"
PLAN_NAME_MAX_LENGTH = 100


def new_plan_id() -> str:
    """生成方案 ID，形如 plan_1a2b3c4d5e6f。"""
    return f"{PLAN_ID_PREFIX}{secrets.token_hex(6)}"


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def summary(plan: UserPlan) -> dict[str, Any]:
    """列表项（产品书 6.1.7 GET /api/user/plans 的 items[]）。"""
    return {
        "plan_id": plan.id,
        "name": plan.name,
        "strategy": plan.strategy,
        "item_count": len(plan.items or []),
        "created_at": _iso(plan.created_at),
        "updated_at": _iso(plan.updated_at),
    }


def detail(plan: UserPlan) -> dict[str, Any]:
    """详情（产品书 6.1.7 GET /api/user/plans/{id}，含完整 items）。"""
    return {
        "plan_id": plan.id,
        "name": plan.name,
        "strategy": plan.strategy,
        "items": list(plan.items or []),
        "created_at": _iso(plan.created_at),
        "updated_at": _iso(plan.updated_at),
    }


def list_plans(db: Session, user_id: str) -> list[dict[str, Any]]:
    """当前用户的方案列表，最近更新的在前。"""
    plans = db.scalars(
        select(UserPlan)
        .where(UserPlan.user_id == user_id)
        .order_by(UserPlan.updated_at.desc(), UserPlan.id.desc())
    ).all()
    return [summary(plan) for plan in plans]


def load_owned(db: Session, user_id: str, plan_id: str) -> UserPlan:
    """按 ID 取方案并校验归属。

    不存在 → 1001；属于他人 → 1003（而非 1001）。两者区分开，
    既让本人拿到明确提示，也不把他人的方案 ID 是否存在暴露给越权方。
    """
    plan = db.get(UserPlan, plan_id)
    if plan is None:
        raise BizError("方案不存在或已被删除", BizCode.PARAM_ERROR)
    if plan.user_id != user_id:
        raise BizError("无权访问该方案", BizCode.FORBIDDEN)
    return plan


def get_plan(db: Session, user_id: str, plan_id: str) -> dict[str, Any]:
    """重新打开一套已保存的方案。"""
    return detail(load_owned(db, user_id, plan_id))


def create_plan(db: Session, user_id: str, payload: Any) -> dict[str, Any]:
    """保存新方案，返回 plan_id（产品书 6.1.7 POST /api/user/plans）。"""
    data = payload.model_dump()
    plan = UserPlan(
        id=new_plan_id(),
        user_id=user_id,
        name=str(data["name"]).strip()[:PLAN_NAME_MAX_LENGTH],
        strategy=str(data.get("strategy") or "稳"),
        items=list(data.get("items") or []),
    )
    db.add(plan)
    db.commit()
    return {"plan_id": plan.id}


def update_plan(db: Session, user_id: str, plan_id: str, payload: Any) -> None:
    """重命名 / 编辑方案（产品书 6.1.7 PUT /api/user/plans/{id}）。

    请求体与保存一致（整体替换），因此改名与改条目共用同一入口。
    """
    plan = load_owned(db, user_id, plan_id)
    data = payload.model_dump()
    plan.name = str(data["name"]).strip()[:PLAN_NAME_MAX_LENGTH]
    plan.strategy = str(data.get("strategy") or plan.strategy)
    plan.items = list(data.get("items") or [])
    plan.updated_at = utcnow()
    db.commit()


def delete_plan(db: Session, user_id: str, plan_id: str) -> None:
    """删除方案（产品书 6.1.7 DELETE /api/user/plans/{id}）。"""
    plan = load_owned(db, user_id, plan_id)
    db.delete(plan)
    db.commit()
