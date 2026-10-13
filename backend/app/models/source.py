"""来源登记表 source（产品书第 7.1 节）。

第 7 章要求「所有事实表必须含 source_name / source_url / year 三要素，或外键 source_id」。
本表是落库后的来源字典：事实表以 source_id 外键指向它，追溯时一次查询即可拿到出处。

应用层的「缺来源不进库」强制校验见 app/core/dataset.py（tasks.md 2.6）；
本表的 CHECK 约束是数据库层的第二道闸门，拦截 year 明显非法的写入。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow
from app.models.constants import YEAR_MAX, YEAR_MIN

SOURCE_NAME_MAX_LENGTH = 200
SOURCE_URL_MAX_LENGTH = 500
SOURCE_TYPE_MAX_LENGTH = 32


class Source(Base):
    """数据来源：官方公告、考试院、院校官网、招生章程等。"""

    __tablename__ = "source"
    __table_args__ = (
        CheckConstraint(f"year BETWEEN {YEAR_MIN} AND {YEAR_MAX}", name="year_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_name: Mapped[str] = mapped_column(
        String(SOURCE_NAME_MAX_LENGTH), index=True, comment="来源名称，如「河南省教育考试院」"
    )
    source_url: Mapped[str] = mapped_column(
        String(SOURCE_URL_MAX_LENGTH), comment="来源链接，须可回溯到原文"
    )
    year: Mapped[int] = mapped_column(Integer, index=True, comment="数据所属年份")
    source_type: Mapped[str | None] = mapped_column(
        String(SOURCE_TYPE_MAX_LENGTH), default=None, comment="official / school / media …"
    )
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Source {self.source_name} {self.year}>"
