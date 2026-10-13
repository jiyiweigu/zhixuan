"""请求依赖：解析 Authorization: Bearer 令牌并加载当前用户（tasks.md 3.2）。

三类依赖，对应契约中的三种接口：
- ``get_current_user``   受保护接口（Auth: yes）—— 无令牌或令牌无效一律返回 code 1002；
- ``get_optional_user``  游客可用接口（Auth: optional/no）—— 令牌缺失或失效时按游客处理，
  例如 4.5 游客自检与 4.2 的登录用户增强；
- ``get_current_admin``  管理端接口（Auth: admin，tasks.md 8.1）—— 缺令牌 1002，
  持有 C 端用户令牌（无 typ=admin）则 1003 权限不足，正是 M0-5 要求的
  「user 访问 admin 返回 1003」。

令牌校验失败与令牌缺失对受保护接口是同一种结果（1002），
错误文案区分"未登录"与"登录已过期/无效"，便于前端决定是否跳登录页。
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.response import BizCode, BizError
from app.core.security import ADMIN_TOKEN_TYPE, admin_id_from_subject, decode_access_token
from app.db.session import get_db
from app.models.knowledge import AdminUser
from app.models.user import User
from app.services import admin_auth as admin_auth_service
from app.services import auth as auth_service


def bearer_token(authorization: str | None = Header(default=None)) -> str | None:
    """从 Authorization 头取出 Bearer 令牌；缺失或格式不符返回 None。"""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.strip().lower() != "bearer":
        return None
    return token.strip() or None


def get_current_claims(token: str | None = Depends(bearer_token)) -> dict[str, Any]:
    """仅校验令牌本身（退出登录用，不需要加载用户）。"""
    if not token:
        raise BizError("未登录，请先登录后再访问", BizCode.UNAUTHORIZED)
    return decode_access_token(token)


def get_current_user(
    token: str | None = Depends(bearer_token),
    db: Session = Depends(get_db),
) -> User:
    """受保护接口依赖：返回当前登录用户，否则抛 1002。"""
    if not token:
        raise BizError("未登录，请先登录后再访问", BizCode.UNAUTHORIZED)
    claims = decode_access_token(token)
    user = auth_service.get_active_user(db, str(claims.get("sub") or ""))
    if user is None:
        raise BizError("登录状态无效，请重新登录", BizCode.UNAUTHORIZED)
    return user


def get_optional_user(
    token: str | None = Depends(bearer_token),
    db: Session = Depends(get_db),
) -> User | None:
    """游客可用接口依赖：令牌缺失或失效时返回 None（按游客处理）。"""
    if not token:
        return None
    try:
        claims = decode_access_token(token)
    except BizError:
        return None
    return auth_service.get_active_user(db, str(claims.get("sub") or ""))


def get_current_admin(
    token: str | None = Depends(bearer_token),
    db: Session = Depends(get_db),
) -> AdminUser:
    """管理端接口依赖（tasks.md 8.1）。

    - 无令牌 / 令牌无效过期 → 1002；
    - 令牌有效但不是管理端令牌（缺少 ``typ=admin``，即 C 端用户令牌）→ 1003；
    - 管理端令牌对应的账号已不存在 → 1002。
    """
    if not token:
        raise BizError("未登录，请先登录后再访问", BizCode.UNAUTHORIZED)
    claims = decode_access_token(token)
    if str(claims.get("typ") or "") != ADMIN_TOKEN_TYPE:
        raise BizError("需要管理员权限", BizCode.FORBIDDEN)

    admin_id = admin_id_from_subject(str(claims.get("sub") or ""))
    admin = admin_auth_service.get_active_admin(db, admin_id) if admin_id else None
    if admin is None:
        raise BizError("登录状态无效，请重新登录", BizCode.UNAUTHORIZED)
    return admin
