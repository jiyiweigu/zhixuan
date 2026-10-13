"""ORM 基类。

约定：所有模型继承 Base；结构变更一律走 alembic 迁移（tasks.md 1.4）。
元数据采用显式命名约定，使 SQLite 与 PostgreSQL 生成的约束名一致，便于迁移比对。
时间统一按 naive UTC 存储，展示层再本地化。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    """当前 UTC 时间（naive，避免 SQLite 与 PostgreSQL 的时区行为差异）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)
