"""索引管理：增量重建与任务态（tasks.md 8.3；产品书 6.6.4–6.6.5）。

分工边界（任务标注【②④】）：

- **② 负责本模块的全部内容**——重建范围判定（增量 / 全量 / 指定文档）、任务态与进度落库、
  后台线程执行。请求线程只建单不干活，因此**重建期间问答链路照常响应**（8.3 的验收条件）；
- **④ 负责真正的向量计算**（tasks.md 5.2）：完成 ``bge-small-zh-v1.5`` 接入后调用
  ``register_embedder`` 注入即可，本模块的编排、进度与落库逻辑无需改动。

**未注入 embedder 时不假装重建成功**：任务以 ``partial`` 结束，``pending_embedding`` 如实等于
待向量化切片数，``message`` 明写「向量化未接入（待 ④ 号 5.2）」，绝不让界面以为索引进度已完成。

增量语义（如实定义）：``incremental=True`` 只处理 ``embedding IS NULL`` 的切片。
若将来 ④ 需要「按文档更新时间判定陈旧」，在此函数内加条件即可。
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.response import BizCode, BizError
from app.db.base import utcnow
from app.db.session import SessionLocal
from app.models.audit import ACTION_INDEX_REBUILD
from app.models.knowledge import (
    INDEX_STATUS_DONE,
    INDEX_STATUS_FAILED,
    INDEX_STATUS_PARTIAL,
    INDEX_STATUS_PENDING,
    INDEX_STATUS_RUNNING,
    IndexTask,
    KnowledgeChunk,
    KnowledgeDoc,
    AdminUser,
)
from app.services import audit as audit_service

__all__ = [
    "SCOPE_ALL",
    "SCOPE_DOC_IDS",
    "active_task_id",
    "embedder_ready",
    "register_embedder",
    "submit_rebuild",
    "task_state",
    "target_chunk_ids",
]

SCOPE_ALL = "all"
SCOPE_DOC_IDS = "doc_ids"
SCOPES = (SCOPE_ALL, SCOPE_DOC_IDS)

ACTIVE_STATUSES = (INDEX_STATUS_PENDING, INDEX_STATUS_RUNNING)

BATCH_SIZE = 200
MESSAGE_MAX = 300
MESSAGE_NO_EMBEDDER = "向量化未接入（待 ④ 号 5.2）：本次仅完成切片清点与增量判定"

# 后台线程串行执行：SQLite 写锁下并发重建只会互相拖慢，且无业务收益
_WORKER_LOCK = threading.Lock()

# ④ 号 5.2 的接入点：接收切片正文，返回定长向量（本模块负责 L2 归一化后落库）
Embedder = Callable[[str], "list[float] | None"]
_embedder: Embedder | None = None


def register_embedder(embedder: Embedder | None) -> None:
    """④ 号 5.2 完成后注入向量化实现；传 ``None`` 可注销（测试用）。"""
    global _embedder
    _embedder = embedder


def embedder_ready() -> bool:
    return _embedder is not None


def _normalize(vector: list[float]) -> list[float]:
    """L2 归一化（knowledge_chunk.embedding 的写入约定）。"""
    norm = math.sqrt(sum(float(x) * float(x) for x in vector))
    if norm <= 0:
        return [float(x) for x in vector]
    return [float(x) / norm for x in vector]


def _embed(text: str) -> list[float] | None:
    """调用已注入的 embedder；未注入或返回空则返回 ``None``（如实计入待向量化）。"""
    if _embedder is None:
        return None
    raw = _embedder(text)
    if not raw:
        return None
    return _normalize(list(raw))


# --------------------------------------------------------------------------- #
# 范围判定
# --------------------------------------------------------------------------- #
def target_chunk_ids(
    db: Session, scope: str, doc_ids: list[int], incremental: bool
) -> list[int]:
    """列出本次重建的目标切片 id（按 id 升序）。

    **增量判定为何不走 SQL**：``knowledge_chunk.embedding`` 是 JSON 列，SQLAlchemy 默认把
    Python 的 ``None`` 落成 JSON 的 ``null``（不是 SQL NULL），因此 ``embedding IS NULL``
    匹配不到 8.2 语料导入产生的切片；两种存储形态经 JSON 解码后都是 ``None``，
    故在 Python 层判定更可靠。待 ④ 号 5.2 把该列切到 pgvector（原生 ``vector`` + HNSW）后，
    这里可改回 SQL 侧 ``embedding IS NULL`` 过滤，本函数签名不变。
    """
    conditions = []
    if scope == SCOPE_DOC_IDS:
        conditions.append(KnowledgeChunk.doc_id.in_(doc_ids))

    if not incremental:
        # 全量：无需读取向量列
        stmt = select(KnowledgeChunk.id).where(*conditions).order_by(KnowledgeChunk.id.asc())
        return [int(chunk_id) for chunk_id in db.scalars(stmt).all()]

    stmt = (
        select(KnowledgeChunk.id, KnowledgeChunk.embedding)
        .where(*conditions)
        .order_by(KnowledgeChunk.id.asc())
    )
    return [
        int(chunk_id)
        for chunk_id, embedding in db.execute(stmt).all()
        if embedding is None
    ]


def active_task_id(db: Session) -> int | None:
    """当前未结束的重建任务 id（用于拒绝并发重建）。"""
    task_id = db.scalar(
        select(IndexTask.id)
        .where(IndexTask.status.in_(ACTIVE_STATUSES))
        .order_by(IndexTask.id.asc())
    )
    return int(task_id) if task_id is not None else None


# --------------------------------------------------------------------------- #
# 发起重建
# --------------------------------------------------------------------------- #
def submit_rebuild(
    db: Session, payload: Any, admin: AdminUser, *, client_ip: str = ""
) -> dict[str, Any]:
    """建单并异步启动重建（产品书 6.6.4）。返回 ``{task_id, status}``。

    请求线程只做「范围判定 + 建单 + 留痕」，向量化在后台线程执行，
    因此**重建期间问答仍可响应**（tasks.md 8.3 验收条件）。
    并发重建、参数非法、文档不存在 → 1001。
    """
    scope = str(getattr(payload, "scope", "") or "").strip()
    if scope not in SCOPES:
        raise BizError(f"参数错误：scope 仅支持 {'/'.join(SCOPES)}")

    doc_ids = [int(x) for x in (getattr(payload, "doc_ids", None) or [])]
    if scope == SCOPE_DOC_IDS:
        if not doc_ids:
            raise BizError("参数错误：scope=doc_ids 时必须提供 doc_ids")
        known = {int(x) for x in db.scalars(select(KnowledgeDoc.id).where(KnowledgeDoc.id.in_(doc_ids)))}
        missing = sorted(set(doc_ids) - known)
        if missing:
            raise BizError(f"参数错误：文档不存在 {missing}")

    running = active_task_id(db)
    if running is not None:
        raise BizError(f"已有索引重建任务进行中（task_id={running}），请等待其结束")

    incremental = bool(getattr(payload, "incremental", True))
    chunk_ids = target_chunk_ids(db, scope, doc_ids, incremental)

    task = IndexTask(
        scope=scope,
        doc_ids=doc_ids,
        incremental=incremental,
        status=INDEX_STATUS_PENDING,
        total=len(chunk_ids),
        processed=0,
        embedded=0,
        pending_embedding=0,
        failed_chunks=0,
        message="",
        operator=admin.username,
    )
    db.add(task)
    db.flush()

    audit_service.record_audit(
        db,
        admin,
        ACTION_INDEX_REBUILD,
        target_type="index_task",
        target_id=task.id,
        detail={
            "scope": scope,
            "doc_ids": doc_ids,
            "incremental": incremental,
            "total": len(chunk_ids),
            "embedder_ready": embedder_ready(),
        },
        client_ip=client_ip,
    )
    db.commit()

    _start_worker(task.id, chunk_ids)
    return {"task_id": task.id, "status": task.status}


def _start_worker(task_id: int, chunk_ids: list[int]) -> None:
    """后台线程执行重建（daemon：进程退出不阻塞）。"""
    worker = threading.Thread(
        target=_run_rebuild,
        args=(task_id, chunk_ids),
        name=f"index-rebuild-{task_id}",
        daemon=True,
    )
    worker.start()


def _save_progress(
    db: Session,
    task_id: int,
    *,
    status: str,
    processed: int,
    embedded: int,
    pending: int,
    failed: int,
    message: str = "",
) -> None:
    """写入进度并提交（小步提交，避免长时间持写锁影响其他请求）。"""
    task = db.get(IndexTask, task_id)
    if task is None:
        return
    task.status = status
    task.processed = processed
    task.embedded = embedded
    task.pending_embedding = pending
    task.failed_chunks = failed
    if message:
        task.message = message[:MESSAGE_MAX]
    if status in (INDEX_STATUS_DONE, INDEX_STATUS_PARTIAL, INDEX_STATUS_FAILED):
        task.finished_at = utcnow()
    db.commit()


def _run_rebuild(task_id: int, chunk_ids: list[int]) -> None:
    """重建主体：逐批向量化并提交进度。异常一律落 ``failed`` 并留摘要。"""
    with _WORKER_LOCK:
        db = SessionLocal()
        try:
            task = db.get(IndexTask, task_id)
            if task is None:
                return
            task.status = INDEX_STATUS_RUNNING
            task.started_at = utcnow()
            db.commit()

            if not chunk_ids:
                _save_progress(
                    db,
                    task_id,
                    status=INDEX_STATUS_DONE,
                    processed=0,
                    embedded=0,
                    pending=0,
                    failed=0,
                    message="无待处理切片（增量范围内已全部向量化）",
                )
                return

            if not embedder_ready():
                # 不假装重建成功：如实标注为「待向量化」，直接结束（无写操作，问答不受影响）
                _save_progress(
                    db,
                    task_id,
                    status=INDEX_STATUS_PARTIAL,
                    processed=len(chunk_ids),
                    embedded=0,
                    pending=len(chunk_ids),
                    failed=0,
                    message=MESSAGE_NO_EMBEDDER,
                )
                return

            processed = embedded = pending = failed = 0
            for start in range(0, len(chunk_ids), BATCH_SIZE):
                for chunk_id in chunk_ids[start : start + BATCH_SIZE]:
                    processed += 1
                    chunk = db.get(KnowledgeChunk, chunk_id)
                    if chunk is None:  # 期间被删除
                        failed += 1
                        continue
                    # 先算向量（耗时且不持写锁）再落库
                    vector = _embed(chunk.content)
                    if vector is None:
                        pending += 1
                        continue
                    chunk.embedding = vector
                    embedded += 1
                _save_progress(
                    db,
                    task_id,
                    status=INDEX_STATUS_RUNNING,
                    processed=processed,
                    embedded=embedded,
                    pending=pending,
                    failed=failed,
                )

            message = "" if pending == 0 else f"仍有 {pending} 条切片未向量化（embedder 返回空）"
            _save_progress(
                db,
                task_id,
                status=INDEX_STATUS_DONE if pending == 0 else INDEX_STATUS_PARTIAL,
                processed=processed,
                embedded=embedded,
                pending=pending,
                failed=failed,
                message=message,
            )
        except Exception as exc:  # noqa: BLE001 - 后台线程必须兜住全部异常并落库
            db.rollback()
            try:
                current = db.get(IndexTask, task_id)
                _save_progress(
                    db,
                    task_id,
                    status=INDEX_STATUS_FAILED,
                    processed=int(current.processed or 0) if current else 0,
                    embedded=int(current.embedded or 0) if current else 0,
                    pending=int(current.pending_embedding or 0) if current else 0,
                    failed=int(current.failed_chunks or 0) if current else 0,
                    message=f"{type(exc).__name__}: {exc}",
                )
            except Exception:  # noqa: BLE001 - 落库失败时不再向上抛，避免线程异常刷屏
                db.rollback()
        finally:
            db.close()


# --------------------------------------------------------------------------- #
# 任务态查询
# --------------------------------------------------------------------------- #
def task_state(db: Session, task_id: int) -> dict[str, Any]:
    """任务状态与进度（产品书 6.6.5）。任务不存在 → 1001。"""
    task = db.get(IndexTask, task_id)
    if task is None:
        raise BizError("索引任务不存在", BizCode.PARAM_ERROR)

    total = int(task.total or 0)
    processed = int(task.processed or 0)
    percent = 100.0 if total == 0 else round(processed / total * 100, 1)
    return {
        "task_id": task.id,
        "status": task.status,
        "progress": {
            "total": total,
            "processed": processed,
            "embedded": int(task.embedded or 0),
            "pending_embedding": int(task.pending_embedding or 0),
            "failed": int(task.failed_chunks or 0),
            "percent": percent,
        },
        # 以下为追加字段，便于 ⑤ 索引页展示与排障
        "scope": task.scope,
        "doc_ids": list(task.doc_ids or []),
        "incremental": task.incremental,
        "message": task.message,
        "embedder_ready": embedder_ready(),
        "operator": task.operator,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
    }