"""报考约束规则表（产品书第 7.6 节；对应 8.5 四道闸门）。

三张表都由 ③ 号数据工程按 7.6 填数，本模块只定义结构：

- ``province_exam_rule``  省份志愿模式模板（闸门 1）
- ``subject_requirement`` 选科要求（闸门 2）
- ``physical_restriction`` 身体条件限制（闸门 3）

**三张表都必须带 ``year``**（7.6 明确要求）：2025 与 2026 的规则不同，
严禁只存一份"最新"；否则跨年结论会错。年份同时纳入 CHECK，
与 app/models/constants.py 的 YEAR_MIN/YEAR_MAX 口径一致。

来源三要素：三表均为事实数据，``source_id`` 非空并外键指向 ``source`` 表，
写入前由 app/services/source_guard.py 校验。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow
from app.models.constants import (
    ADMIT_METHOD_PARALLEL,
    EXAM_MODE_GROUP,
    EXAM_MODE_VALUES,
    PROVINCE_MAX_LENGTH,
    RESTRICTION_LEVEL_VALUES,
    SUBJECT_LOGIC_ALL,
    SUBJECT_LOGIC_VALUES,
    YEAR_MAX,
    YEAR_MIN,
)

BATCH_MAX_LENGTH = 32
MODE_MAX_LENGTH = 16
LOGIC_MAX_LENGTH = 8
LEVEL_MAX_LENGTH = 16
CONDITION_MAX_LENGTH = 64
THRESHOLD_MAX_LENGTH = 128
CATEGORY_MAX_LENGTH = 50
CODE_MAX_LENGTH = 32
SUBJECT_MAX_LENGTH = 16
TIE_RULE_MAX_LENGTH = 200
RATIO_MAX_LENGTH = 32

# 用于 CHECK 的字面量清单（与 constants 中的元组保持一致）
_MODE_SQL = ", ".join(f"'{value}'" for value in EXAM_MODE_VALUES)
_LOGIC_SQL = ", ".join(f"'{value}'" for value in SUBJECT_LOGIC_VALUES)
_LEVEL_SQL = ", ".join(f"'{value}'" for value in RESTRICTION_LEVEL_VALUES)


class ProvinceExamRule(Base):
    """省份志愿模式模板（产品书 7.6；接口 6.2.6）。

    方案生成器与志愿表渲染的唯一依据：河南本科批 48 行、江西本科批 45 行、
    提前批 64 行的结构完全不同，因此必须按 (province, year, batch) 定位。
    """

    __tablename__ = "province_exam_rule"
    __table_args__ = (
        CheckConstraint(f"year BETWEEN {YEAR_MIN} AND {YEAR_MAX}", name="year_range"),
        CheckConstraint(f"mode IN ({_MODE_SQL})", name="mode_values"),
        Index("ix_province_exam_rule_lookup", "province", "year", "batch", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    province: Mapped[str] = mapped_column(String(PROVINCE_MAX_LENGTH), comment="省份，如 河南")
    year: Mapped[int] = mapped_column(Integer, comment="规则年份")
    batch: Mapped[str] = mapped_column(String(BATCH_MAX_LENGTH), comment="批次，如 本科批")
    mode: Mapped[str] = mapped_column(
        String(MODE_MAX_LENGTH), default=EXAM_MODE_GROUP, comment="group / major_school / school_major"
    )
    volunteer_count: Mapped[int] = mapped_column(Integer, default=0, comment="志愿单位数 48/45/64…")
    majors_per_group: Mapped[int | None] = mapped_column(
        Integer, default=None, comment="每组专业上限；major_school 模式为 NULL"
    )
    has_adjust: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否有“服从专业调剂”"
    )
    admit_method: Mapped[str] = mapped_column(
        String(MODE_MAX_LENGTH), default=ADMIT_METHOD_PARALLEL, comment="parallel / single"
    )
    ratio: Mapped[str] = mapped_column(String(RATIO_MAX_LENGTH), default="1:1", comment="投档比例")
    tie_rule: Mapped[str] = mapped_column(
        String(TIE_RULE_MAX_LENGTH), default="", comment="同分排序规则"
    )
    mutex_groups: Mapped[list[str]] = mapped_column(
        JSON, default=list, comment="兼报互斥组，如 提前批各类互斥、艺体不能兼报"
    )
    collect_count: Mapped[int | None] = mapped_column(
        Integer, default=None, comment="征集志愿名额"
    )
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class SubjectRequirement(Base):
    """选科要求（产品书 7.6；接口 6.2.9）。"""

    __tablename__ = "subject_requirement"
    __table_args__ = (
        CheckConstraint(f"year BETWEEN {YEAR_MIN} AND {YEAR_MAX}", name="year_range"),
        CheckConstraint(f"logic IN ({_LOGIC_SQL})", name="logic_values"),
        Index("ix_subject_requirement_major", "province", "year", "major_id"),
        Index("ix_subject_requirement_school", "school_id", "year"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    province: Mapped[str] = mapped_column(String(PROVINCE_MAX_LENGTH))
    year: Mapped[int] = mapped_column(Integer)
    batch: Mapped[str] = mapped_column(String(BATCH_MAX_LENGTH), default="")
    school_id: Mapped[int | None] = mapped_column(
        ForeignKey("school.id"), default=None, comment="同一专业不同高校要求可能不同，故可空"
    )
    group_code: Mapped[str | None] = mapped_column(
        String(CODE_MAX_LENGTH), default=None, comment="院校专业组代码"
    )
    major_id: Mapped[int | None] = mapped_column(ForeignKey("major.id"), default=None)
    first_subject: Mapped[str] = mapped_column(
        String(SUBJECT_MAX_LENGTH), default="", comment="首选科目：物理 / 历史 / 不限"
    )
    secondary_subjects: Mapped[list[str]] = mapped_column(
        JSON, default=list, comment="再选科目清单"
    )
    logic: Mapped[str] = mapped_column(
        String(LOGIC_MAX_LENGTH), default=SUBJECT_LOGIC_ALL, comment="all / any"
    )
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PhysicalRestriction(Base):
    """身体条件限制（产品书 7.6；接口 6.2.9）。

    ``level`` 严格两级，不得混同：
    - ``reject``       不合格 = 不予录取 → 进 blockers
    - ``not_suitable`` 合格不宜 = 不宜就读 → 进 warnings
    """

    __tablename__ = "physical_restriction"
    __table_args__ = (
        CheckConstraint(f"year BETWEEN {YEAR_MIN} AND {YEAR_MAX}", name="year_range"),
        CheckConstraint(f"level IN ({_LEVEL_SQL})", name="level_values"),
        Index("ix_physical_restriction_condition", "condition"),
        Index("ix_physical_restriction_major", "major_category", "major_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    condition: Mapped[str] = mapped_column(
        String(CONDITION_MAX_LENGTH), comment="条件，如 色弱 / 色盲 / 裸眼视力 / 乙肝"
    )
    threshold: Mapped[str] = mapped_column(
        String(THRESHOLD_MAX_LENGTH), default="", comment="阈值，如 <5.0 / 携带 / 不限"
    )
    major_category: Mapped[str] = mapped_column(
        String(CATEGORY_MAX_LENGTH), default="", comment="影响专业类，如 医学类"
    )
    major_code: Mapped[str] = mapped_column(String(CODE_MAX_LENGTH), default="")
    level: Mapped[str] = mapped_column(
        String(LEVEL_MAX_LENGTH), comment="reject / not_suitable"
    )
    detail: Mapped[str] = mapped_column(Text, default="", comment="依据原文")
    province: Mapped[str] = mapped_column(
        String(PROVINCE_MAX_LENGTH), default="", comment="适用省份，空表示全国"
    )
    year: Mapped[int] = mapped_column(Integer, comment="规则年份")
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
