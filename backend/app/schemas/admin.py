"""管理端请求模型（产品书 6.6；tasks.md 8.1、8.2、8.6）。

按模块分节，字段名一律 snake_case，与产品书第 6 章保持一致。
所有模型均为新增，不影响既有 C 端接口的入参。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# 途径优先级与数据状态（产品书 6.6.6；与 app/models/pathway.py 的注释口径一致）
PathwayPriority = Literal["P0", "P1", "P2"]
PathwayDataStatus = Literal["ready", "planned"]
# 资格规则类型（产品书 7.2 pathway_eligibility.rule_type）
RuleType = Literal["户籍", "学籍", "区域", "成绩"]

SOURCE_NAME_MAX_LENGTH = 200
SOURCE_URL_MAX_LENGTH = 500


class AdminCredentials(BaseModel):
    """管理端登录凭据（产品书 6.6.1）。"""

    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=6, max_length=128)


class SourceInput(BaseModel):
    """来源三要素（产品书第 7 章：缺一拒收）。

    路径与规则维护用它承载「强制附官方来源」（tasks.md 8.6）；
    校验在服务层完成，缺失时返回 4001 而非 1001，便于前端标红提示。
    """

    source_name: str = Field(default="", max_length=SOURCE_NAME_MAX_LENGTH)
    source_url: str = Field(default="", max_length=SOURCE_URL_MAX_LENGTH)
    year: int = Field(default=0, description="数据所属年份")
    source_type: str | None = Field(default=None, max_length=32, description="official / school / media …")


class DocCreateRequest(BaseModel):
    """语料导入（产品书 6.6.2；tasks.md 8.2）。

    来源三要素按产品书 6.6 的写法**平铺**在顶层（含 ``source_name`` / ``source_url`` / ``year``）。
    ``chunks`` 可选：仅落库切片正文，向量化与索引重建属 8.3 / ④ 号职责。
    """

    title: str = Field(min_length=1, max_length=200)
    source_name: str = Field(default="", max_length=SOURCE_NAME_MAX_LENGTH)
    source_url: str = Field(default="", max_length=SOURCE_URL_MAX_LENGTH)
    year: int = Field(default=0, description="数据所属年份")
    doc_type: str = Field(default="", max_length=32, description="章程 / 公告 / 政策…")
    province: str = Field(default="", max_length=20)
    pathway_id: str | None = Field(default=None, max_length=32)
    content: str = Field(default="", description="语料正文")
    source_type: str | None = Field(default=None, max_length=32)
    chunks: list[str] = Field(default_factory=list, description="可选切片正文，向量化由 8.3 负责")


class PathwayWriteRequest(BaseModel):
    """升学途径字典写入（产品书 6.6.6；tasks.md 8.6）。"""

    name: str = Field(min_length=1, max_length=100)
    category: str = Field(default="", max_length=32)
    batch: str = Field(default="", max_length=32)
    target_group: str = Field(default="", max_length=50)
    apply_time: str = Field(default="", max_length=100)
    description: str = Field(default="")
    priority: PathwayPriority = "P2"
    data_status: PathwayDataStatus = "planned"
    year: int = Field(default=0, description="数据所属年份")
    source: SourceInput = Field(default_factory=SourceInput)


class PathwayRuleWriteRequest(BaseModel):
    """途径资格规则写入（产品书 6.6.7；tasks.md 8.6）。

    规则必须附官方来源：``source`` 三要素缺一即返回 4001，规则不入库。
    """

    pathway_id: str = Field(min_length=1, max_length=32)
    province: str = Field(default="", max_length=20, description="适用省份，空表示通用")
    rule_type: RuleType
    rule_desc: str = Field(default="", description="规则条文，前端可展开")
    params: dict[str, Any] = Field(default_factory=dict, description="规则参数")
    year: int = Field(default=0, description="数据所属年份")
    source: SourceInput = Field(default_factory=SourceInput)


# --------------------------------------------------------------------------- #
# 报考约束规则维护（产品书 6.6，v1.1 新增三组）
#   province-rules / subject-requirements / physical-restrictions
#   三组都必须带 year（2025 / 2026 并存），缺 year 或来源 → 4001
# --------------------------------------------------------------------------- #
class ProvinceRuleWriteRequest(BaseModel):
    """省份志愿模式模板写入（产品书 6.6；7.6 province_exam_rule）。"""

    province: str = Field(min_length=1, max_length=20)
    year: int = Field(default=0, description="规则年份，必填且 2000–2100")
    batch: str = Field(min_length=1, max_length=32, description="如 本科批 / 提前批")
    mode: str = Field(default="group", max_length=16, description="group / major_school / school_major")
    volunteer_count: int = Field(default=0, ge=0, description="志愿单位数 48 / 45 / 64")
    majors_per_group: int | None = Field(default=None, ge=0)
    has_adjust: bool = False
    admit_method: str = Field(default="parallel", max_length=16)
    ratio: str = Field(default="1:1", max_length=32)
    tie_rule: str = Field(default="", max_length=200)
    mutex_groups: list[str] = Field(default_factory=list)
    collect_count: int | None = Field(default=None, ge=0)
    source: SourceInput = Field(default_factory=SourceInput)


class SubjectRequirementWriteRequest(BaseModel):
    """选科要求写入（产品书 6.6；7.6 subject_requirement）。"""

    province: str = Field(min_length=1, max_length=20)
    year: int = Field(default=0)
    batch: str = Field(default="", max_length=32)
    school_id: int | None = None
    group_code: str | None = Field(default=None, max_length=32)
    major_id: int | None = None
    first_subject: str = Field(default="", max_length=16, description="物理 / 历史 / 不限")
    secondary_subjects: list[str] = Field(default_factory=list)
    logic: str = Field(default="all", max_length=8, description="all / any")
    source: SourceInput = Field(default_factory=SourceInput)


class PhysicalRestrictionWriteRequest(BaseModel):
    """身体条件限制写入（产品书 6.6；7.6 physical_restriction）。

    ``level`` 只允许 ``reject`` / ``not_suitable``，二者不得混同（8.5 闸门 3）。
    """

    condition: str = Field(min_length=1, max_length=64, description="色弱 / 色盲 / 裸眼视力 / 乙肝…")
    threshold: str = Field(default="", max_length=128, description="如 <5.0 / 携带")
    major_category: str = Field(default="", max_length=50)
    major_code: str = Field(default="", max_length=32)
    level: Literal["reject", "not_suitable"]
    detail: str = Field(default="", description="依据原文")
    province: str = Field(default="", max_length=20, description="空表示全国")
    year: int = Field(default=0)
    source: SourceInput = Field(default_factory=SourceInput)


# 审核动作（产品书 6.6.10）：通过 / 修正 / 驳回
ReviewAction = Literal["approve", "correct", "reject"]


class ReviewDecisionRequest(BaseModel):
    """人工审核决策（产品书 6.6.10 POST /review/tasks/{id}；tasks.md 8.5）。

    - ``approve``：认可原答案；
    - ``correct``：提交修正答案，**必须**带 ``corrected_answer``（缺失由服务层返回 1001），
      修正内容沉淀回知识库（缺来源时不沉淀，见 services/review.py）；
    - ``reject``：驳回，原答案不作为结论，任务留痕可追踪。
    """

    action: ReviewAction
    corrected_answer: str = Field(default="", description="修正后的答案，action=correct 时必填")
    comment: str = Field(default="", max_length=500, description="审核备注，随留痕保存")


# 索引重建范围（产品书 6.6.4）
IndexScope = Literal["all", "doc_ids"]


class IndexRebuildRequest(BaseModel):
    """索引重建请求（产品书 6.6.4 POST /index/rebuild；tasks.md 8.3）。

    - ``scope=all``：全部切片；``scope=doc_ids``：仅 ``doc_ids`` 指定文档的切片（此时必须给 doc_ids）；
    - ``incremental=True``：只处理未向量化（``embedding`` 为空）的切片，即「增量重建」；
    - 缺 ``doc_ids``、文档不存在、已有任务在执行 → 由服务层返回 1001。
    """

    scope: IndexScope = "all"
    doc_ids: list[int] = Field(default_factory=list, description="scope=doc_ids 时的目标文档")
    incremental: bool = Field(default=True, description="真=仅未向量化切片，假=全量重算")
