"""语料管理接口（产品书 6.6.2–6.6.3；tasks.md 8.2）。

- ``GET  /docs``         按省份 / 年份 / 途径 / 文种归档检索（分页）
- ``POST /docs``         导入语料，**缺来源 → 4001**
- ``DELETE /docs/{id}``  删除语料及其切片

全部需管理员身份（由 admin 包的 protected 统一鉴权）；写操作留痕见 services/corpus.py。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core import pagination
from app.core.deps import get_current_admin
from app.core.response import ok
from app.db.session import get_db
from app.models.knowledge import AdminUser
from app.schemas.admin import DocCreateRequest
from app.services import corpus as corpus_service

router = APIRouter(prefix="/docs", tags=["管理端·语料"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


@router.get("", summary="语料列表（按来源与年份归档）")
def list_docs(
    province: str = Query(default="", description="按省份过滤"),
    year: int | None = Query(default=None, description="按年份过滤"),
    pathway_id: str = Query(default="", description="按关联途径过滤"),
    doc_type: str = Query(default="", description="按文种过滤，如 章程 / 公告 / 政策"),
    keyword: str = Query(default="", description="标题或正文关键词"),
    page: int = Query(default=pagination.PAGE_DEFAULT, ge=1),
    page_size: int = Query(default=pagination.PAGE_SIZE_DEFAULT, ge=1, le=pagination.PAGE_SIZE_MAX),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        corpus_service.list_docs(
            db,
            province=province,
            year=year,
            pathway_id=pathway_id,
            doc_type=doc_type,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
    )


@router.post("", summary="导入语料")
def create_doc(
    payload: DocCreateRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """导入一份语料；缺 source_name / source_url / year 任一 → 4001。"""
    return ok(corpus_service.create_doc(db, payload, admin, client_ip=_client_ip(request)))


@router.delete("/{doc_id}", summary="删除语料")
def delete_doc(
    doc_id: int,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """删除语料及其全部切片；不存在 → 1001。"""
    corpus_service.delete_doc(db, doc_id, admin, client_ip=_client_ip(request))
    return ok(None)
