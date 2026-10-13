"""可溯源问答接口。

契约：docs/api-contract.md 第 4 节（GET /qa、POST /qa/ask）与 6.1 节（GET /qa/history）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core import pagination
from app.core.deps import get_current_user, get_optional_user
from app.core.response import ok
from app.db.session import get_db
from app.models.user import User
from app.schemas.core import QaAskRequest
from app.services import qa as qa_service

router = APIRouter(prefix="/qa", tags=["问答"])


@router.get("", summary="提问并返回可溯源回答")
def ask(q: str = Query(..., description="用户问题")) -> dict[str, Any]:
    return ok(qa_service.answer(q))


@router.post("/ask", summary="提问（结构化请求 + 留痕）")
def ask_structured(
    payload: QaAskRequest,
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """契约 §4：Auth optional；响应含 needs_review / degraded / elapsed_ms，并写入 qa_log。

    检索链路尚未接入时如实返回低置信结果并置 ``needs_review``，
    不输出无依据的事实结论（8.1 实现纪律）。
    """
    return ok(
        qa_service.ask(
            db,
            payload.question,
            session_id=payload.session_id,
            province=payload.province,
            pathway_id=payload.pathway_id,
            user_id=user.id if user is not None else None,
        )
    )


@router.get("/history", summary="问答历史（按会话分页）")
def history(
    session_id: str | None = Query(default=None, description="多轮会话标识"),
    page: int = Query(default=pagination.PAGE_DEFAULT, ge=1),
    page_size: int = Query(default=pagination.PAGE_SIZE_DEFAULT, ge=1, le=pagination.PAGE_SIZE_MAX),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """契约 §6.1：Auth yes；返回分页 ``{items, total, page, page_size}``。"""
    return ok(qa_service.history(db, session_id=session_id, page=page, page_size=page_size))
