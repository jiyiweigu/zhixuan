"""管理端请求模型（产品书 6.6；tasks.md 8.1、8.2、8.6）。

按模块分节，字段名一律 snake_case，与产品书第 6 章保持一致。
所有模型均为新增，不影响既有 C 端接口的入参。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# 途径优先级与数据状态（产品书 6.6.6）
# data_status 用契约「跨层词表」的四值，禁止 `ready` / `planned` 等自造写法
PathwayPriority = Literal["P0", "P1", "P2"]
DataStatus = Literal["available", "partial", "schema_only", "unavailable"]
# 资格规则类型（产品书 7.2 pathway_eligibility.rule_type）
RuleType = Literal["户籍", "学籍", "区域", "成绩"]
# 考试类型（契约跨层词表：数据源 category_group 须映射到这三个值）
ExamType = Literal["普通", "艺术", "体育"]
# 规则数据集（契约 8.7 / 8.8）
RuleDataset = Literal[
    "province_exam_rule",
    "subject_requirement",
    "physical_restriction",
    "admission_requirement",
    "major_tuition",
]
# 章程要求类型（契约 8.7）
RequirementType = Literal[
    "single_subject", "language", "gender", "interview", "political_review", "physical_test"
]
RestrictionLevel = Literal["reject", "not_suitable"]
# 单次批量导入上限（契约 8.8）
MAX_IMPORT_ITEMS = 500

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
    data_status: DataStatus = "schema_only"
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
    """省份志愿模式模板写入（产品书 6.6；契约 8.7 province_exam_rule）。

    ``batch`` 是展示名，``batch_code`` 是唯一键；``exam_type`` 由数据源
    ``category_group`` 映射而来（契约 8.7 硬约束）。三者缺省时由服务层按
    展示名 / 省名推导，避免管理端漏填即写入无效规则。
    """

    province: str = Field(min_length=1, max_length=20)
    province_code: str = Field(default="", max_length=32, description="两位省代码，如 41；缺省按省名推导")
    year: int = Field(default=0, description="规则年份，必填且 2000–2100")
    batch: str = Field(min_length=1, max_length=32, description="批次展示名，如 本科批 / 提前批")
    batch_code: str = Field(default="", max_length=32, description="批次机器键；缺省按展示名推导")
    exam_type: ExamType = "普通"
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
    """选科要求写入（产品书 6.6；契约 8.7 subject_requirement）。"""

    province: str = Field(default="", max_length=20)
    province_code: str = Field(default="", max_length=32)
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
    """身体条件限制写入（产品书 6.6；契约 8.7 physical_restriction）。

    ``level`` 只允许 ``reject`` / ``not_suitable``，二者不得混同（契约闸门 3）。
    """

    condition: str = Field(min_length=1, max_length=64, description="色弱 / 色盲 / 裸眼视力 / 乙肝…")
    threshold: str = Field(default="", max_length=128, description="如 <5.0 / 携带")
    major_category: str = Field(default="", max_length=50)
    major_code: str = Field(default="", max_length=32)
    level: RestrictionLevel
    detail: str = Field(default="", description="依据原文")
    province: str = Field(default="", max_length=20, description="空表示全国")
    province_code: str = Field(default="", max_length=32)
    year: int = Field(default=0)
    source: SourceInput = Field(default_factory=SourceInput)


# --------------------------------------------------------------------------- #
# 报考约束规则维护（契约 8.8，v1.2 新增四组）
#   admission-requirements / major-tuition / rule-dataset-status / rule-datasets/import
# --------------------------------------------------------------------------- #
class AdmissionRequirementWriteRequest(BaseModel):
    """章程要求写入（契约 8.7 ``admission_requirement``；支撑 8.6 ``enrollment_notes``）。

    承载单科、语种、性别、面试 / 政审 / 体测等要求，**不得**塞进身体限制表。
    """

    province_code: str = Field(default="", max_length=32)
    province: str = Field(default="", max_length=20, description="展示名，可由 province_code 推导")
    year: int = Field(default=0)
    school_id: int | None = None
    major_id: int | None = None
    requirement_type: RequirementType
    requirement_value: dict[str, Any] = Field(
        default_factory=dict, description="按 requirement_type 取形状，如 {subject, minimum_score}"
    )
    level: RestrictionLevel = "reject"
    detail: str = Field(default="")
    source: SourceInput = Field(default_factory=SourceInput)


class MajorTuitionWriteRequest(BaseModel):
    """专业学费写入（契约 8.7 ``major_tuition``；闸门 4 与 8.6 ``tuition``）。

    学费按具体学校 / 专业 / 年份存储；不得仅以办学性质估算值冒充正式数据。
    """

    province_code: str = Field(default="", max_length=32)
    province: str = Field(default="", max_length=20)
    year: int = Field(default=0)
    school_id: int | None = None
    major_id: int | None = None
    amount: float | None = Field(default=None, ge=0, description="元/年；未知时留空并列入 missing_rule_sets")
    currency: str = Field(default="CNY", max_length=8)
    period: str = Field(default="year", max_length=8)
    ownership: str = Field(default="", max_length=32, description="公办 / 民办 / 中外合作…")
    note: str = Field(default="", description="计费说明")
    source: SourceInput = Field(default_factory=SourceInput)


class RuleDatasetStatusWriteRequest(BaseModel):
    """规则集状态写入（契约 8.7 ``rule_dataset_status``；8.8 ``PUT /rule-dataset-status``）。

    ``status=available`` **不允许**手工强制设置（契约 8.8 明确要求由导入覆盖率得出），
    提交会被拒并返回 1001。
    """

    province_code: str = Field(min_length=1, max_length=32)
    year: int = Field(default=0)
    batch_code: str = Field(default="", max_length=32)
    exam_type: ExamType = "普通"
    dataset: RuleDataset
    status: DataStatus = "schema_only"
    note: str = Field(default="", description="状态说明，如“名单待核验”")


class RuleDatasetImportRequest(BaseModel):
    """批量规则导入（契约 8.8 ``POST /rule-datasets/import``）。

    单次最多 500 条；**全批事务写入**，任一项校验失败整批回滚（由服务层实现）。
    导入成功后由服务层按覆盖率重算对应 ``rule_dataset_status``。
    """

    dataset: RuleDataset
    province_code: str = Field(min_length=1, max_length=32)
    year: int = Field(default=0)
    batch_code: str = Field(default="", max_length=32)
    exam_type: ExamType = "普通"
    items: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def max_items(self) -> int:
        return MAX_IMPORT_ITEMS


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
