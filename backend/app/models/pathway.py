"""升学途径相关表（产品书第 7.2 节）。

途径字典、资格规则、专项实施区域与路径录取参考四张表。
tasks.md 4.1/4.2/4.3 的规则引擎当前从 app/data/pathways/*.json 读取；
本模块提供同构的库表，供 ③ 号数据入库与管理端（tasks.md 8.6）维护规则时落库。

pathway.id 使用可读字符串（如 ``p_general``），与 app/data/pathways/catalog.json 中的 id 一致，
避免字典数据在「文件」与「库表」之间出现两套编号。
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
    PATHWAY_ID_MAX_LENGTH,
    PROVINCE_MAX_LENGTH,
    YEAR_MAX,
    YEAR_MIN,
)


class Pathway(Base):
    """升学途径字典（tasks.md 2.4、4.1）。"""

    __tablename__ = "pathway"
    __table_args__ = (
        CheckConstraint(f"year BETWEEN {YEAR_MIN} AND {YEAR_MAX}", name="year_range"),
    )

    id: Mapped[str] = mapped_column(String(PATHWAY_ID_MAX_LENGTH), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), index=True, comment="途径名称")
    category: Mapped[str] = mapped_column(String(32), index=True, default="", comment="途径分类")
    batch: Mapped[str] = mapped_column(String(32), default="", comment="录取批次")
    target_group: Mapped[str] = mapped_column(String(50), default="", comment="面向人群")
    apply_time: Mapped[str] = mapped_column(String(100), default="", comment="报名 / 填报时间节点")
    description: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(8), index=True, default="P2", comment="P0 / P1 / P2")
    data_status: Mapped[str] = mapped_column(
        String(16), default="planned", comment="ready / planned，对应「数据规划中」标注"
    )
    year: Mapped[int] = mapped_column(Integer)
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PathwayEligibility(Base):
    """途径资格规则（tasks.md 4.2，管理端维护见 8.6）。"""

    __tablename__ = "pathway_eligibility"
    __table_args__ = (
        CheckConstraint(f"year BETWEEN {YEAR_MIN} AND {YEAR_MAX}", name="year_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pathway_id: Mapped[str] = mapped_column(
        String(PATHWAY_ID_MAX_LENGTH), ForeignKey("pathway.id"), index=True
    )
    province: Mapped[str] = mapped_column(
        String(PROVINCE_MAX_LENGTH), index=True, default="", comment="适用省份，空表示通用"
    )
    rule_type: Mapped[str] = mapped_column(
        String(16), comment="户籍 / 学籍 / 区域 / 成绩"
    )
    rule_desc: Mapped[str] = mapped_column(Text, default="", comment="规则条文，前端可展开")
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, comment="规则参数")
    year: Mapped[int] = mapped_column(Integer)
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PathwayRegion(Base):
    """专项计划实施区域名单（tasks.md 2.3、4.3）。

    这里存的是「县名 → 所属专项」的明细；名单为空时资格引擎返回「待核验」而非臆测，
    与 app/core/dataset.py 中 region_quotas.json 的处理原则一致。
    """

    __tablename__ = "pathway_region"
    __table_args__ = (
        CheckConstraint(f"year BETWEEN {YEAR_MIN} AND {YEAR_MAX}", name="year_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pathway_id: Mapped[str] = mapped_column(
        String(PATHWAY_ID_MAX_LENGTH), ForeignKey("pathway.id"), index=True
    )
    province: Mapped[str] = mapped_column(String(PROVINCE_MAX_LENGTH), index=True)
    county_name: Mapped[str] = mapped_column(String(50), index=True, comment="县（区）名称")
    county_code: Mapped[str | None] = mapped_column(String(20), default=None, comment="行政区划代码")
    year: Mapped[int] = mapped_column(Integer)
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PathwayScore(Base):
    """路径录取参考分（专项计划等途径的录取数据）。"""

    __tablename__ = "pathway_score"
    __table_args__ = (
        CheckConstraint(f"year BETWEEN {YEAR_MIN} AND {YEAR_MAX}", name="year_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pathway_id: Mapped[str] = mapped_column(
        String(PATHWAY_ID_MAX_LENGTH), ForeignKey("pathway.id"), index=True
    )
    school_id: Mapped[int] = mapped_column(ForeignKey("school.id"), index=True)
    major_id: Mapped[int | None] = mapped_column(
        ForeignKey("major.id"), default=None, comment="专业维度，可空表示院校级"
    )
    province: Mapped[str] = mapped_column(String(PROVINCE_MAX_LENGTH))
    year: Mapped[int] = mapped_column(Integer)
    min_score: Mapped[int | None] = mapped_column(Integer, default=None)
    min_rank: Mapped[int | None] = mapped_column(Integer, default=None)
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
