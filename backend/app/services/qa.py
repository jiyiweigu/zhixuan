"""基于 T2 基建的可溯源 RAG 问答链路。"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import pagination
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.knowledge import KnowledgeChunk, KnowledgeDoc, QaLog
from app.models.source import Source
from app.rag.embedder import create_embedder_from_env
from app.rag.generation import Generator, create_generator_from_env
from app.rag.reranker import Reranker, create_reranker_from_env
from app.rag.retrieval import bm25_search, vector_search
from app.services import ai_support, review

LOGGER = logging.getLogger("zhixuan.qa")
DEMO_ANSWER = "知识库暂无相关数据，建议查阅各省教育考试院官方渠道。"
NO_EVIDENCE_CITATION = {
    "source_name": "知识库暂无数据",
    "source_url": "",
    "year": None,
    "snippet": "",
    "kind": "no_evidence",
}
CONFIDENCE_HIGH = 0.75
CONFIDENCE_MEDIUM = 0.5
_REFERENCE_WORDS = ("它", "这个", "该校", "这所", "这个专业", "该专业")

_embedder = create_embedder_from_env()
_reranker: Reranker = create_reranker_from_env()
_generator: Generator = create_generator_from_env()


def confidence_level(score: float) -> str:
    if score >= CONFIDENCE_HIGH:
        return "high"
    if score >= CONFIDENCE_MEDIUM:
        return "medium"
    return "low"


def register_embedder(embedder: Any) -> None:
    """替换问答查询 embedding，主要供部署和离线测试使用。"""
    global _embedder
    _embedder = embedder


def register_reranker(reranker: Reranker) -> None:
    global _reranker
    _reranker = reranker


def register_generator(generator: Generator) -> None:
    global _generator
    _generator = generator


def _embed_query(question: str) -> list[float] | None:
    try:
        values = _embedder.embed([question])
        return list(values[0]) if values else None
    except Exception as exc:  # noqa: BLE001 - 检索降级不能阻断问答
        LOGGER.warning("query embedding failed: %s", exc)
        return None


def _complete_source(row: dict[str, Any]) -> bool:
    return bool(row.get("source_name") and row.get("source_url") and row.get("year"))


def _row_to_candidate(chunk: KnowledgeChunk, doc: KnowledgeDoc, source: Source | None) -> dict[str, Any]:
    source_name = (source.source_name if source else "") or doc.source_name
    source_url = (source.source_url if source else "") or doc.source_url
    year = (source.year if source else None) or doc.year
    return {
        "chunk_id": int(chunk.id),
        "content": chunk.content or "",
        "embedding": list(chunk.embedding) if chunk.embedding is not None else None,
        "metadata": {
            "province": chunk.province or doc.province,
            "pathway_id": chunk.pathway_id or doc.pathway_id,
            "doc_id": int(doc.id),
        },
        "source_name": source_name,
        "source_url": source_url,
        "year": year,
        "snippet": chunk.content or "",
        "doc_id": int(doc.id),
    }


def _load_candidates(
    db: Session, *, province: str | None, pathway_id: str | None
) -> tuple[list[dict[str, Any]], bool]:
    def query(filtered: bool) -> list[dict[str, Any]]:
        stmt = (
            select(KnowledgeChunk, KnowledgeDoc, Source)
            .join(KnowledgeDoc, KnowledgeDoc.id == KnowledgeChunk.doc_id)
            .outerjoin(Source, Source.id == KnowledgeChunk.source_id)
        )
        if filtered and province:
            stmt = stmt.where((KnowledgeChunk.province == province) | (KnowledgeDoc.province == province))
        if filtered and pathway_id:
            stmt = stmt.where(
                (KnowledgeChunk.pathway_id == pathway_id) | (KnowledgeDoc.pathway_id == pathway_id)
            )
        return [_row_to_candidate(chunk, doc, source) for chunk, doc, source in db.execute(stmt).all()]

    rows = query(True)
    fallback = bool((province or pathway_id) and not rows)
    return (query(False) if fallback else rows), fallback


def _retrieve(
    db: Session,
    question: str,
    *,
    province: str | None,
    pathway_id: str | None,
) -> tuple[list[dict[str, Any]], bool]:
    candidates, fallback = _load_candidates(db, province=province, pathway_id=pathway_id)
    if not candidates:
        return [], fallback
    vector_hits: list[dict[str, Any]] = []
    query_vector = _embed_query(question)
    if query_vector:
        # SQLite 开发检索只对同维度向量计算，避免历史/测试数据阻断关键词检索。
        compatible = [row for row in candidates if row.get("embedding") and len(row["embedding"]) == len(query_vector)]
        if compatible:
            try:
                vector_hits = [hit.__dict__ for hit in vector_search(query_vector, compatible, settings.rag_vector_top_k)]
            except ValueError as exc:
                LOGGER.warning("vector retrieval skipped: %s", exc)
        by_id = {int(row["chunk_id"]): row for row in candidates}
        vector_hits = [{**by_id[int(hit["chunk_id"])], "vector_score": hit["score"]} for hit in vector_hits]
    keyword_hits = [hit.__dict__ for hit in bm25_search(question, candidates, settings.rag_bm25_top_k)]
    by_id = {int(row["chunk_id"]): row for row in candidates}
    keyword_hits = [{**by_id[int(hit["chunk_id"])], "bm25_score": hit["score"]} for hit in keyword_hits]
    merged = ai_support.rrf_merge(
        vector_hits,
        keyword_hits,
        limit=max(settings.rag_vector_top_k, settings.rag_bm25_top_k),
    )
    if not merged:
        return [], fallback
    scores = _reranker.rerank(question, merged)
    ranked = [
        {**candidate, "rerank_score": max(0.0, min(1.0, float(score)))}
        for candidate, score in zip(merged, scores)
    ]
    ranked.sort(key=lambda item: (item["rerank_score"], str(item["chunk_id"])), reverse=True)
    # 极低重排分数表示候选只是 top-k 的零分占位，不能把它当作证据交给生成器。
    if not ranked or ranked[0]["rerank_score"] < 0.15:
        return [], fallback
    return ranked[: settings.rag_rerank_top_k], fallback


def _citations(snippets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "source_name": item["source_name"],
            "source_url": item["source_url"],
            "year": item["year"],
            "snippet": item["snippet"],
            "chunk_id": item["chunk_id"],
        }
        for item in snippets
        if _complete_source(item)
    ]


def _score(snippets: list[dict[str, Any]], *, fallback: bool) -> tuple[float, str]:
    if not snippets:
        return 0.0, "low"
    top = max(float(item.get("rerank_score", 0.0)) for item in snippets)
    source_ratio = len(_citations(snippets)) / len(snippets)
    structured_hit = any(item.get("metadata", {}).get("pathway_id") for item in snippets)
    level = ai_support.classify_confidence(top, structured_hit and source_ratio >= 0.5)
    score = top * 0.7 + source_ratio * 0.2 + (0.1 if structured_hit else 0.0)
    if fallback:
        score *= 0.8
    score = max(0.0, min(1.0, score))
    if level == "low":
        score = min(score, CONFIDENCE_MEDIUM - 0.001)
    elif level == "medium":
        score = min(score, CONFIDENCE_HIGH - 0.001)
    else:
        score = max(score, CONFIDENCE_HIGH)
    return round(score, 4), confidence_level(score)


def _rewrite_question(db: Session, question: str, session_id: str | None) -> str:
    if not session_id or not any(word in question for word in _REFERENCE_WORDS):
        return question
    previous = db.scalars(
        select(QaLog).where(QaLog.session_id == session_id).order_by(QaLog.id.desc()).limit(3)
    ).all()
    if not previous:
        return question
    history = [{"entity": row.question, "answer": row.answer} for row in reversed(previous)]
    return ai_support.rewrite_question(question, history)


def _restricted(snippets: list[dict[str, Any]]) -> dict[str, Any]:
    if not snippets:
        base = ai_support.restricted_answer("", [])
        return {
            "answer": str(base.get("answer") or DEMO_ANSWER),
            "confidence": 0.0,
            "confidence_level": "low",
            # 保留契约要求的 citations 数组结构；该占位项不是事实来源，UI 应显示为无证据状态。
            "citations": [dict(NO_EVIDENCE_CITATION)],
            "needs_review": True,
            "degraded": False,
        }
    citations = _citations(snippets)
    if not citations:
        return _restricted([])
    base = ai_support.restricted_answer("", citations)
    return {
        "answer": str(base.get("answer") or "基于检索片段的摘要，请结合来源核验。[1]"),
        "citations": citations,
        "needs_review": True,
        "degraded": True,
    }


def _pipeline(
    db: Session,
    question: str,
    *,
    session_id: str | None = None,
    province: str | None = None,
    pathway_id: str | None = None,
) -> dict[str, Any]:
    effective_question = _rewrite_question(db, question, session_id)
    snippets, fallback = _retrieve(db, effective_question, province=province, pathway_id=pathway_id)
    usable = [item for item in snippets if item.get("content") and _complete_source(item)]
    if not usable:
        result = _restricted([])
        result["effective_question"] = effective_question
        return result
    score, level = _score(usable, fallback=fallback)
    citations = _citations(usable)
    try:
        answer_text = _generator.generate(
            effective_question, usable, province=province, pathway_id=pathway_id
        ).strip()
        if not answer_text:
            raise RuntimeError("generator returned empty answer")
        if not re.search(r"\[\d+\]", answer_text):
            answer_text += " [1]"
        degraded = False
    except Exception as exc:  # noqa: BLE001 - 生成失败必须降级并留下日志
        LOGGER.warning("generation failed; using evidence summary: %s", exc)
        answer_text = _restricted(usable)["answer"] + "（AI 生成暂不可用）"
        degraded = True
    return {
        "answer": answer_text,
        "confidence": score,
        "confidence_level": level,
        "citations": citations,
        "needs_review": level == "low" or degraded,
        "degraded": degraded,
        "effective_question": effective_question,
    }


def answer(question: str) -> dict[str, object]:
    """GET /api/qa 的无状态问答入口。"""
    started = time.perf_counter()
    with SessionLocal() as db:
        result = _pipeline(db, question)
    result.pop("effective_question", None)
    result.setdefault("confidence", 0.0)
    result.setdefault("confidence_level", confidence_level(float(result["confidence"])))
    result.setdefault("citations", [])
    LOGGER.debug("qa answer elapsed_ms=%s", int((time.perf_counter() - started) * 1000))
    return result


def ask(
    db: Session,
    question: str,
    *,
    session_id: str | None = None,
    province: str | None = None,
    pathway_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """POST /api/qa/ask：问答、日志和审核任务在同一事务中落库。"""
    started = time.perf_counter()
    result = _pipeline(
        db, question, session_id=session_id, province=province, pathway_id=pathway_id
    )
    score = float(result.get("confidence", 0.0))
    level = str(result.get("confidence_level") or confidence_level(score))
    needs_review = bool(result.get("needs_review")) or level == "low"
    log = QaLog(
        user_id=user_id,
        session_id=session_id,
        question=question,
        answer=str(result["answer"]),
        citations=list(result.get("citations", [])),
        confidence=level,
        needs_review=needs_review,
        degraded=bool(result.get("degraded")),
    )
    db.add(log)
    db.flush()
    # auto_enqueue 同时检查低置信、分数线、规则和资格关键词；始终调用才能覆盖
    # “高置信但高风险问题”的审核闭环，函数本身保持幂等且无理由时不建单。
    review.auto_enqueue(db, log)
    db.commit()
    db.refresh(log)
    return {
        "qa_log_id": log.id,
        "session_id": session_id,
        "question": question,
        "answer": log.answer,
        "confidence": score,
        "confidence_level": level,
        "citations": list(log.citations or []),
        "needs_review": bool(log.needs_review),
        "degraded": bool(log.degraded),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


def history(
    db: Session,
    *,
    session_id: str | None = None,
    page: int = pagination.PAGE_DEFAULT,
    page_size: int = pagination.PAGE_SIZE_DEFAULT,
) -> dict[str, Any]:
    page, page_size = pagination.normalize_page(page, page_size)
    stmt = select(QaLog)
    if session_id:
        stmt = stmt.where(QaLog.session_id == session_id)
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = list(
        db.scalars(
            stmt.order_by(QaLog.created_at.desc(), QaLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return pagination.envelope([_serialize(row) for row in rows], total, page, page_size)


def _serialize(log: QaLog) -> dict[str, Any]:
    return {
        "qa_log_id": log.id,
        "session_id": log.session_id,
        "question": log.question,
        "answer": log.answer,
        "confidence": log.confidence or "",
        "citations": list(log.citations or []),
        "needs_review": bool(log.needs_review),
        "degraded": bool(log.degraded),
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }
