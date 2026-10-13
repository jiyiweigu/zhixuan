"""Alembic 运行环境（tasks.md 1.4）。

- 连接串只从应用配置读取（ZHIXUAN_DATABASE_URL），本目录不保存任何凭证；
- target_metadata 取自 app/db/base.py 的 Base，模型改动可被 --autogenerate 检出；
- SQLite 下开启 render_as_batch，绕开其 ALTER TABLE 能力不足的问题。
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

# 让 alembic 能 import app.*（无论从哪个目录调用）
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import models  # noqa: E402,F401  导入即把所有模型注册到 Base.metadata
from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _configure(**kwargs: object) -> None:
    context.configure(
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=settings.database_url.startswith("sqlite"),
        **kwargs,
    )


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL，不连接数据库。"""
    _configure(url=settings.database_url, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：直接对目标库执行迁移。"""
    connectable = create_engine(settings.database_url, poolclass=pool.NullPool, future=True)
    with connectable.connect() as connection:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
