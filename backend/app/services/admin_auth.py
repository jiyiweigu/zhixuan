"""管理端认证与账号（tasks.md 8.1；产品书 6.6.1）。

与 C 端认证（app/services/auth.py）的关系：
- **分表**：管理端账号存 ``admin_user``（产品书 7.5），C 端存 ``users``，互不复用；
- **分令牌**：管理端令牌额外带 ``typ=admin``（见 app/core/security.py），
  因此 C 端令牌访问管理端接口会被 ``get_current_admin`` 判为 1003（权限不足），
  管理端令牌也不会被 ``get_current_user`` 认作 C 端用户；
- **分限流键**：失败计数以 ``admin:<用户名>`` 为键，与 C 端同名用户互不影响。

口令沿用 PBKDF2 加盐哈希，``admin_user`` 表结构上同样不存在明文字段。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.ratelimit import DEFAULT_LIMITER, FailureLimiter
from app.core.response import BizCode, BizError
from app.core.security import (
    ADMIN_TOKEN_TYPE,
    create_admin_token,
    hash_password,
    verify_password,
)
from app.models.knowledge import AdminUser

logger = logging.getLogger("zhixuan.admin")

ADMIN_ROLE_ADMIN = "admin"
ADMIN_ROLE_REVIEWER = "reviewer"
ADMIN_ROLES = (ADMIN_ROLE_ADMIN, ADMIN_ROLE_REVIEWER)

ADMIN_USERNAME_MAX_LENGTH = 50
CREDENTIAL_ERROR_MESSAGE = "用户名或密码错误"


def normalize_username(username: str) -> str:
    return username.strip()


def limiter_key(username: str) -> str:
    """管理端限流键加 ``admin:`` 前缀，与 C 端登录失败计数隔离。"""
    return f"{ADMIN_TOKEN_TYPE}:{normalize_username(username).lower()}"


def find_admin(db: Session, username: str) -> AdminUser | None:
    return db.scalar(select(AdminUser).where(AdminUser.username == normalize_username(username)))


def get_active_admin(db: Session, admin_id: int) -> AdminUser | None:
    """按主键取管理员；不存在返回 None。"""
    return db.get(AdminUser, admin_id)


def public_admin(admin: AdminUser) -> dict[str, Any]:
    """管理端会话中的账号信息（产品书 6.6.1 响应字段 admin）。"""
    return {"admin_id": admin.id, "username": admin.username, "role": admin.role}


def session_payload(admin: AdminUser) -> dict[str, Any]:
    """登录响应包（产品书 6.6.1：``{ token, admin: {...} }``）。"""
    token, _claims = create_admin_token(admin.id, admin.username, admin.role)
    return {"token": token, "token_type": "bearer", "admin": public_admin(admin)}


def authenticate(
    payload: Any,
    db: Session,
    client: str = "",
    limiter: FailureLimiter | None = None,
) -> AdminUser:
    """校验管理端凭据并返回账号；失败抛 1002，触发限流抛 1008。

    用户名不存在与口令错误返回同一文案，避免账号枚举；只做校验与限流，
    **不签发令牌、不提交事务**，留痕与响应由接口层负责（便于登录留痕与响应同一事务）。
    """
    guard = limiter or DEFAULT_LIMITER
    username = normalize_username(payload.username)
    key = limiter_key(username)
    guard.ensure_allowed(key, client)

    admin = find_admin(db, username)
    if admin is None or not verify_password(payload.password, admin.password_hash):
        remaining = guard.record_failure(key, client)
        logger.warning(
            "管理端登录失败 username=%s client=%s 剩余尝试次数=%s", username, client, remaining
        )
        raise BizError(CREDENTIAL_ERROR_MESSAGE, BizCode.UNAUTHORIZED)

    guard.reset(key, client)
    logger.info("管理端登录成功 username=%s admin_id=%s", admin.username, admin.id)
    return admin


def create_admin(
    db: Session,
    username: str,
    password: str,
    role: str = ADMIN_ROLE_ADMIN,
    *,
    commit: bool = True,
) -> AdminUser:
    """创建管理端账号（引导脚本与测试使用）。用户名冲突 → 1006。"""
    name = normalize_username(username)[:ADMIN_USERNAME_MAX_LENGTH]
    if not name:
        raise BizError("管理员用户名不能为空")
    if role not in ADMIN_ROLES:
        raise BizError(f"管理员角色只能是 {' / '.join(ADMIN_ROLES)}")

    admin = AdminUser(username=name, password_hash=hash_password(password), role=role)
    db.add(admin)
    try:
        if commit:
            db.commit()
        else:
            db.flush()
    except IntegrityError:
        db.rollback()
        raise BizError("管理员用户名已存在，请更换", BizCode.USERNAME_EXISTS) from None
    return admin


def ensure_admin(
    db: Session, username: str, password: str, role: str = ADMIN_ROLE_ADMIN
) -> tuple[AdminUser, bool]:
    """存在即返回，不存在则创建；返回 (账号, 是否新建)。用于幂等引导。"""
    existing = find_admin(db, username)
    if existing is not None:
        return existing, False
    return create_admin(db, username, password, role), True
