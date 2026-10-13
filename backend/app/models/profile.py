"""考生档案表（产品书 7.3 ``user_profile``；接口 6.1.4 / 6.1.5）。

- 一个用户一份档案：``user_id`` 既是主键也是外键，随用户注销级联删除；
- 字段名严格对齐产品书 6.1.4（前端 ``types/api.d.ts`` 的 ``Profile`` 同口径），
  便于 ① 号前端联调时字段逐一对上；
- v1.1 起扩 11 个字段：``color_vision`` / ``vision_left`` / ``vision_right`` /
  ``height`` / ``weight`` / ``hepatitis_b`` / ``hearing`` / ``smell`` / ``stutter`` /
  ``batch_preference`` / ``accept_adjustment``，供 8.5 四道闸门校验；
- **``null`` = 未填**，既不默认放行也不默认拦截，校验结果落 ``unknowns``（6.1.4 注）。

保留的扩展字段（产品书未列，属本项目内部需要）：``enrollment_county`` /
``household_years`` / ``enrollment_years`` / ``parent_household_local``（资格引擎判定
国家专项等要求“户籍 + 学籍连续年限”所需）、``special_marks``（考生自报的专项标记）、
``preferences``（方案生成的偏好，如冲稳保倾向）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow
from app.models.constants import PHYSICAL_STATE_UNFILLED

COUNTY_MAX_LENGTH = 50
COUNTY_CODE_MAX_LENGTH = 16
STATE_MAX_LENGTH = 8
COLOR_VISION_MAX_LENGTH = 24


class Profile(Base):
    """考生档案（全站唯一事实来源）。"""

    __tablename__ = "profiles"

    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )

    # ---- 基本：省 / 科类 / 选科 / 分数位次（6.1.4）----
    province: Mapped[str] = mapped_column(String(20), default="河南")
    exam_type: Mapped[str] = mapped_column(String(8), default="普通", comment="普通 / 艺术 / 体育")
    first_subject: Mapped[str] = mapped_column(String(16), default="", comment="首选科目：物理 / 历史")
    second_subjects: Mapped[list[str]] = mapped_column(JSON, default=list, comment="再选科目")
    subject_type: Mapped[str] = mapped_column(
        String(20), default="物理类", comment="科类：物理类 / 历史类（兼容早期字段）"
    )
    score: Mapped[int] = mapped_column(Integer, default=0)
    rank: Mapped[int | None] = mapped_column(Integer, default=None, comment="省内位次")

    # ---- 户籍与学籍（资格判定输入，tasks.md 4.2）----
    household_type: Mapped[str] = mapped_column(String(8), default="未知")
    home_county: Mapped[str] = mapped_column(String(COUNTY_MAX_LENGTH), default="")
    home_county_code: Mapped[str] = mapped_column(
        String(COUNTY_CODE_MAX_LENGTH), default="", comment="行政区划代码，优先于县名精确匹配"
    )
    school_years: Mapped[int] = mapped_column(Integer, default=0, comment="本地学籍年限")
    # 扩展：资格引擎区分“户籍年限”与“学籍年限”
    enrollment_county: Mapped[str] = mapped_column(String(COUNTY_MAX_LENGTH), default="")
    household_years: Mapped[int] = mapped_column(Integer, default=0)
    enrollment_years: Mapped[int] = mapped_column(Integer, default=0)
    parent_household_local: Mapped[bool | None] = mapped_column(Boolean, default=None)

    # ---- 专项资格标记（由规则引擎写回，6.2.8）----
    has_national_special: Mapped[bool] = mapped_column(Boolean, default=False)
    has_local_special: Mapped[bool] = mapped_column(Boolean, default=False)
    has_college_special: Mapped[bool] = mapped_column(Boolean, default=False)

    # ---- 偏好（6.1.4）----
    preferred_cities: Mapped[list[str]] = mapped_column(JSON, default=list)
    preferred_majors: Mapped[list[str]] = mapped_column(JSON, default=list)
    tuition_budget: Mapped[int | None] = mapped_column(
        Integer, default=None, comment="年学费预算（元），即 fee_ceiling"
    )

    # ---- 体检（v1.1 新增 9 项，供 8.5 闸门 3）----
    color_vision: Mapped[str | None] = mapped_column(
        String(COLOR_VISION_MAX_LENGTH), default=None, comment="正常 / 色弱 / 色盲 / 不能识别…"
    )
    vision_left: Mapped[float | None] = mapped_column(Float, default=None, comment="裸眼视力（小数记录法）")
    vision_right: Mapped[float | None] = mapped_column(Float, default=None)
    height: Mapped[int | None] = mapped_column(Integer, default=None, comment="身高 cm")
    weight: Mapped[int | None] = mapped_column(Integer, default=None, comment="体重 kg")
    hepatitis_b: Mapped[bool | None] = mapped_column(Boolean, default=None, comment="乙肝表面抗原携带")
    hearing: Mapped[str] = mapped_column(String(STATE_MAX_LENGTH), default=PHYSICAL_STATE_UNFILLED)
    smell: Mapped[str] = mapped_column(String(STATE_MAX_LENGTH), default=PHYSICAL_STATE_UNFILLED)
    stutter: Mapped[str] = mapped_column(String(STATE_MAX_LENGTH), default=PHYSICAL_STATE_UNFILLED)

    # ---- 志愿倾向（v1.1 新增）----
    batch_preference: Mapped[list[str]] = mapped_column(JSON, default=list, comment="意向批次")
    accept_adjustment: Mapped[bool | None] = mapped_column(
        Boolean, default=None, comment="是否接受专业调剂（默认值，最终以方案内每条志愿为准）"
    )

    # ---- 扩展：专项标记与方案偏好（本项目内部）----
    special_marks: Mapped[list[str]] = mapped_column(JSON, default=list)
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
