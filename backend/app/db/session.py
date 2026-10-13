"""数据库引擎与会话（tasks.md 1.4）。

默认 SQLite：本地零安装即可跑通，且与 PostgreSQL 共用同一套 SQLAlchemy 2.0 模型与
Alembic 迁移；切换 PostgreSQL 只需设置 ZHIXUAN_DATABASE_URL（见 backend/.env.example）。

注意：数据表的唯一创建入口是 alembic 迁移
（``cd backend && .venv/Scripts/alembic upgrade head``）。
本模块的 ``create_all`` 仅供"零迁移快速起临时库"使用，默认不启用
（见 ZHIXUAN_AUTO_CREATE_TABLES）：它会抢先建表且不写 alembic_version，
导致随后的 alembic 迁移报 "table already exists"。
所有结构变更（加字段、改类型、加索引）都必须写成 alembic 迁移。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.base import Base

_SQLITE_PREFIX = "sqlite:///"


def sqlite_path(url: str) -> Path | None:
    """若为文件型 SQLite，返回其路径；内存库或非 SQLite 返回 None。"""
    if not url.startswith(_SQLITE_PREFIX):
        return None
    raw = url[len(_SQLITE_PREFIX) :]
    if not raw or raw.startswith(":memory:") or raw.startswith("file:"):
        return None
    return Path(raw)


def prepare_database() -> None:
    """SQLite 首次运行时创建数据库文件所在目录。"""
    path = sqlite_path(settings.database_url)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)


prepare_database()

_connect_args = (
    {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
)

engine = create_engine(
    settings.database_url,
    future=True,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：每个请求一个会话，请求结束即释放。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all() -> None:
    """创建缺失的表。

    ⚠️ 仅供"零迁移快速起临时库"使用，默认不启用。常规开发与生产一律用
    alembic 迁移建表（见模块文档字符串）：本函数不会写入 alembic_version，
    先跑它会让随后的 ``alembic upgrade head`` 因 "table already exists" 失败。
    """
    from app import models  # noqa: F401  确保模型已注册到 Base.metadata

    Base.metadata.create_all(engine)


def drop_all() -> None:
    """删除全部表（仅测试使用）。"""
    from app import models  # noqa: F401

    Base.metadata.drop_all(engine)
