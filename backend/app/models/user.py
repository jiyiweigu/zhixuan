"""用户表（tasks.md 3.1、3.3）。

设计要点：
- 只保存 ``password_hash``（PBKDF2-HMAC-SHA256 加盐哈希），表结构上不存在明文口令字段；
- 注销采用"匿名化"而非物理删除（tasks.md 3.3）：status 置为 deleted、用户名脱敏、
  口令哈希替换为随机值、档案行删除，既满足"数据被删除或匿名化"，
  又保留用户 ID 以满足日志与审计的可追溯性。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow
from app.models.profile import Profile

USER_STATUS_ACTIVE = "active"
USER_STATUS_DELETED = "deleted"

USERNAME_MAX_LENGTH = 50
PASSWORD_HASH_MAX_LENGTH = 255
USER_ID_MAX_LENGTH = 64


class User(Base):
    """平台用户。"""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(USER_ID_MAX_LENGTH), primary_key=True, comment="用户 ID，形如 u_xxxx"
    )
    username: Mapped[str] = mapped_column(
        String(USERNAME_MAX_LENGTH), unique=True, index=True, comment="登录用户名，唯一"
    )
    password_hash: Mapped[str] = mapped_column(
        String(PASSWORD_HASH_MAX_LENGTH), comment="PBKDF2 加盐哈希，禁止存放明文"
    )
    status: Mapped[str] = mapped_column(
        String(16), default=USER_STATUS_ACTIVE, comment="active / deleted"
    )
    is_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="管理端鉴权预留（tasks.md 8.1）"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    profile: Mapped["Profile | None"] = relationship(
        cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<User {self.username} status={self.status}>"
