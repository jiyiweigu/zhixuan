"""认证业务逻辑（tasks.md 3.1、3.2、3.3）。

- 注册：用户名唯一（重复 → 1006）；口令只存 PBKDF2 加盐哈希，表结构无明文字段；
- 登录：口令错误与用户不存在返回同一文案，避免用户名枚举；用户不存在时同样执行一次
  哈希校验，使耗时接近，避免通过响应时间区分；
- 限流：按「用户名 + 客户端」滑动窗口计数，达阈值 → 1008（app/core/ratelimit.py）；
- 退出：吊销当前令牌（jti）；
- 注销：匿名化处理，档案行删除、用户保留 ID 但无法再登录。

日志只记录用户名与用户 ID，绝不记录口令（tasks.md 3.1 验证项）。
"""

from __future__ import annotations

import logging
import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.ratelimit import DEFAULT_LIMITER, FailureLimiter
from app.core.response import BizCode, BizError
from app.core.security import (
    burn_password_check,
    create_access_token,
    hash_password,
    revoke_token,
    token_ttl_seconds,
    verify_password,
)
from app.db.base import utcnow
from app.models.profile import Profile
from app.models.user import USER_STATUS_ACTIVE, USER_STATUS_DELETED, User
from app.schemas.core import Credentials

logger = logging.getLogger("zhixuan.auth")

USER_ID_PREFIX = "u_"
CREDENTIAL_ERROR_MESSAGE = "用户名或密码错误"


def new_user_id() -> str:
    """生成用户 ID，形如 u_1a2b3c4d5e6f。"""
    return f"{USER_ID_PREFIX}{secrets.token_hex(6)}"


def normalize_username(username: str) -> str:
    return username.strip()


def find_user(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username))


def get_active_user(db: Session, user_id: str) -> User | None:
    """按 ID 取"仍然有效"的用户；已注销用户返回 None，令牌随之失效。"""
    if not user_id:
        return None
    user = db.get(User, user_id)
    if user is None or user.status != USER_STATUS_ACTIVE:
        return None
    return user


def session_payload(user: User) -> dict[str, Any]:
    """注册/登录的统一响应体（契约字段 user_id / username / access_token）。"""
    token, _claims = create_access_token(user.id, user.username)
    return {
        "user_id": user.id,
        "username": user.username,
        "access_token": token,
        "token_type": "bearer",
        "expires_in": token_ttl_seconds(),
        "is_admin": user.is_admin,
    }


def public_user(user: User) -> dict[str, Any]:
    """对外暴露的用户信息（不含任何凭据）。"""
    return {"user_id": user.id, "username": user.username, "is_admin": user.is_admin}


def register(payload: Credentials, db: Session) -> dict[str, Any]:
    """注册新用户，并同步建立一份空档案。"""
    username = normalize_username(payload.username)
    if find_user(db, username) is not None:
        raise BizError("用户名已存在，请更换", BizCode.USERNAME_EXISTS)

    user = User(
        id=new_user_id(),
        username=username,
        password_hash=hash_password(payload.password),
        status=USER_STATUS_ACTIVE,
    )
    user.profile = Profile()
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # 并发注册同名用户时由唯一约束兜底
        db.rollback()
        raise BizError("用户名已存在，请更换", BizCode.USERNAME_EXISTS) from None

    logger.info("注册成功 username=%s user_id=%s", user.username, user.id)
    return session_payload(user)


def login(
    payload: Credentials,
    db: Session,
    client: str = "",
    limiter: FailureLimiter | None = None,
) -> dict[str, Any]:
    """登录：失败计数达阈值即限流（tasks.md 3.2）。"""
    guard = limiter or DEFAULT_LIMITER
    username = normalize_username(payload.username)
    guard.ensure_allowed(username, client)

    user = find_user(db, username)
    if user is None:
        burn_password_check(payload.password)

    if (
        user is None
        or user.status != USER_STATUS_ACTIVE
        or not verify_password(payload.password, user.password_hash)
    ):
        remaining = guard.record_failure(username, client)
        logger.warning(
            "登录失败 username=%s client=%s 剩余尝试次数=%s", username, client, remaining
        )
        raise BizError(CREDENTIAL_ERROR_MESSAGE, BizCode.UNAUTHORIZED)

    guard.reset(username, client)
    user.last_login_at = utcnow()
    db.commit()
    logger.info("登录成功 username=%s user_id=%s", user.username, user.id)
    return session_payload(user)


def logout(claims: dict[str, Any]) -> None:
    """退出登录：把当前令牌的 jti 写入吊销名单。"""
    revoke_token(claims)


def delete_account(db: Session, user: User, password: str) -> None:
    """账号注销（tasks.md 3.3）：删除档案、匿名化账号，保留 ID 供审计。"""
    if not verify_password(password, user.password_hash):
        raise BizError("密码校验未通过，已取消注销", BizCode.UNAUTHORIZED)

    profile = db.get(Profile, user.id)
    if profile is not None:
        db.delete(profile)

    user.status = USER_STATUS_DELETED
    user.deleted_at = utcnow()
    user.username = f"deleted_{user.id}"  # 脱敏，同时保持唯一约束
    user.password_hash = hash_password(secrets.token_urlsafe(32))  # 置为不可用口令
    db.commit()
    logger.info("账号已注销 user_id=%s", user.id)
