"""报考约束接口的请求模型（契约 8.2–8.6；产品书 6.1.4 / 6.2.7）。

字段名严格对齐契约与前端 ``types/api.d.ts``，snake_case，不转驼峰。
跨层词表（契约「统一约定 · 跨层词表」）：``pathway_id`` 为**字符串 slug**，
``exam_type`` 取 ``普通 / 艺术 / 体育``。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.models.constants import (
    EXAM_TYPE_NORMAL,
    MAX_CHECK_UNITS,
    PHYSICAL_STATE_UNFILLED,
)


def _to_int(value: object) -> object:
    """把纯数字字符串归一为 int（契约示例里的 id 可能以字符串给出）。

    非数字字符串原样返回，交由服务层按"查不到"处理，不臆造映射。
    """
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    return value


class ConstraintProfile(BaseModel):
    """校验所需的档案子集（契约 8.4 请求 ``profile`` 字段清单）。

    所有体检 / 户籍字段可为 ``null``（未填）：引擎据此输出 ``unknowns``，
    **绝不当作合格**（契约 8.1）。服务端同时接受历史哨兵字符串
    （``""`` / ``"未填"`` / ``"未知"``），并在出接口时归一为 ``null``。
    """

    province: str = Field(default="", max_length=20, description="省份名，如 河南；也接受两位省代码 41")
    year: int | None = Field(default=None, description="规则年份，未填时取该省最新规则年份")
    exam_type: str = Field(
        default=EXAM_TYPE_NORMAL, max_length=8, description="普通 / 艺术 / 体育"
    )
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
    hearing: str | None = Field(default=None, max_length=8)
    smell: str | None = Field(default=None, max_length=8)
    stutter: str | None = Field(default=None, max_length=8)

    household_type: str | None = Field(default=None, max_length=8)
    home_county: str | None = Field(default=None, max_length=50)
    home_county_code: str | None = Field(default=None, max_length=16)
    school_years: int | None = Field(default=None, ge=0, le=30)
    tuition_budget: int | None = Field(default=None, ge=0, description="年学费预算，即 fee_ceiling")
    batch_preference: list[str] = Field(default_factory=list, description="意向批次")
    accept_adjustment: bool | None = None

    @field_validator("color_vision", "hearing", "smell", "stutter", "household_type", mode="before")
    @classmethod
    def _blank_sentinel_to_none(cls, value: object) -> object:
        """``""`` / ``"未填"`` / ``"未知"`` 一律收敛为 ``null``（契约 8.1）。"""
        if isinstance(value, str) and value.strip() in ("", PHYSICAL_STATE_UNFILLED, "未知"):
            return None
        return value

    @field_validator("vision_left", "vision_right", "height", "weight", mode="before")
    @classmethod
    def _unfilled_number_to_none(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() in ("", PHYSICAL_STATE_UNFILLED, "未知"):
            return None
        return value

    @field_validator("hepatitis_b", mode="before")
    @classmethod
    def _unfilled_bool_to_none(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() in ("", PHYSICAL_STATE_UNFILLED, "未知"):
            return None
        return value


class CheckUnit(BaseModel):
    """一个志愿单位（契约 8.4 请求 ``items[]``）。"""

    unit_id: str = Field(min_length=1, max_length=64)
    batch: str = Field(default="", max_length=32)
    school_id: int | None = None
    group_code: str | None = Field(default=None, max_length=32)
    major_ids: list[int] = Field(default_factory=list, description="该志愿单位内的专业 id")

    @field_validator("school_id", mode="before")
    @classmethod
    def _school_id_int(cls, value: object) -> object:
        return _to_int(value)

    @field_validator("major_ids", mode="before")
    @classmethod
    def _major_ids_int(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return [_to_int(item) for item in value]
        return value


class EligibilityCheckRequest(BaseModel):
    """批量资格校验请求（契约 8.4 游客 / 8.5 登录）。"""

    profile: ConstraintProfile
    items: list[CheckUnit] = Field(default_factory=list)
    pathway_id: str | None = Field(default=None, max_length=32, description="按特定途径规则校验（字符串 slug）")

    @field_validator("items")
    @classmethod
    def _check_count(cls, value: list[CheckUnit]) -> list[CheckUnit]:
        if len(value) > MAX_CHECK_UNITS:
            raise ValueError(f"单次校验的志愿单位不得超过 {MAX_CHECK_UNITS} 条")
        return value

    @field_validator("items")
    @classmethod
    def _check_unique_unit_id(cls, value: list[CheckUnit]) -> list[CheckUnit]:
        """契约 8.4：每个 item 的 ``unit_id`` 在请求内唯一，重复 → 1001。"""
        seen: set[str] = set()
        for item in value:
            if item.unit_id in seen:
                raise ValueError(f"unit_id 重复：{item.unit_id}")
            seen.add(item.unit_id)
        return value
