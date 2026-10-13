"""管理端登录与会话（产品书 6.6.1；tasks.md 8.1）。

- ``POST /login``：公开接口，校验 admin_user 表账号，成功返回 ``{token, admin}``
  并**写一条登录留痕**；失败按「admin:用户名 + 客户端」限流（与 C 端计数隔离）。
- ``GET /me``：供管理端刷新页面后恢复会话，需管理员令牌。

安全：登录请求体与响应体都不落日志；日志只记录用户名与 admin_id（见 admin_auth）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_admin
from app.core.response import ok
from app.db.session import get_db
from app.models.audit import ACTION_ADMIN_LOGIN
from app.models.knowledge import AdminUser
from app.schemas.admin import AdminCredentials
from app.services import admin_auth as admin_auth_service
from app.services import audit as audit_service

router = APIRouter(tags=["管理端·认证"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


@router.post("/login", summary="管理端登录")
def login(
    payload: AdminCredentials,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """校验管理端账号并签发管理员令牌（载荷带 typ=admin）。"""
    client = _client_ip(request)
    admin = admin_auth_service.authenticate(payload, db, client)

    audit_service.record_audit(
        db,
        admin,
        ACTION_ADMIN_LOGIN,
        target_type="admin",
        target_id=admin.id,
        detail={"role": admin.role},
        client_ip=client,
    )
    db.commit()
    return ok(admin_auth_service.session_payload(admin))


@router.get("/me", summary="当前管理端账号")
def me(admin: AdminUser = Depends(get_current_admin)) -> dict[str, Any]:
    return ok(admin_auth_service.public_admin(admin))
