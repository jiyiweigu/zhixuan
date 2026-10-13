"""健康检查。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.core.response import ok

router = APIRouter(tags=["健康检查"])


@router.get("/health", summary="服务健康检查")
def health() -> dict[str, Any]:
    return ok({"status": "ok", "service": "zhixuan"})
