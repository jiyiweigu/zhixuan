"""知识库与运营表（产品书第 7.5 节）。

知识文档、知识切片、问答日志、审核任务与管理端账号五张表，
支撑第 5 组 RAG 链路（④）与第 8 组管理端人工审核闭环（②⑤）。

关于向量列：第 7 章要求 ``knowledge_chunk.embedding`` 为 512 维向量（pgvector + HNSW）。
本机与开发环境默认走 SQLite（无 pgvector），故此处以 JSON 存储 512 维浮点数组：
写入前须由应用层做 L2 归一化。接入 PostgreSQL + pgvector 后，
用一条后续迁移把该列改为原生 ``vector(512)`` 并建 HNSW 索引即可，业务代码无需改动。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow
from app.models.constants import (
    PATHWAY_ID_MAX_LENGTH,
    PROVINCE_MAX_LENGTH,
    USER_ID_MAX_LENGTH,
    YEAR_MAX,
    YEAR_MIN,
)

SOURCE_NAME_MAX_LENGTH = 200
SOURCE_URL_MAX_LENGTH = 500
PASSWORD_HASH_MAX_LENGTH = 255

EMBEDDING_DIM = 512

QA_STATUS_PENDING_REVIEW = "pending_review"
QA_STATUS_APPROVED = "approved"
QA_STATUS_REJECTED = "rejected"

REVIEW_STATUS_PENDING = "pending"
REVIEW_STATUS_APPROVED = "approved"
REVIEW_STATUS_CORRECTED = "corrected"
REVIEW_STATUS_REJECTED = "rejected"

# 索引重建任务状态（tasks.md 8.3）：partial = 处理结束但仍有切片未向量化（向量化待 ④ 5.2）
INDEX_STATUS_PENDING = "pending"
INDEX_STATUS_RUNNING = "running"
INDEX_STATUS_PARTIAL = "partial"
INDEX_STATUS_DONE = "done"
INDEX_STATUS_FAILED = "failed"


class KnowledgeDoc(Base):
    """知识文档（语料原文）。"""

    __tablename__ = "knowledge_doc"
    __table_args__ = (
        CheckConstraint(f"year BETWEEN {YEAR_MIN} AND {YEAR_MAX}", name="year_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), index=True)
    source_name: Mapped[str] = mapped_column(String(SOURCE_NAME_MAX_LENGTH), default="")
    source_url: Mapped[str] = mapped_column(String(SOURCE_URL_MAX_LENGTH), default="")
    year: Mapped[int] = mapped_column(Integer)
    doc_type: Mapped[str] = mapped_column(String(32), index=True, default="", comment="章程 / 公告 / 政策…")
    province: Mapped[str] = mapped_column(String(PROVINCE_MAX_LENGTH), index=True, default="")
    pathway_id: Mapped[str | None] = mapped_column(
        String(PATHWAY_ID_MAX_LENGTH), default=None, index=True, comment="关联途径，可空"
    )
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class KnowledgeChunk(Base):
    """知识切片（tasks.md 5.1、5.2）。

    切片携带 province / pathway_id 元数据，检索时按二者过滤（第 8.1 节链路要求）。
    """

    __tablename__ = "knowledge_chunk"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("knowledge_doc.id"), index=True)
    content: Mapped[str] = mapped_column(Text, comment="切片正文")
    chunk_index: Mapped[int] = mapped_column(Integer, default=0, comment="文档内序号")
    embedding: Mapped[list[float] | None] = mapped_column(
        JSON, default=None, comment=f"向量占位（{EMBEDDING_DIM} 维，写入前 L2 归一化）"
    )
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, comment="切片附加元数据")
    province: Mapped[str] = mapped_column(String(PROVINCE_MAX_LENGTH), index=True, default="")
    pathway_id: Mapped[str | None] = mapped_column(
        String(PATHWAY_ID_MAX_LENGTH), default=None, index=True
    )
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class QaLog(Base):
    """问答日志（tasks.md 5.6、5.7、5.8、8.4）。"""

    __tablename__ = "qa_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(
        String(USER_ID_MAX_LENGTH), ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )
    session_id: Mapped[str | None] = mapped_column(String(64), default=None, index=True, comment="多轮会话标识")
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text, default="")
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, comment="引用溯源（来源名称 / 年份 / 链接 / 原文片段）"
    )
    confidence: Mapped[str] = mapped_column(String(16), default="", comment="high / medium / low")
    needs_review: Mapped[bool] = mapped_column(
        Boolean, default=False, index=True, comment="低置信或涉分数线时置真，自动入审核队列"
    )
    degraded: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="生成失败降级为检索片段摘要时为真"
    )
    status: Mapped[str] = mapped_column(String(16), default=QA_STATUS_APPROVED)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class ReviewTask(Base):
    """人工审核任务（tasks.md 8.4、8.5）。"""

    __tablename__ = "review_task"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    qa_log_id: Mapped[int] = mapped_column(ForeignKey("qa_log.id"), index=True)
    status: Mapped[str] = mapped_column(
        String(16), default=REVIEW_STATUS_PENDING, index=True, comment="pending / approved / corrected / rejected"
    )
    trigger_reason: Mapped[str] = mapped_column(
        String(100), default="", comment="入队原因：低置信 / 涉分数线 / 涉规则"
    )
    reviewer: Mapped[str | None] = mapped_column(String(50), default=None, comment="审核人账号")
    comment: Mapped[str] = mapped_column(Text, default="")
    corrected_answer: Mapped[str] = mapped_column(Text, default="", comment="修正后的答案，沉淀回知识库")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class IndexTask(Base):
    """索引重建任务（tasks.md 8.3；产品书 6.6.4–6.6.5）。

    该表不在产品书第 7 章表清单内（同 ``admin_audit_log``）：产品书只规定
    ``POST /index/rebuild`` 返回 ``{task_id, status}``、``GET /index/tasks/{task_id}``
    返回 ``{status, progress}``，**任务的持久化载体未定义**，故新增本表承载任务态与进度，
    使「重建期间问答仍可响应」可被观测（请求线程只建单，实际重建在后台线程执行）。
    """

    __tablename__ = "index_task"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(16), comment="all / doc_ids")
    doc_ids: Mapped[list[int]] = mapped_column(JSON, default=list, comment="scope=doc_ids 时的目标文档")
    incremental: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="真=只处理未向量化切片，假=全量重算"
    )
    status: Mapped[str] = mapped_column(
        String(16),
        default=INDEX_STATUS_PENDING,
        index=True,
        comment="pending / running / partial / done / failed",
    )
    total: Mapped[int] = mapped_column(Integer, default=0, comment="目标切片数")
    processed: Mapped[int] = mapped_column(Integer, default=0)
    embedded: Mapped[int] = mapped_column(Integer, default=0, comment="本次成功向量化数")
    pending_embedding: Mapped[int] = mapped_column(
        Integer, default=0, comment="仍待向量化数（未接入 Embedding 时等于 total）"
    )
    failed_chunks: Mapped[int] = mapped_column(Integer, default=0, comment="处理失败的切片数")
    message: Mapped[str] = mapped_column(
        String(300), default="", comment="如实标注：未接入向量化 / 异常摘要"
    )
    operator: Mapped[str] = mapped_column(String(50), default="", comment="发起重建的管理员账号")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class AdminUser(Base):
    """管理端账号（tasks.md 8.1）。

    与 C 端 ``users`` 分表：管理端鉴权独立，避免 C 端越权。
    """

    __tablename__ = "admin_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(
        String(PASSWORD_HASH_MAX_LENGTH), comment="加盐哈希，禁止明文"
    )
    role: Mapped[str] = mapped_column(String(32), default="reviewer", comment="admin / reviewer")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
