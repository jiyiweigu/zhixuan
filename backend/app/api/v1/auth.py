"""认证接口：注册 / 登录 / 退出 / 当前用户。

契约：docs/api-contract.md 第 1 节。
其中 /logout 与 /me 为新增接口，已在 PR 描述中提请补入契约。

口令不落日志：本模块只接收 payload，不打印任何字段（tasks.md 3.1 验证项）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_claims, get_current_user
from app.core.response import ok
from app.db.session import get_db
from app.models.user import User
from app.schemas.core import Credentials
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", summary="注册")
def register(payload: Credentials, db: Session = Depends(get_db)) -> dict[str, Any]:
    """注册并直接返回登录态（契约字段：user_id / username / access_token）。"""
    return ok(auth_service.register(payload, db))


@router.post("/login", summary="登录")
def login(
    payload: Credentials,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """登录失败按「用户名 + 客户端」计数限流（tasks.md 3.2）。"""
    client = request.client.host if request.client else ""
    return ok(auth_service.login(payload, db, client))


@router.post("/logout", summary="退出登录")
def logout(claims: dict[str, Any] = Depends(get_current_claims)) -> dict[str, Any]:
    """吊销当前令牌（jti 写入吊销名单，直至自然过期）。"""
    auth_service.logout(claims)
    return ok(None, "已退出登录")


@router.get("/me", summary="当前登录用户")
def me(user: User = Depends(get_current_user)) -> dict[str, Any]:
    """供前端刷新页面后恢复登录态，避免每次都读档案。"""
    return ok(auth_service.public_user(user))
