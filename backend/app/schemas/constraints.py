"""报考约束接口的请求模型（产品书 6.2.6–6.2.9）。

字段名严格对齐产品书 6.1.4 / 6.2.7 与前端 ``types/api.d.ts``，snake_case，不转驼峰。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.models.constants import (
    MAX_CHECK_UNITS,
    PHYSICAL_STATE_UNFILLED,
)


class ConstraintProfile(BaseModel):
    """校验所需的档案子集（6.2.7 请求 ``profile`` 字段清单）。

    所有体检 / 户籍字段可为 ``null``（未填）：引擎据此输出 ``unknowns``，
    **绝不当作合格**（8.5 实现纪律第 4 条）。
    """

    province: str = Field(default="河南", max_length=20)
    year: int | None = Field(default=None, description="规则年份，未填时取该省最新规则年份")
    exam_type: str = Field(default="普通", max_length=8, description="普通 / 艺术 / 体育")
    first_subject: str = Field(default="", max_length=16, description="物理 / 历史")
    second_subjects: list[str] = Field(default_factory=list, description="再选科目")
    score: int | None = Field(default=None, ge=0, le=750)
    rank: int | None = Field(default=None, ge=1)

    color_vision: str | None = Field(default=None, max_length=24)
    vision_left: float | None = Field(default=None, ge=0, le=10)
    vision_right: float | None = Field(default=None, ge=0, le=10)
    height: int | None = Field(default=None, ge=0, le=300)
    weight: int | None = Field(default=None, ge=0, le=500)
    hepatitis_b: bool | None = None
    hearing: str = Field(default=PHYSICAL_STATE_UNFILLED, max_length=8)
    smell: str = Field(default=PHYSICAL_STATE_UNFILLED, max_length=8)
    stutter: str = Field(default=PHYSICAL_STATE_UNFILLED, max_length=8)

    household_type: str = Field(default="未知", max_length=8)
    home_county: str = Field(default="", max_length=50)
    home_county_code: str = Field(default="", max_length=16)
    school_years: int = Field(default=0, ge=0, le=30)
    tuition_budget: int | None = Field(default=None, ge=0, description="年学费预算，即 fee_ceiling")
    batch_preference: list[str] = Field(default_factory=list, description="意向批次")
    accept_adjustment: bool | None = None


class CheckUnit(BaseModel):
    """一个志愿单位（6.2.7 请求 ``items[]``）。"""

    unit_id: str = Field(min_length=1, max_length=64)
    batch: str = Field(default="", max_length=32)
    school_id: int | None = None
    group_code: str | None = Field(default=None, max_length=32)
    major_ids: list[int] = Field(default_factory=list, description="该志愿单位内的专业 id")


class EligibilityCheckRequest(BaseModel):
    """批量资格校验请求（6.2.7 游客 / 6.2.8 登录）。"""

    profile: ConstraintProfile
    items: list[CheckUnit] = Field(default_factory=list)
    pathway_id: int | None = Field(default=None, description="按特定途径规则校验")

    @field_validator("items")
    @classmethod
    def _check_count(cls, value: list[CheckUnit]) -> list[CheckUnit]:
        if len(value) > MAX_CHECK_UNITS:
            raise ValueError(f"单次校验的志愿单位不得超过 {MAX_CHECK_UNITS} 条")
        return value
