"""院校画像表（产品书第 7.4 节）。

- ``school_profile``：办学与费用信息，含 source_id 外键（tasks.md 2.5）；
- ``school_life``：生活信息，来源就地冗余记录，并带 ``reliability`` 可靠性标注；
  非官方来源在前端默认折叠并显示「仅供参考」（tasks.md 7.3）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
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
    RELIABILITY_OFFICIAL,
    RELIABILITY_UNOFFICIAL,
    YEAR_MAX,
    YEAR_MIN,
)

SOURCE_NAME_MAX_LENGTH = 200
SOURCE_URL_MAX_LENGTH = 500

__all__ = [
    "RELIABILITY_OFFICIAL",
    "RELIABILITY_UNOFFICIAL",
    "SchoolLife",
    "SchoolProfile",
]


class SchoolProfile(Base):
    """办学 / 费用信息（tasks.md 2.5、7.2）。"""

    __tablename__ = "school_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("school.id"), index=True, unique=True)
    tuition_range: Mapped[str] = mapped_column(String(50), default="", comment="学费区间")
    accommodation_fee: Mapped[str] = mapped_column(String(50), default="", comment="住宿费")
    campus_list: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, comment="校区列表：[{name, address, city}]（产品书 6.5.3）"
    )
    established_year: Mapped[int | None] = mapped_column(Integer, default=None, comment="建校年份")
    master_phd_points: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, default=None, comment="硕博点数：{master, phd}（产品书 6.5.3 定为对象，无数据为 null）"
    )
    first_class_major_count: Mapped[int | None] = mapped_column(
        Integer, default=None, comment="一流本科专业建设点数量"
    )
    faculty_count: Mapped[int | None] = mapped_column(Integer, default=None, comment="师资人数")
    student_faculty_ratio: Mapped[str] = mapped_column(String(20), default="", comment="生师比")
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class SchoolLife(Base):
    """生活信息（tasks.md 7.3）：来源就地记录 + 可靠性标注。"""

    __tablename__ = "school_life"
    __table_args__ = (
        CheckConstraint(f"year BETWEEN {YEAR_MIN} AND {YEAR_MAX}", name="year_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("school.id"), index=True)
    category: Mapped[str] = mapped_column(
        String(32), index=True, default="", comment="宿舍 / 食堂 / 交通 / 校园环境…"
    )
    content: Mapped[str] = mapped_column(Text, default="")
    source_type: Mapped[str] = mapped_column(String(32), default="", comment="official / 论坛 / 自媒体")
    source_name: Mapped[str] = mapped_column(String(SOURCE_NAME_MAX_LENGTH), default="")
    source_url: Mapped[str] = mapped_column(String(SOURCE_URL_MAX_LENGTH), default="")
    year: Mapped[int] = mapped_column(Integer)
    reliability: Mapped[str] = mapped_column(
        String(16),
        default=RELIABILITY_UNOFFICIAL,
        comment="official / unofficial；非官方前端默认折叠",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
