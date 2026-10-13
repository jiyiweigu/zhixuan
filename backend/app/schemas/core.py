"""接口请求/响应公共模型。

约定：字段 snake_case（docs/api-contract.md 统一约定）。
本文件为后端共享文件，新增字段一律以"可选 + 有默认值"的方式追加，避免破坏既有调用方。

字段分组（tasks.md 3.4、3.5）：
- 基本档案：province / score / subject_type（契约原有三字段）
- 户籍与学籍：资格判定的输入，缺省为"未知"，判定结果落到"待核验"而不是臆测
- special_marks / preferences：专项资格标记与偏好，随档案保存，供资格自检与方案生成使用
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.models.constants import MAX_COMPARE_SCHOOLS

# 户籍类型：'未知' 表示用户未填写，判定结果将落为"待核验"而非确定结论
HouseholdType = Literal["农村", "城镇", "未知"]
Strategy = Literal["冲", "稳", "保"]
Priority = Literal["院校优先", "专业优先", "城市优先"]

# 已保存方案的倾向值：生成接口的三种倾向，外加 balanced（第 7 章 user_plan.strategy 的历史口径）
SavedStrategy = Literal["冲", "稳", "保", "balanced"]
# 志愿条目的档位取值（与产品书 6.1.7 PlanItem.tier 一致）
TIER_LABELS = ("冲", "稳", "保")
# 单套方案的志愿条目上限，防止异常请求写入超大 JSON
MAX_PLAN_ITEMS = 200


class Preferences(BaseModel):
    """档案中的偏好字段（tasks.md 3.5）。

    字段名与 POST /api/plans 的请求字段一致：请求未显式提供时，
    服务端沿用档案里保存的偏好（见 app/api/v1/plans.py）。
    """

    strategy: Strategy = "稳"
    priority: Priority = "院校优先"
    preferred_majors: list[str] = Field(default_factory=list, description="偏好专业")
    preferred_provinces: list[str] = Field(default_factory=list, description="偏好省份或城市")
    major_adjust: bool = Field(default=True, description="是否服从专业调剂")


class ProfileRequest(BaseModel):
    """考生档案（产品书 6.1.4；tasks.md 3.4、3.5）。

    字段名严格对齐产品书 6.1.4 与前端 ``types/api.d.ts`` 的 ``Profile``；
    v1.1 起扩 11 个字段（体检 9 项 + ``batch_preference`` + ``accept_adjustment``）。
    ``None`` 表示未填，判定引擎据此输出"待核验"而非臆测。
    """

    # ---- 基本：省 / 科类 / 选科 / 分数位次 ----
    province: str = Field(default="河南", max_length=20)
    exam_type: str = Field(default="普通", max_length=8, description="普通 / 艺术 / 体育")
    first_subject: str = Field(default="", max_length=16, description="首选科目：物理 / 历史")
    second_subjects: list[str] = Field(default_factory=list, description="再选科目")
    subject_type: str = Field(default="物理类", max_length=20, description="科类：物理类 / 历史类")
    score: int = Field(default=0, ge=0, le=750, description="高考分数，越界分数在此被拦截")
    rank: int | None = Field(default=None, ge=1, description="省内位次")

    # ---- 户籍与学籍 ----
    household_type: HouseholdType = "未知"
    home_county: str = Field(default="", max_length=50, description="户籍所在县 / 区名")
    home_county_code: str = Field(default="", max_length=16, description="行政区划代码，优先于县名")
    school_years: int = Field(default=0, ge=0, le=30, description="本地学籍年限")
    enrollment_county: str = Field(default="", max_length=50, description="学籍所在县")
    household_years: int = Field(default=0, ge=0, le=30, description="本人当地连续户籍年限")
    enrollment_years: int = Field(default=0, ge=0, le=30, description="学籍连续年限")
    parent_household_local: bool | None = Field(default=None, description="父母是否具有当地户籍")

    # ---- 偏好（6.1.4）----
    preferred_cities: list[str] = Field(default_factory=list, description="意向城市（有序）")
    preferred_majors: list[str] = Field(default_factory=list, description="意向专业类")
    tuition_budget: int | None = Field(default=None, ge=0, description="年学费预算，即 fee_ceiling")

    # ---- 体检（v1.1 新增 9 项，供 8.5 闸门 3）----
    color_vision: str | None = Field(default=None, max_length=24)
    vision_left: float | None = Field(default=None, ge=0, le=10, description="裸眼视力（小数记录法）")
    vision_right: float | None = Field(default=None, ge=0, le=10)
    height: int | None = Field(default=None, ge=0, le=300, description="身高 cm")
    weight: int | None = Field(default=None, ge=0, le=500, description="体重 kg")
    hepatitis_b: bool | None = Field(default=None, description="乙肝表面抗原携带")
    hearing: str = Field(default="未填", max_length=8, description="正常 / 异常 / 未填")
    smell: str = Field(default="未填", max_length=8)
    stutter: str = Field(default="未填", max_length=8)

    # ---- 志愿倾向（v1.1 新增）----
    batch_preference: list[str] = Field(default_factory=list, description="意向批次")
    accept_adjustment: bool | None = Field(default=None, description="是否接受专业调剂（默认值）")

    # ---- 扩展：专项标记与方案偏好 ----
    special_marks: list[str] = Field(
        default_factory=list, description="考生自行标记的专项资格，取值为途径 id"
    )
    preferences: Preferences = Field(default_factory=Preferences)


class EligibilityRequest(ProfileRequest):
    """路径资格自检请求（tasks.md 4.2、4.5）。

    在档案字段基础上仅追加报名状态；全部新增字段可选，因此只携带
    province/score/subject_type 的旧请求（游客自检）依然可用。
    """

    registered: bool = Field(
        default=True, description="是否已完成当年高考报名并通过报名资格审核"
    )


class Citation(BaseModel):
    """来源三要素（缺一不得展示）。"""

    source_name: str
    source_url: str
    year: int


class Credentials(BaseModel):
    """注册/登录凭据（契约 1. 认证）。"""

    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=6, max_length=128)


class DeleteAccountRequest(BaseModel):
    """账号注销请求（tasks.md 3.3）。

    要求二次校验口令：令牌泄漏时，攻击者无法仅凭令牌直接销号。
    """

    password: str = Field(min_length=6, max_length=128, description="当前账号口令")


class PlanRequest(BaseModel):
    """志愿方案生成请求（契约 5. 志愿方案）。

    除 profile 与 strategy 外均为新增可选字段，只传原有字段同样可用
    （tasks.md 6.3、6.4、6.5）。
    """

    profile: ProfileRequest
    strategy: Strategy = "稳"
    priority: Priority = Field(default="院校优先", description="排序策略（tasks.md 6.4）")
    preferred_majors: list[str] = Field(
        default_factory=list, description="偏好专业，用于专业优先排序"
    )
    preferred_provinces: list[str] = Field(
        default_factory=list, description="偏好省份或城市，用于城市优先排序"
    )
    limit: int = Field(default=9, ge=1, le=96, description="方案志愿总数，按倾向配额等比缩放")
    major_adjust: bool = Field(default=True, description="是否服从专业调剂")
    batch_line: int | None = Field(
        default=None, description="批次控制线，未提供时不判定贴近批次线风险"
    )


class SavedPlanWrite(BaseModel):
    """方案保存 / 命名 / 编辑请求（tasks.md 6.6，产品书 6.1.7 POST|PUT /api/user/plans）。

    字段严格对齐产品书 6.1.7 的 ``{ name, strategy, items[] }``。
    ``items`` 原样落库（JSON），因此这里只做形状与档位取值校验，
    不对条目内部字段做二次建模——生成接口（POST /api/plans）输出的条目结构
    可能随 6.3/6.4/6.5 演进，保存环节保持透传可避免两处结构各自漂移。
    """

    name: str = Field(min_length=1, max_length=100, description="方案名称，用户可自定义")
    strategy: SavedStrategy = Field(default="稳", description="方案倾向：冲 / 稳 / 保")
    items: list[dict[str, Any]] = Field(
        default_factory=list, description="冲—稳—保志愿条目，原样保存"
    )

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("方案名称不能为空")
        return value

    @field_validator("items")
    @classmethod
    def _check_items(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(value) > MAX_PLAN_ITEMS:
            raise ValueError(f"方案志愿条目不得超过 {MAX_PLAN_ITEMS} 条")
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                raise ValueError(f"第 {index + 1} 个志愿必须是对象")
            tier = item.get("tier")
            if tier is not None and tier not in TIER_LABELS:
                raise ValueError(f"第 {index + 1} 个志愿的 tier 只能是 冲 / 稳 / 保")
        return value


class SchoolCompareRequest(BaseModel):
    """院校并排对比请求（产品书 6.5.5 POST /api/schools/compare）。

    产品书把校数写作「建议 ≤5」，此处落为硬上限（``MAX_COMPARE_SCHOOLS``）：
    并排表超过 5 列在页面上已不可读，硬约束可让前端在发起请求前就拦住误用。
    """

    school_ids: list[int] = Field(
        min_length=1,
        max_length=MAX_COMPARE_SCHOOLS,
        description=f"待对比院校 id，1–{MAX_COMPARE_SCHOOLS} 所，按传入顺序并排",
    )

    @field_validator("school_ids")
    @classmethod
    def _check_ids(cls, value: list[int]) -> list[int]:
        for school_id in value:
            if school_id <= 0:
                raise ValueError("院校 id 必须为正整数")
        return value
