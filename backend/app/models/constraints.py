"""报考约束规则表（产品书第 7.6 节；对应 8.5 四道闸门）。

六张表都由 ③ 号数据工程按 7.6 填数，本模块只定义结构（与契约 8.7 的逻辑表一一对应）：

- ``province_exam_rule``     省份志愿模式模板（闸门 1）
- ``subject_requirement``    选科要求（闸门 2）
- ``physical_restriction``   身体条件限制（闸门 3）
- ``admission_requirement``  单科 / 语种 / 性别 / 面试 / 政审 / 体测等章程要求（8.6 ``enrollment_notes``）
- ``major_tuition``          按省份 / 年份 / 院校 / 专业维度的学费（闸门 4）
- ``rule_dataset_status``    各规则集的 ``data_status``（8.1 四值唯一取值）

**所有规则表都必须带 ``year``**（7.6 明确要求）：2025 与 2026 的规则不同，
严禁只存一份"最新"；否则跨年结论会错。年份同时纳入 CHECK，
与 app/models/constants.py 的 YEAR_MIN/YEAR_MAX 口径一致。

**批次与考试类型（契约 8.7）**：唯一键用 ``batch_code``（机器键），``batch`` 仅作展示；
数据源列名 ``category_group`` 导入时必须映射为 ``exam_type``。

来源三要素：事实数据表均为 ``source_id`` 非空并外键指向 ``source`` 表，
写入前由 app/services/source_guard.py 校验。``rule_dataset_status`` 是派生状态表，
不带来源三要素（它描述的是"哪些规则集已入库"，不是事实规则本身）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
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
    BATCH_DISPLAY_UG,
    DATA_STATUS_SCHEMA_ONLY,
    DATA_STATUS_VALUES,
    EXAM_MODE_GROUP,
    EXAM_MODE_VALUES,
    EXAM_TYPE_NORMAL,
    EXAM_TYPE_VALUES,
    PROVINCE_MAX_LENGTH,
    REQUIREMENT_TYPE_VALUES,
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
EXAM_TYPE_MAX_LENGTH = 8
REQUIREMENT_TYPE_MAX_LENGTH = 32
CURRENCY_MAX_LENGTH = 8
PERIOD_MAX_LENGTH = 8
OWNERSHIP_MAX_LENGTH = 32

# 用于 CHECK 的字面量清单（与 constants 中的元组保持一致）
_MODE_SQL = ", ".join(f"'{value}'" for value in EXAM_MODE_VALUES)
_LOGIC_SQL = ", ".join(f"'{value}'" for value in SUBJECT_LOGIC_VALUES)
_LEVEL_SQL = ", ".join(f"'{value}'" for value in RESTRICTION_LEVEL_VALUES)
_EXAM_TYPE_SQL = ", ".join(f"'{value}'" for value in EXAM_TYPE_VALUES)
_DATA_STATUS_SQL = ", ".join(f"'{value}'" for value in DATA_STATUS_VALUES)
_REQUIREMENT_TYPE_SQL = ", ".join(f"'{value}'" for value in REQUIREMENT_TYPE_VALUES)


class ProvinceExamRule(Base):
    """省份志愿模式模板（产品书 7.6；接口 8.3）。

    方案生成器与志愿表渲染的唯一依据：河南本科批 48 行、江西本科批 45 行、
    提前批 64 行的结构完全不同，因此必须按
    ``(province_code, year, batch_code, exam_type)`` 定位（契约 8.7 唯一键）。

    ``province`` / ``batch`` 保留为**展示名**（河南 / 本科批），
    跨省同批次（河南「普通本科批」、江西「本科批次」）经 ``batch_code`` 归一后不再区分。
    """

    __tablename__ = "province_exam_rule"
    __table_args__ = (
        CheckConstraint(f"year BETWEEN {YEAR_MIN} AND {YEAR_MAX}", name="year_range"),
        CheckConstraint(f"mode IN ({_MODE_SQL})", name="mode_values"),
        CheckConstraint(f"exam_type IN ({_EXAM_TYPE_SQL})", name="exam_type_values"),
        Index(
            "ix_province_exam_rule_lookup",
            "province_code",
            "year",
            "batch_code",
            "exam_type",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    province_code: Mapped[str] = mapped_column(
        String(CODE_MAX_LENGTH), default="", comment="两位省级行政区划代码，如 41（唯一键之一）"
    )
    province: Mapped[str] = mapped_column(String(PROVINCE_MAX_LENGTH), comment="省份展示名，如 河南")
    year: Mapped[int] = mapped_column(Integer, comment="规则年份")
    batch_code: Mapped[str] = mapped_column(
        String(CODE_MAX_LENGTH),
        default="",
        comment="批次机器键，如 undergraduate_regular（唯一键之一）",
    )
    batch: Mapped[str] = mapped_column(
        String(BATCH_MAX_LENGTH), default=BATCH_DISPLAY_UG, comment="批次展示名，如 本科批"
    )
    exam_type: Mapped[str] = mapped_column(
        String(EXAM_TYPE_MAX_LENGTH),
        default=EXAM_TYPE_NORMAL,
        comment="考试类型：普通 / 艺术 / 体育（由数据源 category_group 映射而来）",
    )
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
    """选科要求（产品书 7.6；接口 8.6）。"""

    __tablename__ = "subject_requirement"
    __table_args__ = (
        CheckConstraint(f"year BETWEEN {YEAR_MIN} AND {YEAR_MAX}", name="year_range"),
        CheckConstraint(f"logic IN ({_LOGIC_SQL})", name="logic_values"),
        Index("ix_subject_requirement_major", "province", "year", "major_id"),
        Index("ix_subject_requirement_school", "school_id", "year"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    province_code: Mapped[str] = mapped_column(
        String(CODE_MAX_LENGTH), default="", comment="两位省级行政区划代码，如 41"
    )
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
    """身体条件限制（产品书 7.6；接口 8.6）。

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
    province_code: Mapped[str] = mapped_column(
        String(CODE_MAX_LENGTH), default="", comment="两位省级行政区划代码；空表示全国"
    )
    province: Mapped[str] = mapped_column(
        String(PROVINCE_MAX_LENGTH), default="", comment="适用省份名，空表示全国"
    )
    year: Mapped[int] = mapped_column(Integer, comment="规则年份")
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AdmissionRequirement(Base):
    """章程要求（契约 8.7 ``admission_requirement``；支撑 8.6 的 ``enrollment_notes``）。

    承载单科成绩、语种、性别、面试 / 政审 / 体测等要求，
    **不得**把它们塞进 ``physical_restriction``（8.7 明确区分）。

    唯一键：``(province_code, year, school_id, major_id, requirement_type)``。
    ``requirement_value`` 用 JSON 表达不同 ``requirement_type`` 的形状。
    """

    __tablename__ = "admission_requirement"
    __table_args__ = (
        CheckConstraint(f"year BETWEEN {YEAR_MIN} AND {YEAR_MAX}", name="year_range"),
        CheckConstraint(
            f"requirement_type IN ({_REQUIREMENT_TYPE_SQL})", name="requirement_type_values"
        ),
        CheckConstraint(f"level IN ({_LEVEL_SQL})", name="level_values"),
        Index(
            "ix_admission_requirement_lookup",
            "province_code",
            "year",
            "school_id",
            "major_id",
            "requirement_type",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    province_code: Mapped[str] = mapped_column(String(CODE_MAX_LENGTH), default="")
    year: Mapped[int] = mapped_column(Integer)
    school_id: Mapped[int | None] = mapped_column(ForeignKey("school.id"), default=None)
    major_id: Mapped[int | None] = mapped_column(ForeignKey("major.id"), default=None)
    requirement_type: Mapped[str] = mapped_column(
        String(REQUIREMENT_TYPE_MAX_LENGTH),
        comment="single_subject / language / gender / interview / political_review / physical_test",
    )
    requirement_value: Mapped[Any] = mapped_column(
        JSON, default=dict, comment="按 requirement_type 取形状，如 {subject, minimum_score}"
    )
    level: Mapped[str] = mapped_column(
        String(LEVEL_MAX_LENGTH), default="reject", comment="reject / not_suitable"
    )
    detail: Mapped[str] = mapped_column(Text, default="", comment="依据原文")
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class MajorTuition(Base):
    """专业学费（契约 8.7 ``major_tuition``；闸门 4 与 8.6 ``tuition``）。

    学费按具体学校 / 专业 / 年份存储；**不得**仅以办学性质估算值冒充正式数据
    （8.7 硬约束）。唯一键：``(province_code, year, school_id, major_id)``。
    """

    __tablename__ = "major_tuition"
    __table_args__ = (
        CheckConstraint(f"year BETWEEN {YEAR_MIN} AND {YEAR_MAX}", name="year_range"),
        Index(
            "ix_major_tuition_lookup",
            "province_code",
            "year",
            "school_id",
            "major_id",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    province_code: Mapped[str] = mapped_column(String(CODE_MAX_LENGTH), default="")
    year: Mapped[int] = mapped_column(Integer)
    school_id: Mapped[int | None] = mapped_column(ForeignKey("school.id"), default=None)
    major_id: Mapped[int | None] = mapped_column(ForeignKey("major.id"), default=None)
    amount: Mapped[float | None] = mapped_column(
        Float, default=None, comment="元/年；未知时为 NULL 并列入 missing_rule_sets"
    )
    currency: Mapped[str] = mapped_column(String(CURRENCY_MAX_LENGTH), default="CNY")
    period: Mapped[str] = mapped_column(String(PERIOD_MAX_LENGTH), default="year")
    ownership: Mapped[str] = mapped_column(
        String(OWNERSHIP_MAX_LENGTH), default="", comment="公办 / 民办 / 中外合作…"
    )
    note: Mapped[str] = mapped_column(Text, default="", comment="计费说明，如 按官方收费标准")
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class RuleDatasetStatus(Base):
    """规则集数据状态（契约 8.7 ``rule_dataset_status``；8.1 ``data_status`` 的唯一来源）。

    唯一键：``(province_code, year, batch_code, exam_type, dataset)``。

    ``available`` **必须**由导入覆盖率 / 完整性校验得出，管理端不允许手工强制设为 available
    （契约 8.8）。本表不设来源三要素：它描述"哪些规则集已入库"，不是事实规则本身。
    """

    __tablename__ = "rule_dataset_status"
    __table_args__ = (
        CheckConstraint(f"year BETWEEN {YEAR_MIN} AND {YEAR_MAX}", name="year_range"),
        CheckConstraint(f"status IN ({_DATA_STATUS_SQL})", name="status_values"),
        Index(
            "ix_rule_dataset_status_lookup",
            "province_code",
            "year",
            "batch_code",
            "exam_type",
            "dataset",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    province_code: Mapped[str] = mapped_column(String(CODE_MAX_LENGTH), default="")
    year: Mapped[int] = mapped_column(Integer)
    batch_code: Mapped[str] = mapped_column(String(CODE_MAX_LENGTH), default="")
    exam_type: Mapped[str] = mapped_column(
        String(EXAM_TYPE_MAX_LENGTH), default=EXAM_TYPE_NORMAL
    )
    dataset: Mapped[str] = mapped_column(
        String(REQUIREMENT_TYPE_MAX_LENGTH), comment="规则集名，取值见 DATASET_VALUES"
    )
    status: Mapped[str] = mapped_column(
        String(LEVEL_MAX_LENGTH), default=DATA_STATUS_SCHEMA_ONLY, comment="available / partial / schema_only / unavailable"
    )
    note: Mapped[str] = mapped_column(Text, default="", comment="状态说明，如“名单待核验”")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
