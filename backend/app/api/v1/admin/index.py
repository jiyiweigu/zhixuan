"""索引管理接口（产品书 6.6.4–6.6.5；tasks.md 8.3）。

- ``POST /index/rebuild``     发起增量 / 全量重建，返回 ``{task_id, status}``
- ``GET  /index/tasks/{id}``  任务状态与进度 ``{status, progress}``

重建在后台线程执行，请求线程只建单，**重建期间问答链路照常响应**（8.3 验收条件）。
向量化由 ④ 号 ``services.indexing.register_embedder`` 注入；未注入时任务以 ``partial`` 结束并如实标注。

全部需管理员身份（由 admin 包的 protected 统一鉴权）；发起重建会留痕（``index.rebuild``）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_admin
from app.core.response import ok
from app.db.session import get_db
from app.models.knowledge import AdminUser
from app.schemas.admin import IndexRebuildRequest
from app.services import indexing as indexing_service

router = APIRouter(prefix="/index", tags=["管理端·索引"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


@router.post("/rebuild", summary="发起索引增量重建（后台执行，不阻塞问答）")
def rebuild_index(
    payload: IndexRebuildRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """参数非法 / 文档不存在 / 已有任务在执行 → 1001。"""
    return ok(
        indexing_service.submit_rebuild(
            db, payload, admin, client_ip=_client_ip(request)
        )
    )


@router.get("/tasks/{task_id}", summary="索引任务状态与进度")
def get_index_task(task_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """任务不存在 → 1001。"""
    return ok(indexing_service.task_state(db, task_id))