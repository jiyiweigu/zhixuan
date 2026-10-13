"""考生档案接口。

契约：docs/api-contract.md 第 2 节（Auth: yes）。
DELETE /api/user 为新增接口（账号注销，tasks.md 3.3），已在 PR 描述中提请补入契约。

说明：契约中"考生档案"两个接口本来就标注 Auth: yes，此前的演示实现不做校验；
本 PR 起按契约要求校验令牌，未带令牌返回 code 1002。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.response import ok
from app.db.session import get_db
from app.models.user import User
from app.schemas.core import DeleteAccountRequest, ProfileRequest
from app.services import auth as auth_service
from app.services import profile as profile_service

router = APIRouter(prefix="/user", tags=["考生档案"])


@router.get("/profile", summary="读取考生档案")
def get_profile(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """读取档案；首次访问自动建立空档案。"""
    return ok(profile_service.get_or_create(db, user.id))


@router.put("/profile", summary="保存考生档案")
def update_profile(
    payload: ProfileRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """保存档案：只更新请求中显式提供的字段（未提供的字段保持原值）。

    非法分数（如 751）由 Pydantic 拦截并返回 code 1001（tasks.md 3.4 验证项）。
    """
    return ok(profile_service.save(db, user.id, payload))


@router.delete("", summary="账号注销")
def delete_account(
    payload: DeleteAccountRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """注销账号（tasks.md 3.3）：删除档案、匿名化账号、令牌立即失效。

    需二次校验口令：仅凭被盗令牌无法直接销号。
    """
    auth_service.delete_account(db, user, payload.password)
    return ok(None, "账号已注销，相关数据已删除或匿名化")
