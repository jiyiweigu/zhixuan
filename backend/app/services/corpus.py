"""语料管理（tasks.md 8.2；产品书 6.6.2–6.6.3）。

职责：
- 导入语料 → ``knowledge_doc``（缺来源三要素一律 4001 拒收，验证条件「缺来源导入被拒绝」）；
- 按省份 / 年份 / 途径 / 文种归档与检索（产品书 6.6.2 的筛选项）；
- 删除语料 → 连同其 ``knowledge_chunk`` 一并清理，避免留下悬空切片。

边界：**切片正文**可随导入一并落库，但**向量化与索引重建**属 tasks.md 8.3 / ④ 号职责，
本模块不生成 embedding（``knowledge_chunk.embedding`` 保持为 NULL，由 8.3 填充）。

写操作全部留痕（tasks.md 8.1），与业务改动在同一事务提交。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core import pagination
from app.core.response import BizCode, BizError
from app.models.audit import ACTION_DOC_CREATE, ACTION_DOC_DELETE
from app.models.knowledge import AdminUser, KnowledgeChunk, KnowledgeDoc
from app.models.pathway import Pathway
from app.services import audit as audit_service
from app.services import source_guard

__all__ = [
    "create_doc",
    "delete_doc",
    "doc_item",
    "list_docs",
]


def doc_item(doc: KnowledgeDoc, chunk_count: int = 0) -> dict[str, Any]:
    """语料列表项。

    产品书 6.6.2 的字段集为 ``doc_id / title / source_name / year / doc_type / province /
    pathway_id / created_at``；``source_url`` 与 ``chunk_count`` 为本实现**追加**字段
    （管理端需要看到切片是否已入库，且冻结期允许加字段，见产品书 6.7.5）。
    """
    return {
        "doc_id": doc.id,
        "title": doc.title,
        "source_name": doc.source_name,
        "source_url": doc.source_url,
        "year": doc.year,
        "doc_type": doc.doc_type,
        "province": doc.province,
        "pathway_id": doc.pathway_id,
        "chunk_count": chunk_count,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


def list_docs(
    db: Session,
    *,
    province: str = "",
    year: int | None = None,
    pathway_id: str = "",
    doc_type: str = "",
    keyword: str = "",
    page: int = pagination.PAGE_DEFAULT,
    page_size: int = pagination.PAGE_SIZE_DEFAULT,
) -> dict[str, Any]:
    """按来源与年份归档检索语料（产品书 6.6.2），最近入库的在先。"""
    stmt = select(KnowledgeDoc)
    if province.strip():
        stmt = stmt.where(KnowledgeDoc.province == province.strip())
    if year:
        stmt = stmt.where(KnowledgeDoc.year == int(year))
    if pathway_id.strip():
        stmt = stmt.where(KnowledgeDoc.pathway_id == pathway_id.strip())
    if doc_type.strip():
        stmt = stmt.where(KnowledgeDoc.doc_type == doc_type.strip())
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(KnowledgeDoc.title.like(like) | KnowledgeDoc.content.like(like))
    stmt = stmt.order_by(KnowledgeDoc.id.desc())

    page, page_size = pagination.normalize_page(page, page_size)
    total = pagination.count_of(db, stmt)
    rows = pagination.page_rows(db, stmt, page=page, page_size=page_size)

    counts = _chunk_counts(db, [row.id for row in rows])
    items = [doc_item(row, counts.get(row.id, 0)) for row in rows]
    return pagination.envelope(items, total, page, page_size)


def _chunk_counts(db: Session, doc_ids: list[int]) -> dict[int, int]:
    """一次查询算出每篇文档的切片数，避免列表接口 N+1。"""
    if not doc_ids:
        return {}
    rows = db.execute(
        select(KnowledgeChunk.doc_id, func.count(KnowledgeChunk.id))
        .where(KnowledgeChunk.doc_id.in_(doc_ids))
        .group_by(KnowledgeChunk.doc_id)
    ).all()
    return {int(doc_id): int(count) for doc_id, count in rows}


def create_doc(
    db: Session,
    payload: Any,
    admin: AdminUser,
    *,
    client_ip: str = "",
) -> dict[str, Any]:
    """导入一份语料（产品书 6.6.2；tasks.md 8.2）。

    校验顺序刻意与错误码对应：来源缺失 → 4001，年份非法 / 途径不存在 → 1001。
    """
    source_guard.require_source(payload.source_name, payload.source_url, payload.year)
    year = source_guard.require_year(payload.year)

    pathway_id = (payload.pathway_id or "").strip() or None
    if pathway_id and db.get(Pathway, pathway_id) is None:
        raise BizError(f"参数错误：途径不存在：{pathway_id}")

    source = source_guard.ensure_source(db, payload)

    doc = KnowledgeDoc(
        title=str(payload.title).strip(),
        source_name=str(payload.source_name).strip(),
        source_url=str(payload.source_url).strip(),
        year=year,
        doc_type=str(payload.doc_type or "").strip(),
        province=str(payload.province or "").strip(),
        pathway_id=pathway_id,
        content=payload.content or "",
    )
    db.add(doc)
    db.flush()

    chunk_texts = [text for text in (payload.chunks or []) if str(text).strip()]
    for index, text in enumerate(chunk_texts):
        db.add(
            KnowledgeChunk(
                doc_id=doc.id,
                content=str(text),
                chunk_index=index,
                province=doc.province,
                pathway_id=pathway_id,
                source_id=source.id,
                embedding=None,  # 向量化见 tasks.md 8.3 / ④
                meta={"title": doc.title, "doc_type": doc.doc_type},
            )
        )

    audit_service.record_audit(
        db,
        admin,
        ACTION_DOC_CREATE,
        target_type="doc",
        target_id=doc.id,
        detail={
            "title": doc.title,
            "source_name": doc.source_name,
            "year": doc.year,
            "chunk_count": len(chunk_texts),
        },
        client_ip=client_ip,
    )
    db.commit()
    return {"doc_id": doc.id, "chunk_count": len(chunk_texts)}


def delete_doc(db: Session, doc_id: int, admin: AdminUser, *, client_ip: str = "") -> None:
    """删除语料及其切片（产品书 6.6.3）。不存在 → 1001。"""
    doc = db.get(KnowledgeDoc, doc_id)
    if doc is None:
        raise BizError("语料不存在或已被删除", BizCode.PARAM_ERROR)

    removed_chunks = db.execute(
        delete(KnowledgeChunk).where(KnowledgeChunk.doc_id == doc_id)
    ).rowcount
    db.delete(doc)

    audit_service.record_audit(
        db,
        admin,
        ACTION_DOC_DELETE,
        target_type="doc",
        target_id=doc_id,
        detail={
            "title": doc.title,
            "source_name": doc.source_name,
            "removed_chunk_count": int(removed_chunks or 0),
        },
        client_ip=client_ip,
    )
    db.commit()
