"""口令哈希、访问令牌与会话失效（tasks.md 3.1、3.2、3.3）。

口令
----
- 算法：PBKDF2-HMAC-SHA256，每个用户一份随机盐（16 字节）。
- 存储编码：``pbkdf2_sha256$<迭代次数>$<盐 urlsafe-b64>$<摘要 urlsafe-b64>``，
  自描述格式便于日后提升迭代次数而无需迁移数据。
- 校验：``hmac.compare_digest`` 常数时间比较，避免时序侧信道。
- 数据库中不存在任何明文口令；日志只记录用户名与 trace_id（见 app/api/v1/auth.py）。

访问令牌
--------
- JWT(HS256)，密钥来自 ``ZHIXUAN_SECRET_KEY``；载荷含 ``sub``（用户 ID）、
  ``username``、``iat``、``exp``、``jti``。
- 失效：``/api/auth/logout`` 把当前令牌的 ``jti`` 写入吊销名单，直至其自然过期；
  账号注销后用户查不到，令牌同样立即失效（见 app/services/auth.py）。
- **管理端令牌**（tasks.md 8.1）：与 C 端共用签名密钥，但额外带 ``typ=admin``，
  ``sub`` 形如 ``admin:<id>``。``get_current_admin`` 校验 ``typ``，因此 C 端令牌
  不能访问管理端接口（返回 1003），管理端令牌也不会被 ``get_current_user`` 认作 C 端用户。

已知边界：吊销名单为进程内实现，多进程/多实例部署时应改为数据库或 Redis 存储。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from typing import Any

import jwt

from app.core.config import settings
from app.core.response import BizCode, BizError

HASH_NAME = "pbkdf2_sha256"
SALT_BYTES = 16
TOKEN_ALGORITHM = "HS256"

# 管理端令牌标记（tasks.md 8.1）：载荷 typ=admin，sub 形如 admin:<id>
ADMIN_TOKEN_TYPE = "admin"
ADMIN_SUBJECT_PREFIX = "admin:"

# 用户不存在时也执行一次哈希校验，避免通过响应耗时区分"用户是否存在"
_DUMMY_HASH = (
    "pbkdf2_sha256$1000$AAAAAAAAAAAAAAAAAAAAAA$"
    "Y2FsaWJyYXRpb24tb25seS1ub3QtYS1yZWFsLWhhc2g"
)


# --------------------------------------------------------------------------- #
# 口令
# --------------------------------------------------------------------------- #
def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str, iterations: int | None = None) -> str:
    """生成加盐哈希（数据库只存这个字符串，不存明文）。"""
    rounds = iterations or settings.password_iterations
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return f"{HASH_NAME}${rounds}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    """校验口令；编码格式非法或算法不符时返回 False，不抛异常。"""
    try:
        name, rounds, salt, digest = encoded.split("$")
        if name != HASH_NAME:
            return False
        expected = _unb64(digest)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), _unb64(salt), int(rounds)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(expected, actual)


def burn_password_check(password: str) -> None:
    """用户不存在时调用，使登录失败耗时与口令错误时接近。"""
    verify_password(password, _DUMMY_HASH)


# --------------------------------------------------------------------------- #
# 访问令牌
# --------------------------------------------------------------------------- #
class _RevocationList:
    """已吊销令牌（jti）名单，过期项自动清理。线程安全。"""

    def __init__(self) -> None:
        self._expires: dict[str, int] = {}
        self._lock = threading.Lock()

    def revoke(self, jti: str, exp: int) -> None:
        if not jti:
            return
        with self._lock:
            self._purge(int(time.time()))
            self._expires[jti] = int(exp)

    def contains(self, jti: str) -> bool:
        if not jti:
            return False
        with self._lock:
            self._purge(int(time.time()))
            return jti in self._expires

    def clear(self) -> None:
        with self._lock:
            self._expires.clear()

    def _purge(self, now: int) -> None:
        expired = [key for key, exp in self._expires.items() if exp <= now]
        for key in expired:
            self._expires.pop(key, None)


REVOKED_TOKENS = _RevocationList()


def create_access_token(
    user_id: str, username: str, ttl_minutes: int | None = None
) -> tuple[str, dict[str, Any]]:
    """签发访问令牌，返回 (token, 载荷)。"""
    now = int(time.time())
    ttl = ttl_minutes if ttl_minutes is not None else settings.access_token_ttl_minutes
    claims: dict[str, Any] = {
        "sub": user_id,
        "username": username,
        "iat": now,
        "exp": now + ttl * 60,
        "jti": secrets.token_hex(16),
    }
    token = jwt.encode(claims, settings.secret_key, algorithm=TOKEN_ALGORITHM)
    return token, claims


def create_admin_token(
    admin_id: int, username: str, role: str, ttl_minutes: int | None = None
) -> tuple[str, dict[str, Any]]:
    """签发管理端访问令牌（tasks.md 8.1）。载荷额外带 ``typ=admin`` 与 ``role``。"""
    now = int(time.time())
    ttl = ttl_minutes if ttl_minutes is not None else settings.access_token_ttl_minutes
    claims: dict[str, Any] = {
        "sub": f"{ADMIN_SUBJECT_PREFIX}{admin_id}",
        "username": username,
        "role": role,
        "typ": ADMIN_TOKEN_TYPE,
        "iat": now,
        "exp": now + ttl * 60,
        "jti": secrets.token_hex(16),
    }
    token = jwt.encode(claims, settings.secret_key, algorithm=TOKEN_ALGORITHM)
    return token, claims


def admin_id_from_subject(subject: str) -> int | None:
    """从 ``admin:<id>`` 形式的 sub 取出管理员主键；格式不符返回 None。"""
    if not subject.startswith(ADMIN_SUBJECT_PREFIX):
        return None
    raw = subject[len(ADMIN_SUBJECT_PREFIX) :]
    return int(raw) if raw.isdigit() else None


def decode_access_token(token: str) -> dict[str, Any]:
    """解析并校验令牌；任何异常都转成统一的"未登录"业务错误（code 1002）。"""
    try:
        claims = jwt.decode(token, settings.secret_key, algorithms=[TOKEN_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise BizError("登录已过期，请重新登录", BizCode.UNAUTHORIZED) from None
    except jwt.InvalidTokenError:
        raise BizError("登录状态无效，请重新登录", BizCode.UNAUTHORIZED) from None

    if REVOKED_TOKENS.contains(str(claims.get("jti") or "")):
        raise BizError("登录已失效，请重新登录", BizCode.UNAUTHORIZED)
    return claims


def revoke_token(claims: dict[str, Any]) -> None:
    """退出登录：吊销单个令牌。"""
    REVOKED_TOKENS.revoke(str(claims.get("jti") or ""), int(claims.get("exp") or 0))


def token_ttl_seconds() -> int:
    return settings.access_token_ttl_minutes * 60
