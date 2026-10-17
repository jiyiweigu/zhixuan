"""进程环境初始化：导入本模块即自动加载 backend/.env。

独立成模块的原因：除了 app/core/config.py，RAG 适配器（generation / embedder /
reranker）与导入器也直接读 os.getenv，且可能被单独引入（如单元测试）。
把加载动作放在这里，任何入口只要 `from app.core import env` 就先获得同一份配置，
避免「.env 只在导入 config 时才生效」的隐式依赖。

规则：
- 只补空缺：真实环境变量优先级更高（CI / 生产可用 export 覆盖本地 .env）。
- 无第三方依赖也能跑：未安装 python-dotenv 时退回极简解析（KEY=VALUE / # 注释）。
- .env 已列入 .gitignore，任何密钥都不入库。
"""

from __future__ import annotations

import os
from pathlib import Path

# backend/ 目录（本文件位于 backend/app/core/env.py）
BACKEND_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND_DIR / ".env"


def load_env_file(path: Path) -> None:
    """把 path 指向的 .env 载入 os.environ，已存在的变量不覆盖。"""
    if not path.is_file():
        return

    try:
        from dotenv import load_dotenv
    except ImportError:
        _load_env_file_minimal(path)
        return

    load_dotenv(dotenv_path=path, override=False, encoding="utf-8")


def _load_env_file_minimal(path: Path) -> None:
    """无 python-dotenv 时的兜底解析：支持 KEY=VALUE、# 注释、成对引号。"""
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file(ENV_FILE)

__all__ = ["BACKEND_DIR", "ENV_FILE", "load_env_file"]
