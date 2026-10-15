"""可溯源问答业务逻辑。

正式实现为混合检索 + 重排 + 受限生成，见 tasks.md 第 5 组与 6.1。
当前为演示实现：固定回答 + 固定置信度，引用为演示来源。

契约（docs/api-contract.md 第 4 节）：
- ``GET  /api/qa``        返回 ``answer`` / ``confidence``（0~1）/ ``citations``；
- ``POST /api/qa/ask``    同一形状，另含 ``needs_review`` / ``degraded`` / ``elapsed_ms``，
  并把本轮问答写入 ``qa_log``（多轮会话按 ``session_id`` 归集）；
- ``GET  /api/qa/history`` 按 ``session_id`` 返回分页历史。

``confidence`` 与 ``confidence_level`` 的关系：契约 §4 规定 ``confidence`` 为 0~1 数值，
前端置信度徽标需要 ``high|medium|low`` 三档；为避免前端自行设阈值，
服务端在返回数值的同时给出同一判定的分档结果，两者**必须**由同一份判定逻辑产出。
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import pagination
from app.core.demo import demo_citation
from app.models.knowledge import QaLog

DEMO_ANSWER = "请先完善考生档案，我会基于你的省份、分数与选科给出可核验建议。"
DEMO_CONFIDENCE = 0.62

# 置信度分档（与前端 ConfidenceBadge 的 high/medium/low 同口径）
CONFIDENCE_HIGH = 0.75
CONFIDENCE_MEDIUM = 0.5


def confidence_level(score: float) -> str:
    """把 0~1 置信度映射为 high / medium / low（唯一分档入口）。"""
    if score >= CONFIDENCE_HIGH:
        return "high"
    if score >= CONFIDENCE_MEDIUM:
        return "medium"
    return "low"


def answer(question: str) -> dict[str, object]:
    """回答问题，返回答案、置信度与引用（``GET /api/qa`` 形状）。"""
    return {
        "answer": DEMO_ANSWER,
        "confidence": DEMO_CONFIDENCE,
        "confidence_level": confidence_level(DEMO_CONFIDENCE),
        "citations": [demo_citation()],
    }


def ask(
    db: Session,
    question: str,
    *,
    session_id: str | None = None,
    province: str | None = None,
    pathway_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """回答并落库，返回 ``POST /api/qa/ask`` 形状。

    无可用片段时（当前演示实现恒为低置信来源）如实标注 ``needs_review``，
    不输出无依据的事实结论；检索链路接入后只需替换答案与引用来源，
    落库与响应组装保持不变。
    """
    started = time.perf_counter()
    result = answer(question)
    score = float(result["confidence"])
    level = confidence_level(score)
    # 低置信或涉分数线的问题必须人工复核（tasks.md 5.7）
    needs_review = level != "high"
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    log = QaLog(
        user_id=user_id,
        session_id=session_id,
        question=question,
        answer=str(result["answer"]),
        citations=list(result["citations"]),
        confidence=level,
        needs_review=needs_review,
        degraded=False,
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    return {
        "qa_log_id": log.id,
        "session_id": session_id,
        "question": question,
        "answer": log.answer,
        "confidence": score,
        "confidence_level": level,
        "citations": log.citations,
        "needs_review": needs_review,
        "degraded": False,
        "elapsed_ms": elapsed_ms,
    }


def history(
    db: Session,
    *,
    session_id: str | None = None,
    page: int = pagination.PAGE_DEFAULT,
    page_size: int = pagination.PAGE_SIZE_DEFAULT,
) -> dict[str, Any]:
    """按会话返回问答历史（分页，最近在前）。"""
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
