"""基础数据表（产品书第 7.1 节）。

覆盖院校库、专业库、录取分、一分一段、招生章程与学科评估六张事实表。
数据由 tasks.md 第 2 组（③ 数据工程）采集入库，本模块只定义结构。

来源约定（第 7 章）：带 ``source_id`` 的表为事实数据，字段非空；
院校库与专业库属基础字典，来源随记录在 source 表中登记。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
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
    PROVINCE_MAX_LENGTH,
    SCORE_MAX,
    SCORE_MIN,
    SUBJECT_TYPE_MAX_LENGTH,
    YEAR_MAX,
    YEAR_MIN,
)

NAME_MAX_LENGTH = 200
CODE_MAX_LENGTH = 32


class School(Base):
    """院校基础库。

    按第 7.1 节，院校库与专业库属基础字典，字段中不含 source_id；
    依赖来源的事实数据（录取分、一分一段、章程、学科评估）才带 source_id 外键。
    """

    __tablename__ = "school"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH), index=True, comment="院校名称")
    code: Mapped[str | None] = mapped_column(String(CODE_MAX_LENGTH), default=None, comment="院校代码")
    province: Mapped[str] = mapped_column(
        String(PROVINCE_MAX_LENGTH), index=True, comment="所在省份"
    )
    city: Mapped[str] = mapped_column(String(50), default="", comment="所在城市")
    level: Mapped[str] = mapped_column(
        String(32), index=True, default="", comment="办学层次：本科 / 专科"
    )
    type: Mapped[str] = mapped_column(String(32), default="", comment="院校类型：综合 / 理工 / 师范…")
    ownership: Mapped[str] = mapped_column(String(32), default="", comment="办学性质：公办 / 民办")
    website: Mapped[str] = mapped_column(String(200), default="")
    intro: Mapped[str] = mapped_column(Text, default="", comment="院校简介")
    # 0008：院校层次 —— 冲稳保推荐与家长决策的核心维度
    is_985: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否 985")
    is_211: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否 211")
    dual_class: Mapped[str] = mapped_column(
        String(32), default="", comment="双一流：一流大学建设高校 / 一流学科建设高校"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Major(Base):
    """专业基础库。

    7.1 后半段字段（tuition / ownership / duration / campus / is_category /
    single_subject_req / language_req / gender_req / interview_required）为
    v1.1 报考约束所需：闸门 4 用学费与办学性质分档，6.2.9 用单科 / 语种 /
    性别 / 面试等"藏在招生章程里"的要求。
    """

    __tablename__ = "major"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH), index=True, comment="专业名称")
    code: Mapped[str | None] = mapped_column(String(CODE_MAX_LENGTH), default=None, comment="专业代码")
    category: Mapped[str] = mapped_column(
        String(50), index=True, default="", comment="学科门类 / 专业类"
    )
    first_class: Mapped[str] = mapped_column(String(100), default="", comment="是否一流本科专业建设点")
    degree: Mapped[str] = mapped_column(String(32), default="", comment="授予学位")
    # v1.1：报考约束所需
    tuition: Mapped[int | None] = mapped_column(Integer, default=None, comment="学费参考（元/年）")
    ownership: Mapped[str] = mapped_column(
        String(32), default="", comment="办学性质：公办 / 民办 / 中外合作"
    )
    duration: Mapped[str] = mapped_column(String(16), default="", comment="学制，如 四年")
    campus: Mapped[str] = mapped_column(String(100), default="", comment="校区")
    is_category: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否按大类招生"
    )
    single_subject_req: Mapped[str] = mapped_column(
        String(100), default="", comment="单科成绩要求（来自招生章程）"
    )
    language_req: Mapped[str] = mapped_column(String(64), default="", comment="外语语种要求")
    gender_req: Mapped[str] = mapped_column(String(32), default="", comment="性别要求")
    interview_required: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否要求面试"
    )
    # 0008：专业简介（数据库侧产出的正文，产品端「专业介绍」直接可用）
    intro: Mapped[str] = mapped_column(Text, default="", comment="专业简介")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class SchoolMajorScore(Base):
    """院校专业录取分（历年录取数据，tasks.md 2.2）。"""

    __tablename__ = "school_major_score"
    __table_args__ = (
        CheckConstraint(f"year BETWEEN {YEAR_MIN} AND {YEAR_MAX}", name="year_range"),
        CheckConstraint(
            f"min_score IS NULL OR (min_score BETWEEN {SCORE_MIN} AND {SCORE_MAX})",
            name="min_score_range",
        ),
        Index("ix_school_major_score_lookup", "province", "year", "batch", "pathway_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 0008：两个外键放宽为可空 —— 项目红线「宁可缺，不可猜」，
    # 未匹配到院校库 / 专业库的行留 null 并如实登记原因，不猜测补全。
    school_id: Mapped[int | None] = mapped_column(
        ForeignKey("school.id"), default=None, index=True, comment="未匹配到院校库时留空"
    )
    major_id: Mapped[int | None] = mapped_column(
        ForeignKey("major.id"), default=None, index=True, comment="未匹配到专业库时留空"
    )
    province: Mapped[str] = mapped_column(String(PROVINCE_MAX_LENGTH), comment="招生省份")
    year: Mapped[int] = mapped_column(Integer, comment="录取年份")
    batch: Mapped[str] = mapped_column(String(32), default="", comment="录取批次")
    group_code: Mapped[str] = mapped_column(
        String(32), default="", comment="院校专业组代码（河南为院校专业组志愿模式）"
    )
    pathway_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("pathway.id"), default=None, comment="对应升学途径，可空"
    )
    subject_type: Mapped[str] = mapped_column(
        String(SUBJECT_TYPE_MAX_LENGTH), default="", comment="科类：物理类 / 历史类"
    )
    min_score: Mapped[int | None] = mapped_column(Integer, default=None, comment="最低录取分")
    min_rank: Mapped[int | None] = mapped_column(Integer, default=None, comment="最低位次")
    avg_score: Mapped[int | None] = mapped_column(Integer, default=None, comment="平均分")
    plan_count: Mapped[int | None] = mapped_column(Integer, default=None, comment="招生计划数")
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ScoreSegment(Base):
    """一分一段表（tasks.md 2.2）。"""

    __tablename__ = "score_segment"
    __table_args__ = (
        CheckConstraint(f"year BETWEEN {YEAR_MIN} AND {YEAR_MAX}", name="year_range"),
        CheckConstraint(
            f"score BETWEEN {SCORE_MIN} AND {SCORE_MAX}", name="score_range"
        ),
        Index("ix_score_segment_lookup", "province", "year", "subject_type", "score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    province: Mapped[str] = mapped_column(String(PROVINCE_MAX_LENGTH))
    year: Mapped[int] = mapped_column(Integer)
    subject_type: Mapped[str] = mapped_column(String(SUBJECT_TYPE_MAX_LENGTH))
    batch: Mapped[str] = mapped_column(
        String(32), default="", comment="批次（老高考一分为多段，必须按 batch 保留）"
    )
    score: Mapped[int] = mapped_column(Integer, comment="分数")
    cumulative_rank: Mapped[int] = mapped_column(Integer, comment="累计人数（位次）")
    same_score_count: Mapped[int | None] = mapped_column(
        Integer, default=None, comment="同分人数（0008 补列）"
    )
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class EnrollmentRule(Base):
    """招生章程 / 录取规则（tasks.md 2.5）。"""

    __tablename__ = "enrollment_rule"
    __table_args__ = (
        CheckConstraint(f"year BETWEEN {YEAR_MIN} AND {YEAR_MAX}", name="year_range"),
        Index("ix_enrollment_rule_school_year", "school_id", "year"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("school.id"))
    year: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text, default="", comment="章程正文 / 摘要")
    subject_req: Mapped[str] = mapped_column(Text, default="", comment="选科要求")
    health_req: Mapped[str] = mapped_column(Text, default="", comment="体检要求")
    foreign_lang_req: Mapped[str] = mapped_column(Text, default="", comment="外语语种要求")
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class DisciplineEval(Base):
    """学科评估结果（tasks.md 2.5）。"""

    __tablename__ = "discipline_eval"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("school.id"), index=True)
    discipline_name: Mapped[str] = mapped_column(String(100), comment="学科名称")
    grade: Mapped[str] = mapped_column(String(16), default="", comment="评估等级，如 A+ / B")
    round: Mapped[str] = mapped_column(String(16), default="", comment="评估轮次，如第四轮")
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
