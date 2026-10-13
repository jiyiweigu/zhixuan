"""人工审核工作台接口（产品书 6.6.9–6.6.10；tasks.md 8.4、8.5）。

- ``GET  /review/tasks``       待审列表（分页，可按状态 / 入队原因过滤）
- ``GET  /review/tasks/{id}``  审核详情（含 ``citations`` 原文片段，供对照）
- ``POST /review/tasks/{id}``  审核操作（approve / correct / reject），动作一律留痕
- ``POST /review/enqueue``     刷新待审队列：扫描问答日志为待审项补建任务（幂等）

前三者对应产品书 6.6.9–6.6.10；``POST /review/enqueue`` 为**追加接口**：
8.4 的自动入队发生在 ④ 号写 ``qa_log`` 时（``services.review.auto_enqueue``），
此口子供 ⑤ 管理端「刷新」与 ④ 批量补录兜底，不影响 6.6 既有契约。

全部需管理员身份（由 admin 包的 protected 统一鉴权）；审核操作留痕见 services/review.py。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core import pagination
from app.core.deps import get_current_admin
from app.core.response import ok
from app.db.session import get_db
from app.models.knowledge import (
    REVIEW_STATUS_PENDING,
    AdminUser,
)
from app.schemas.admin import ReviewDecisionRequest
from app.services import review as review_service

router = APIRouter(prefix="/review", tags=["管理端·审核"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


@router.get("/tasks", summary="待审任务列表")
def list_review_tasks(
    status: str = Query(default=REVIEW_STATUS_PENDING, description="任务状态，默认 pending；传空串则不过滤"),
    trigger_reason: str = Query(default="", description="按入队原因过滤，如 低置信 / 涉分数线 / 涉规则"),
    page: int = Query(default=pagination.PAGE_DEFAULT, ge=1),
    page_size: int = Query(default=pagination.PAGE_SIZE_DEFAULT, ge=1, le=pagination.PAGE_SIZE_MAX),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        review_service.list_tasks(
            db,
            status=status,
            trigger_reason=trigger_reason,
            page=page,
            page_size=page_size,
        )
    )


@router.post("/enqueue", summary="刷新待审队列（扫描日志补建任务，幂等）")
def enqueue_pending(
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """为尚未建单的问答补建审核任务。返回 ``{scanned, enqueued}``。"""
    return ok(review_service.enqueue_missing(db))


@router.get("/tasks/{task_id}", summary="审核详情（含引用原文片段）")
def get_review_task(task_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """任务不存在 → 1001。"""
    return ok(review_service.task_detail(db, task_id))


@router.post("/tasks/{task_id}", summary="审核操作：通过 / 修正 / 驳回")
def decide_review_task(
    task_id: int,
    payload: ReviewDecisionRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """动作非法 / 任务不存在 / 已处理 / 修正缺答案 → 1001；成功返回 ``data: null``。"""
    review_service.decide(db, task_id, payload, admin, client_ip=_client_ip(request))
    return ok(None)