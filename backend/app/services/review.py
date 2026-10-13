"""人工审核工作台与审核闭环（tasks.md 8.4、8.5；产品书 6.6.9–6.6.10）。

两部分职责：

1. **自动入队（8.4）**——低置信、涉分数线、涉规则的问答，写日志后自动进待审队列：
   - ``evaluate_trigger`` 判定触发条件并给出入队原因（不含模型，纯关键词 + 置信度）；
   - ``auto_enqueue`` 幂等建单，**是 ④ 号问答链路的接入点**：④ 写完 ``qa_log`` 后调用一次即可；
   - ``enqueue_missing`` 扫描补建，供管理端「刷新待审队列」与 ④ 批量补录兜底。

2. **审核操作与回流（8.5）**——通过 / 修正 / 驳回，动作一律留痕：
   - 状态流转：``pending`` → ``approved`` / ``corrected`` / ``rejected``（已处理任务不可重复审核）；
   - **修正回流**：修正答案沉淀为 ``knowledge_doc`` + 一条切片（向量化留待 8.3 / ④），
     来源取自原问答的首条引用；引用缺来源三要素时**不沉淀**（遵守「缺来源不展示、不臆测」）。

边界说明：向量化与索引重建属 tasks.md 8.3 / ④ 号职责，本模块沉淀的切片 ``embedding`` 为 NULL。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import pagination
from app.core.response import BizCode, BizError
from app.db.base import utcnow
from app.models.audit import (
    ACTION_REVIEW_APPROVE,
    ACTION_REVIEW_CORRECT,
    ACTION_REVIEW_REJECT,
)
from app.models.constants import YEAR_MAX, YEAR_MIN
from app.models.knowledge import (
    QA_STATUS_APPROVED,
    QA_STATUS_PENDING_REVIEW,
    QA_STATUS_REJECTED,
    REVIEW_STATUS_APPROVED,
    REVIEW_STATUS_CORRECTED,
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_REJECTED,
    AdminUser,
    KnowledgeChunk,
    KnowledgeDoc,
    QaLog,
    ReviewTask,
)
from app.services import audit as audit_service
from app.services import source_guard

__all__ = [
    "auto_enqueue",
    "decide",
    "enqueue_missing",
    "evaluate_trigger",
    "list_tasks",
    "task_detail",
    "task_item",
]

CONFIDENCE_LOW = "low"

TRIGGER_LOW_CONFIDENCE = "低置信"
TRIGGER_SCORE_LINE = "涉分数线"
TRIGGER_RULE = "涉规则"

# 触发关键词（命中即入队；口径与产品书 M6-4「低置信 / 涉分数线 / 涉规则」一致）
SCORE_LINE_KEYWORDS = ("分数线", "投档线", "省控线", "录取线", "位次", "一分一段", "招生计划")
RULE_KEYWORDS = ("资格", "户籍", "学籍", "专项", "政策", "报名条件", "章程")

DECISION_APPROVE = "approve"
DECISION_CORRECT = "correct"
DECISION_REJECT = "reject"
DECISION_ACTIONS = (DECISION_APPROVE, DECISION_CORRECT, DECISION_REJECT)

_AUDIT_ACTION_BY_DECISION = {
    DECISION_APPROVE: ACTION_REVIEW_APPROVE,
    DECISION_CORRECT: ACTION_REVIEW_CORRECT,
    DECISION_REJECT: ACTION_REVIEW_REJECT,
}
_STATUS_BY_DECISION = {
    DECISION_APPROVE: REVIEW_STATUS_APPROVED,
    DECISION_CORRECT: REVIEW_STATUS_CORRECTED,
    DECISION_REJECT: REVIEW_STATUS_REJECTED,
}

REVIEW_COMMENT_MAX = 200
SEDIMENT_TITLE_MAX = 80


# --------------------------------------------------------------------------- #
# 8.4 自动入队
# --------------------------------------------------------------------------- #
def evaluate_trigger(confidence: str, question: str, answer: str) -> str | None:
    """判定是否需人工审核，返回入队原因；无需审核返回 ``None``。

    触发条件（tasks.md 8.4）：低置信、涉分数线、涉规则；命中多类时以「、」连接。
    纯确定性判定，无模型参与。
    """
    reasons: list[str] = []
    if str(confidence or "").strip().lower() == CONFIDENCE_LOW:
        reasons.append(TRIGGER_LOW_CONFIDENCE)

    text = f"{question or ''}{answer or ''}"
    if any(keyword in text for keyword in SCORE_LINE_KEYWORDS):
        reasons.append(TRIGGER_SCORE_LINE)
    if any(keyword in text for keyword in RULE_KEYWORDS):
        reasons.append(TRIGGER_RULE)

    return "、".join(reasons) if reasons else None


def _existing_task_id(db: Session, qa_log_id: int) -> int | None:
    return db.scalar(select(ReviewTask.id).where(ReviewTask.qa_log_id == qa_log_id))


def auto_enqueue(db: Session, qa_log: QaLog) -> ReviewTask | None:
    """低置信 / 涉分数线 / 涉规则问答自动入队（tasks.md 8.4）。

    幂等：同一 ``qa_log`` 已建过任务则原样返回，不重复建单（一条问答最多一个任务）。
    **不提交事务**，由调用方随自身业务一起提交——④ 号在写 ``qa_log`` 的同一事务里调用即可。
    """
    existing_id = _existing_task_id(db, qa_log.id)
    if existing_id is not None:
        return db.get(ReviewTask, existing_id)

    reason = evaluate_trigger(qa_log.confidence, qa_log.question, qa_log.answer)
    if qa_log.needs_review and not reason:
        # ④ 已标记需审但置信度/关键词未命中，原因仍如实记为「低置信」以外的兜底
        reason = TRIGGER_LOW_CONFIDENCE
    if not reason:
        return None

    qa_log.needs_review = True
    qa_log.status = QA_STATUS_PENDING_REVIEW
    task = ReviewTask(
        qa_log_id=qa_log.id,
        status=REVIEW_STATUS_PENDING,
        trigger_reason=reason,
    )
    db.add(task)
    db.flush()
    return task


def enqueue_missing(db: Session) -> dict[str, int]:
    """扫描问答日志，为尚未建单的待审问答补建任务（幂等）。

    供管理端「刷新待审队列」按钮与 ④ 批量补录兜底使用；返回 ``{scanned, enqueued}``。
    本函数自带提交。
    """
    scanned = 0
    enqueued = 0
    logs = db.scalars(select(QaLog).order_by(QaLog.id.asc())).all()
    for log in logs:
        if _existing_task_id(db, log.id) is not None:
            continue
        scanned += 1
        if auto_enqueue(db, log) is not None:
            enqueued += 1
    db.commit()
    return {"scanned": scanned, "enqueued": enqueued}


# --------------------------------------------------------------------------- #
# 序列化
# --------------------------------------------------------------------------- #
def task_item(task: ReviewTask, log: QaLog) -> dict[str, Any]:
    """待审列表项（产品书 6.6.9：task_id / qa_log_id / question / answer /
    confidence / trigger_reason / created_at；``status`` 与 ``reviewer`` 为本实现追加字段）。
    """
    return {
        "task_id": task.id,
        "qa_log_id": task.qa_log_id,
        "question": log.question,
        "answer": log.answer,
        "confidence": log.confidence,
        "trigger_reason": task.trigger_reason,
        "status": task.status,
        "reviewer": task.reviewer,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


# --------------------------------------------------------------------------- #
# 8.4 待审列表
# --------------------------------------------------------------------------- #
def list_tasks(
    db: Session,
    *,
    status: str = "",
    trigger_reason: str = "",
    page: int = pagination.PAGE_DEFAULT,
    page_size: int = pagination.PAGE_SIZE_DEFAULT,
) -> dict[str, Any]:
    """待审任务列表（产品书 6.6.9），最近入队的在先。"""
    stmt = select(ReviewTask, QaLog).join(QaLog, ReviewTask.qa_log_id == QaLog.id)
    if status.strip():
        stmt = stmt.where(ReviewTask.status == status.strip())
    if trigger_reason.strip():
        stmt = stmt.where(ReviewTask.trigger_reason.like(f"%{trigger_reason.strip()}%"))
    stmt = stmt.order_by(ReviewTask.id.desc())

    page, page_size = pagination.normalize_page(page, page_size)
    total = pagination.count_of(db, stmt)
    rows = db.execute(
        stmt.offset((page - 1) * page_size).limit(page_size)
    ).all()
    items = [task_item(task, log) for task, log in rows]
    return pagination.envelope(items, total, page, page_size)


def _load(db: Session, task_id: int) -> tuple[ReviewTask, QaLog]:
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise BizError("审核任务不存在", BizCode.PARAM_ERROR)
    log = db.get(QaLog, task.qa_log_id)
    if log is None:
        # 任务必有日志（外键约束），此处仅作防御，属服务端数据异常
        raise BizError("审核任务关联的问答日志缺失", BizCode.INTERNAL_ERROR)
    return task, log


def task_detail(db: Session, task_id: int) -> dict[str, Any]:
    """审核详情（产品书 6.6.10）：任务 + 问答原文 + ``citations`` 原文片段，供审核对照。"""
    task, log = _load(db, task_id)
    detail = task_item(task, log)
    detail.update(
        {
            "citations": list(log.citations or []),
            "degraded": log.degraded,
            "session_id": log.session_id,
            "user_id": log.user_id,
            "original_answer": log.answer,
            "corrected_answer": task.corrected_answer,
            "comment": task.comment,
            "reviewed_at": task.reviewed_at.isoformat() if task.reviewed_at else None,
            "qa_created_at": log.created_at.isoformat() if log.created_at else None,
        }
    )
    return detail


# --------------------------------------------------------------------------- #
# 8.5 审核操作与回流
# --------------------------------------------------------------------------- #
def _primary_citation(citations: Any) -> dict[str, Any] | None:
    """取首条来源三要素齐全**且年份合规**的引用；无可用引用返回 ``None``。

    年份须落在 2000–2100（口径同 ``app/models/constants.py`` 与各事实表 CHECK）。
    越界年份（如 1999）与缺来源同等处理——**不沉淀**：否则写 ``source`` /
    ``knowledge_doc`` 会撞 CHECK 约束抛 IntegrityError，把管理端审核接口变成 500，
    而不是给出可预期、可解释的结果。
    """
    for citation in citations or []:
        if not isinstance(citation, dict):
            continue
        name = str(citation.get("source_name") or "").strip()
        url = str(citation.get("source_url") or "").strip()
        try:
            year = int(citation.get("year") or 0)
        except (TypeError, ValueError):
            year = 0
        if source_guard.missing_source_fields(name, url, year):
            continue
        if not (YEAR_MIN <= year <= YEAR_MAX):
            continue
        return {"source_name": name, "source_url": url, "year": year}
    return None


def _sediment_correction(db: Session, log: QaLog, corrected: str) -> int | None:
    """把修正答案沉淀为知识文档 + 一条切片（回流）。

    来源取自原问答的首条可用引用；**引用缺来源三要素则不沉淀**，返回 ``None``，
    调用方在留痕 detail 里如实标注，绝不臆造来源。切片 ``embedding`` 留空，由 8.3 / ④ 补。
    """
    citation = _primary_citation(log.citations)
    if citation is None:
        return None

    source = source_guard.ensure_source(db, SimpleNamespace(source_type=None, **citation))
    doc = KnowledgeDoc(
        title=f"审核修正：{log.question[:SEDIMENT_TITLE_MAX]}",
        source_name=citation["source_name"],
        source_url=citation["source_url"],
        year=citation["year"],
        doc_type="审核修正",
        province="",
        pathway_id=None,
        content=corrected,
    )
    db.add(doc)
    db.flush()
    db.add(
        KnowledgeChunk(
            doc_id=doc.id,
            content=corrected,
            chunk_index=0,
            province="",
            pathway_id=None,
            source_id=source.id,
            embedding=None,  # 向量化属 tasks.md 8.3 / ④
            meta={
                "title": doc.title,
                "doc_type": doc.doc_type,
                "origin": "review_correction",
                "qa_log_id": log.id,
            },
        )
    )
    return doc.id


def decide(
    db: Session,
    task_id: int,
    payload: Any,
    admin: AdminUser,
    *,
    client_ip: str = "",
) -> None:
    """审核操作（产品书 6.6.10；tasks.md 8.5）：通过 / 修正 / 驳回，**必须留痕**。

    校验顺序：动作非法 → 1001；任务不存在 → 1001；任务已处理 → 1001；
    修正缺 ``corrected_answer`` → 1001。成功返回 ``None``（契约要求 ``data: null``）。
    """
    action = str(getattr(payload, "action", "") or "").strip()
    if action not in DECISION_ACTIONS:
        raise BizError(f"参数错误：action 仅支持 {'/'.join(DECISION_ACTIONS)}")

    corrected = str(getattr(payload, "corrected_answer", "") or "").strip()
    comment = str(getattr(payload, "comment", "") or "").strip()
    if action == DECISION_CORRECT and not corrected:
        raise BizError("参数错误：修正（correct）必须提供 corrected_answer")

    task, log = _load(db, task_id)
    if task.status != REVIEW_STATUS_PENDING:
        raise BizError(f"该任务已处理（当前状态：{task.status}），不可重复审核")

    sediment_doc_id: int | None = None
    task.status = _STATUS_BY_DECISION[action]

    if action == DECISION_APPROVE:
        log.status = QA_STATUS_APPROVED
    elif action == DECISION_CORRECT:
        task.corrected_answer = corrected
        log.status = QA_STATUS_APPROVED
        sediment_doc_id = _sediment_correction(db, log, corrected)
    else:  # reject
        log.status = QA_STATUS_REJECTED

    task.reviewer = admin.username
    task.comment = comment
    task.reviewed_at = utcnow()

    audit_service.record_audit(
        db,
        admin,
        _AUDIT_ACTION_BY_DECISION[action],
        target_type="review_task",
        target_id=task.id,
        detail={
            "qa_log_id": task.qa_log_id,
            "decision": action,
            "result_status": task.status,
            "sediment_doc_id": sediment_doc_id,
            "sedimented": sediment_doc_id is not None,
            "comment": comment[:REVIEW_COMMENT_MAX],
        },
        client_ip=client_ip,
    )
    db.commit()