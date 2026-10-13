"""数据统计（tasks.md 8.7；产品书 6.6.11）。

验收条件「统计页数据与库内一致」——因此这里全部用聚合查询现算，
不缓存、不落中间表，任何一次调用都等于当时库内真实值。

覆盖度 ``coverage_by_pathway`` 的口径：以 ``pathway`` 表为骨架左连接语料，
逐条途径给出语料量（``doc_count`` / ``chunk_count``）与是否已达标的 ``covered`` 标记，
便于 ⑤ 管理端直接渲染「哪些途径还缺语料」。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.knowledge import (
    REVIEW_STATUS_PENDING,
    KnowledgeChunk,
    KnowledgeDoc,
    QaLog,
    ReviewTask,
)
from app.models.pathway import Pathway

CONFIDENCE_LOW = "low"


def _count(db: Session, model: Any, *conditions: Any) -> int:
    stmt = select(func.count()).select_from(model)
    if conditions:
        stmt = stmt.where(*conditions)
    return int(db.scalar(stmt) or 0)


def coverage_by_pathway(db: Session) -> list[dict[str, Any]]:
    """逐途径语料覆盖度（以 pathway 表为骨架，未挂语料的途径也列出）。"""
    doc_rows = dict(
        db.execute(
            select(KnowledgeDoc.pathway_id, func.count(KnowledgeDoc.id))
            .where(KnowledgeDoc.pathway_id.is_not(None))
            .group_by(KnowledgeDoc.pathway_id)
        ).all()
    )
    chunk_rows = dict(
        db.execute(
            select(KnowledgeChunk.pathway_id, func.count(KnowledgeChunk.id))
            .where(KnowledgeChunk.pathway_id.is_not(None))
            .group_by(KnowledgeChunk.pathway_id)
        ).all()
    )

    items: list[dict[str, Any]] = []
    pathways = db.scalars(select(Pathway).order_by(Pathway.id.asc())).all()
    for pathway in pathways:
        doc_count = int(doc_rows.get(pathway.id, 0))
        chunk_count = int(chunk_rows.get(pathway.id, 0))
        items.append(
            {
                "pathway_id": pathway.id,
                "pathway_name": pathway.name,
                "priority": pathway.priority,
                "doc_count": doc_count,
                "chunk_count": chunk_count,
                "covered": doc_count > 0,
            }
        )
    return items


def overview(db: Session) -> dict[str, Any]:
    """统计总览（产品书 6.6.11）。"""
    return {
        "doc_count": _count(db, KnowledgeDoc),
        "chunk_count": _count(db, KnowledgeChunk),
        "qa_count": _count(db, QaLog),
        "low_confidence_count": _count(db, QaLog, QaLog.confidence == CONFIDENCE_LOW),
        "review_pending_count": _count(db, ReviewTask, ReviewTask.status == REVIEW_STATUS_PENDING),
        "coverage_by_pathway": coverage_by_pathway(db),
    }
