"""应用配置。

所有可调项集中从环境变量读取，代码里不硬编码地址与密钥。
环境变量样例见 backend/.env.example。
"""

from __future__ import annotations

import os
from pathlib import Path

# backend/ 目录（本文件位于 backend/app/core/config.py）
BACKEND_DIR = Path(__file__).resolve().parents[2]

DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
# 开发用占位密钥。HS256 的密钥建议不少于 32 字节（RFC 7518 §3.2），
# 故占位值本身就是 32 字节以上的字符串，避免本地开发时安全库持续告警。
DEFAULT_SECRET_KEY = "zhixuan-dev-only-secret-key-change-me-in-production"
DEFAULT_DB_PATH = BACKEND_DIR / ".runtime" / "zhixuan.db"

# HS256 密钥的最小建议长度（字节）
MIN_SECRET_KEY_BYTES = 32


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


class Settings:
    """运行时配置（进程启动时读取一次）。"""

    app_name: str = "智选志愿 API"
    version: str = "0.1.0"
    api_prefix: str = "/api"
    debug: bool = _bool_env("ZHIXUAN_DEBUG", True)
    cors_origins: list[str] = _split_csv(
        os.getenv("ZHIXUAN_CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
    )
    environment: str = os.getenv("ZHIXUAN_ENV", "dev").strip() or "dev"

    # —— 数据库（tasks.md 1.4）——
    # 默认 SQLite：本地零安装即可跑通，且与 PostgreSQL 共用同一套 SQLAlchemy 模型。
    # 切换 PostgreSQL 只需设置 ZHIXUAN_DATABASE_URL，例如：
    #   postgresql+psycopg://user:password@host:5432/zhixuan
    database_url: str = os.getenv(
        "ZHIXUAN_DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"
    )
    # 建表唯一入口是 alembic（`cd backend && .venv/Scripts/alembic upgrade head`）。
    # 此项默认关闭：开启后启动时会用 create_all() 抢先建表，导致随后的 alembic
    # 迁移因 "table already exists" 失败，且不会写入 alembic_version。
    # 仅在需要"零迁移快速起一个临时库"时才显式设为 true。
    auto_create_tables: bool = _bool_env("ZHIXUAN_AUTO_CREATE_TABLES", False)

    # —— 认证（tasks.md 3.1、3.2）——
    secret_key: str = os.getenv("ZHIXUAN_SECRET_KEY", DEFAULT_SECRET_KEY)
    access_token_ttl_minutes: int = _int_env("ZHIXUAN_TOKEN_TTL_MINUTES", 7 * 24 * 60)
    password_iterations: int = _int_env("ZHIXUAN_PASSWORD_ITERATIONS", 260_000)
    login_max_failures: int = _int_env("ZHIXUAN_LOGIN_MAX_FAILURES", 5)
    login_lock_seconds: int = _int_env("ZHIXUAN_LOGIN_LOCK_SECONDS", 300)

    # —— 管理端（tasks.md 8.1）——
    # 首个管理员的引导值，仅在手工执行 `python -m app.services.admin_seed` 时使用；
    # 口令为空则脚本拒绝创建（避免落一个空口令的管理员）。登录后可正常使用。
    admin_username: str = os.getenv("ZHIXUAN_ADMIN_USERNAME", "admin").strip() or "admin"
    admin_password: str = os.getenv("ZHIXUAN_ADMIN_PASSWORD", "")

    @property
    def secret_key_is_default(self) -> bool:
        return self.secret_key == DEFAULT_SECRET_KEY

    @property
    def secret_key_too_short(self) -> bool:
        """HS256 密钥短于 32 字节时安全性下降（RFC 7518 §3.2）。"""
        return len(self.secret_key.encode("utf-8")) < MIN_SECRET_KEY_BYTES


settings = Settings()
