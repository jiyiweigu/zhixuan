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

# 约束命中类型（产品书 6.2.7 blockers[].type 取值）
CONSTRAINT_TYPE_SUBJECT = "选科"
CONSTRAINT_TYPE_PHYSICAL = "physical"
CONSTRAINT_TYPE_FEE = "fee"
CONSTRAINT_TYPE_PROVINCE_RULE = "province_rule"
CONSTRAINT_TYPE_SCORE = "score"
CONSTRAINT_TYPE_LANGUAGE = "language"
CONSTRAINT_TYPE_GENDER = "gender"
CONSTRAINT_TYPE_BATCH = "batch"

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
