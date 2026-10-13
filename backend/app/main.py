"""应用入口。

统一响应包与全局异常处理见 app/core/response.py，契约见 docs/api-contract.md。
数据表结构见 app/models/，变更一律通过 alembic 迁移（tasks.md 1.4）。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router
from app.core.config import MIN_SECRET_KEY_BYTES, settings
from app.core.response import register_exception_handlers

logger = logging.getLogger("zhixuan")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """启动时提示未替换的默认密钥；数据表由 alembic 迁移创建。"""
    if settings.auto_create_tables:
        logger.warning(
            "ZHIXUAN_AUTO_CREATE_TABLES 已开启：启动时会直接建表，"
            "将与 alembic 迁移冲突（迁移会报 table already exists）。"
            "生产与常规开发请保持关闭，并在启动前执行："
            "cd backend && .venv/Scripts/alembic upgrade head"
        )
        from app.db.session import create_all

        create_all()
    if settings.secret_key_is_default:
        logger.warning(
            "ZHIXUAN_SECRET_KEY 仍为默认值，部署前请通过环境变量替换（见 backend/.env.example）"
        )
    elif settings.secret_key_too_short:
        logger.warning(
            "ZHIXUAN_SECRET_KEY 短于 %d 字节，HS256 安全性下降，建议替换为更长的随机值",
            MIN_SECRET_KEY_BYTES,
        )
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    debug=settings.debug,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
app.include_router(router)
