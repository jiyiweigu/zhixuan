"""可溯源问答接口。

契约：docs/api-contract.md 第 4 节。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.core.response import ok
from app.services import qa as qa_service

router = APIRouter(prefix="/qa", tags=["问答"])


@router.get("", summary="提问并返回可溯源回答")
def ask(q: str = Query(..., description="用户问题")) -> dict[str, Any]:
    return ok(qa_service.answer(q))
