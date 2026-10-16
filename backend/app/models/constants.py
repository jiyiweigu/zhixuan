"""数据模型共享常量（产品书第 7 章「数据模型与数据字典」）。

集中定义年份、分数、长度等边界，供各事实表的 CHECK 约束与列长度复用，
避免魔法值散落各处（第 7 章「通用要求：枚举字段用常量，禁止魔法值」）。
"""

from __future__ import annotations

# 年份合理区间：与 app/core/dataset.py 的来源校验口径保持一致
YEAR_MIN = 2000
YEAR_MAX = 2100

# 高考分数合理区间（满分为 750 分的省份口径）
SCORE_MIN = 0
SCORE_MAX = 750

# 常用列长度
PROVINCE_MAX_LENGTH = 20
SUBJECT_TYPE_MAX_LENGTH = 20
PATHWAY_ID_MAX_LENGTH = 32
USER_ID_MAX_LENGTH = 64

# 生活信息可靠性标注（产品书 7.4 school_life.reliability；tasks.md 7.3）
# official 视为官方来源，unofficial 在前端默认折叠并显示「仅供参考」
RELIABILITY_OFFICIAL = "official"
RELIABILITY_UNOFFICIAL = "unofficial"
RELIABILITY_VALUES = (RELIABILITY_OFFICIAL, RELIABILITY_UNOFFICIAL)

# 院校并排对比的校数上限（产品书 6.5.5「建议 ≤5」，此处落为硬上限）
MAX_COMPARE_SCHOOLS = 5

# --------------------------------------------------------------------------- #
# 报考约束（产品书 7.6 三张规则表 + 8.5 四道闸门）
# --------------------------------------------------------------------------- #

# 单次批量校验的志愿单位上限（产品书 6.2.7：items ≤100）
MAX_CHECK_UNITS = 100

# 省份志愿模式（产品书 6.2.6 province_exam_rule.mode）
EXAM_MODE_GROUP = "group"  # 院校专业组
EXAM_MODE_MAJOR_SCHOOL = "major_school"  # 专业 + 院校
EXAM_MODE_SCHOOL_MAJOR = "school_major"  # 老高考：院校 + 专业
EXAM_MODE_VALUES: tuple[str, ...] = (
    EXAM_MODE_GROUP,
    EXAM_MODE_MAJOR_SCHOOL,
    EXAM_MODE_SCHOOL_MAJOR,
)

# 投档方式（产品书 6.2.6 admit_method）
ADMIT_METHOD_PARALLEL = "parallel"
ADMIT_METHOD_SINGLE = "single"
ADMIT_METHOD_VALUES: tuple[str, ...] = (ADMIT_METHOD_PARALLEL, ADMIT_METHOD_SINGLE)

# 选科匹配逻辑（产品书 7.6 subject_requirement.logic）
SUBJECT_LOGIC_ALL = "all"
SUBJECT_LOGIC_ANY = "any"
SUBJECT_LOGIC_VALUES: tuple[str, ...] = (SUBJECT_LOGIC_ALL, SUBJECT_LOGIC_ANY)

# 身体条件限制级别（产品书 7.6 physical_restriction.level）
# reject = 不合格 = 不予录取（硬拦 → blockers）
# not_suitable = 合格不宜 = 不宜就读（软提示 → warnings）
RESTRICTION_REJECT = "reject"
RESTRICTION_NOT_SUITABLE = "not_suitable"
RESTRICTION_LEVEL_VALUES: tuple[str, ...] = (
    RESTRICTION_REJECT,
    RESTRICTION_NOT_SUITABLE,
)

# 约束命中类型（契约 8.4 blockers[].type 取值，唯一取值见 docs/api-contract.md 8.4）
CONSTRAINT_TYPE_SUBJECT = "subject"
CONSTRAINT_TYPE_PHYSICAL = "physical"
CONSTRAINT_TYPE_FEE = "fee"
CONSTRAINT_TYPE_PROVINCE_RULE = "province_rule"
CONSTRAINT_TYPE_SCORE = "score"
CONSTRAINT_TYPE_LANGUAGE = "language"
CONSTRAINT_TYPE_GENDER = "gender"
CONSTRAINT_TYPE_BATCH = "batch"
CONSTRAINT_TYPE_PATHWAY = "pathway"
CONSTRAINT_TYPE_VALUES: tuple[str, ...] = (
    CONSTRAINT_TYPE_PROVINCE_RULE,
    CONSTRAINT_TYPE_SUBJECT,
    CONSTRAINT_TYPE_PHYSICAL,
    CONSTRAINT_TYPE_FEE,
    CONSTRAINT_TYPE_SCORE,
    CONSTRAINT_TYPE_LANGUAGE,
    CONSTRAINT_TYPE_GENDER,
    CONSTRAINT_TYPE_BATCH,
    CONSTRAINT_TYPE_PATHWAY,
)

# 三档结果（产品书 8.5；前后端统一，禁止一刀切）
LEVEL_REJECT = "reject"
LEVEL_NOT_SUITABLE = "not_suitable"
LEVEL_UNKNOWN = "unknown"

# 视力判定线（产品书 6.1.4：后端按 5.0、4.8 两条线判定）
VISION_LINE_50 = 5.0
VISION_LINE_48 = 4.8

# 色觉取值（产品书 6.1.4 color_vision）
COLOR_VISION_NORMAL = "正常"
COLOR_VISION_WEAK = "色弱"
COLOR_VISION_BLIND = "色盲"
COLOR_VISION_NO_DISTINCT = "不能识别红黄绿蓝紫任一色"
COLOR_VISION_VALUES: tuple[str, ...] = (
    COLOR_VISION_NORMAL,
    COLOR_VISION_WEAK,
    COLOR_VISION_BLIND,
    COLOR_VISION_NO_DISTINCT,
)

# 听力 / 嗅觉 / 口吃取值（产品书 6.1.4）
PHYSICAL_STATE_NORMAL = "正常"
PHYSICAL_STATE_ABNORMAL = "异常"
PHYSICAL_STATE_UNFILLED = "未填"
PHYSICAL_STATE_VALUES: tuple[str, ...] = (
    PHYSICAL_STATE_NORMAL,
    PHYSICAL_STATE_ABNORMAL,
    PHYSICAL_STATE_UNFILLED,
)

# --------------------------------------------------------------------------- #
# 跨层词表（docs/api-contract.md「统一约定 · 跨层词表」，唯一取值，禁止各层自造）
# --------------------------------------------------------------------------- #

# 数据完备度：全项目唯一取值（契约 8.1 / 统一约定）
DATA_STATUS_AVAILABLE = "available"
DATA_STATUS_PARTIAL = "partial"
DATA_STATUS_SCHEMA_ONLY = "schema_only"
DATA_STATUS_UNAVAILABLE = "unavailable"
DATA_STATUS_VALUES: tuple[str, ...] = (
    DATA_STATUS_AVAILABLE,
    DATA_STATUS_PARTIAL,
    DATA_STATUS_SCHEMA_ONLY,
    DATA_STATUS_UNAVAILABLE,
)

# 考试类型：数据源原始列名为 category_group，导入时必须映射为 exam_type（契约 8.7）
EXAM_TYPE_NORMAL = "普通"
EXAM_TYPE_ART = "艺术"
EXAM_TYPE_SPORTS = "体育"
EXAM_TYPE_VALUES: tuple[str, ...] = (EXAM_TYPE_NORMAL, EXAM_TYPE_ART, EXAM_TYPE_SPORTS)

# 规则数据集：rule_dataset_status.dataset 与 8.8 批量导入的 dataset 取值
DATASET_PROVINCE_EXAM_RULE = "province_exam_rule"
DATASET_SUBJECT_REQUIREMENT = "subject_requirement"
DATASET_PHYSICAL_RESTRICTION = "physical_restriction"
DATASET_ADMISSION_REQUIREMENT = "admission_requirement"
DATASET_MAJOR_TUITION = "major_tuition"
DATASET_VALUES: tuple[str, ...] = (
    DATASET_PROVINCE_EXAM_RULE,
    DATASET_SUBJECT_REQUIREMENT,
    DATASET_PHYSICAL_RESTRICTION,
    DATASET_ADMISSION_REQUIREMENT,
    DATASET_MAJOR_TUITION,
)

# 章程要求类型（契约 8.7 admission_requirement.requirement_type）
REQUIREMENT_TYPE_SINGLE_SUBJECT = "single_subject"
REQUIREMENT_TYPE_LANGUAGE = "language"
REQUIREMENT_TYPE_GENDER = "gender"
REQUIREMENT_TYPE_INTERVIEW = "interview"
REQUIREMENT_TYPE_POLITICAL_REVIEW = "political_review"
REQUIREMENT_TYPE_PHYSICAL_TEST = "physical_test"
REQUIREMENT_TYPE_VALUES: tuple[str, ...] = (
    REQUIREMENT_TYPE_SINGLE_SUBJECT,
    REQUIREMENT_TYPE_LANGUAGE,
    REQUIREMENT_TYPE_GENDER,
    REQUIREMENT_TYPE_INTERVIEW,
    REQUIREMENT_TYPE_POLITICAL_REVIEW,
    REQUIREMENT_TYPE_PHYSICAL_TEST,
)

# 身体条件阈值操作符（契约 8.6 physical_restrictions[].threshold.operator）
THRESHOLD_OPERATOR_IN = "in"
THRESHOLD_OPERATOR_EQ = "eq"
THRESHOLD_OPERATOR_LT = "lt"
THRESHOLD_OPERATOR_LTE = "lte"
THRESHOLD_OPERATOR_GT = "gt"
THRESHOLD_OPERATOR_GTE = "gte"
THRESHOLD_OPERATOR_BETWEEN = "between"
THRESHOLD_OPERATOR_VALUES: tuple[str, ...] = (
    THRESHOLD_OPERATOR_IN,
    THRESHOLD_OPERATOR_EQ,
    THRESHOLD_OPERATOR_LT,
    THRESHOLD_OPERATOR_LTE,
    THRESHOLD_OPERATOR_GT,
    THRESHOLD_OPERATOR_GTE,
    THRESHOLD_OPERATOR_BETWEEN,
)

# 首期批次：``batch`` 只作展示，``batch_code`` 是唯一键（契约 8.3/8.7）。
# 河南叫「普通本科批」、江西叫「本科批次」，经 batch_code 归一后不得再区分；
# batch_code 取值与数据侧 data/dictionaries/province-exam-rule.json 同源。
BATCH_DISPLAY_UG = "本科批"
BATCH_CODE_UG = "undergraduate_regular"
BATCH_CODE_EARLY = "undergraduate_early"
BATCH_CODE_VOCATIONAL = "vocational_regular"
BATCH_CODE_ART_SPORT = "undergraduate_art_sport"

# 展示名 → 机器键（首期别名收敛表；未知展示名原样返回，交数据侧补登）
BATCH_ALIAS_TO_CODE: dict[str, str] = {
    "本科批": BATCH_CODE_UG,
    "普通本科批": BATCH_CODE_UG,
    "本科批次": BATCH_CODE_UG,
    "本科": BATCH_CODE_UG,                      # 江西招生计划口径（2024 选科数据实测）
    "提前批": BATCH_CODE_EARLY,
    "普通本科提前批": BATCH_CODE_EARLY,
    "提前本科": BATCH_CODE_EARLY,                # 江西招生计划口径
    "高职（专科）批": BATCH_CODE_VOCATIONAL,
    "高职（专科）批次": BATCH_CODE_VOCATIONAL,
    "高职(专科)": BATCH_CODE_VOCATIONAL,         # 江西招生计划口径（半角括号）
    "专科批": BATCH_CODE_VOCATIONAL,             # 河南招生计划口径
    "艺术类/体育类本科批次": BATCH_CODE_ART_SPORT,
}

# 首期试点省份（产品书：河南第一、江西第二）
PROVINCE_CODE_HENAN = "41"
PROVINCE_CODE_JIANGXI = "36"
PROVINCE_NAME_BY_CODE: dict[str, str] = {
    PROVINCE_CODE_HENAN: "河南",
    PROVINCE_CODE_JIANGXI: "江西",
}
PROVINCE_CODE_BY_NAME: dict[str, str] = {
    name: code for code, name in PROVINCE_NAME_BY_CODE.items()
}


def batch_code_of(batch: str) -> str:
    """把批次展示名归一为 ``batch_code``；传入的已是机器键时原样返回。"""
    value = str(batch or "").strip()
    if not value:
        return BATCH_CODE_UG
    return BATCH_ALIAS_TO_CODE.get(value, value)


def province_code_of(province: str) -> str:
    """把省名归一为两位省代码；已是代码则原样返回。

    与契约 8.3 / 8.6 的入参口径一致（``41`` / ``36``），同时兼容历史入参的省名，
    避免老调用方直接 3001。
    """
    value = str(province or "").strip()
    if value in PROVINCE_NAME_BY_CODE:
        return value
    return PROVINCE_CODE_BY_NAME.get(value, value)


def province_name_of(code: str) -> str:
    """把两位省代码归一为省名；未知时原样返回。"""
    value = str(code or "").strip()
    return PROVINCE_NAME_BY_CODE.get(value, value)

