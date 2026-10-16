"""报考约束业务层（产品书 6.2.6–6.2.9；8.5 四道闸门的数据与编排）。

本层只做两件事：**从规则表读数据**（IO）+ **调用纯函数引擎**（app/engine/constraints.py）。
判定逻辑一律在引擎里，服务层不做二次改判，避免"双份真相"（8.5 风险清单）。

契约对齐（docs/api-contract.md v1.6）：

- 8.3 ``GET /api/provinces/{code}/rules``：入参是**两位省代码**（河南 ``41`` / 江西 ``36``），
  出参含 ``province_code`` / ``batch_code`` / ``exam_type`` / ``data_status`` / 嵌套 ``rule`` /
  ``sources`` / ``missing_rule_sets``；**无对应版本仍返回 200 + ``unavailable``**，不返回虚构模板；
- 8.4 / 8.5 ``POST /api/eligibility/check``：出参首字段为 ``data_status``，并含 ``data_years``
  （各规则集实际数据年度；按"不晚于报考年份的最近可得年度"取数，用到滞后年度时
  结果标 ``partial``，同一 ``school_id + group_code`` 的多科类变体按考生首选科目选择）；
- 8.6 ``GET /api/majors/{id}/requirements``：``threshold`` 为对象、``tuition`` 完整、
  缺失规则集列入 ``missing_rule_sets``、未知要求用 ``null`` 而不是空数组冒充"无限制"；
  体检类级匹配走「专业代码前 4 位 → 专业类名」（``_rule_targets_major``）。

规则数据缺失 → **校验接口**返回 ``3001``，绝不静默放行（8.5 实现纪律第 3 条、7.6 约束第 5 条）：

- 执行校验所必需的规则集（省份模板 / 选科 / 身体条件）任一缺失 → 3001
- 可选规则集（学费 / 章程要求）缺失 → 降级为 ``partial``，相关闸门进 ``unknowns``

``null``（未填）只进 ``unknowns``，不判合格（8.1）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.response import BizCode, BizError
from app.engine import constraints as engine
from app.models.base_data import Major
from app.models.constants import (
    BATCH_DISPLAY_UG,
    DATA_STATUS_AVAILABLE,
    DATA_STATUS_PARTIAL,
    DATA_STATUS_SCHEMA_ONLY,
    DATA_STATUS_UNAVAILABLE,
    DATA_STATUS_VALUES,
    DATASET_ADMISSION_REQUIREMENT,
    DATASET_MAJOR_TUITION,
    DATASET_PHYSICAL_RESTRICTION,
    DATASET_PROVINCE_EXAM_RULE,
    DATASET_SUBJECT_REQUIREMENT,
    DATASET_VALUES,
    EXAM_TYPE_NORMAL,
    REQUIREMENT_TYPE_GENDER,
    REQUIREMENT_TYPE_INTERVIEW,
    REQUIREMENT_TYPE_LANGUAGE,
    REQUIREMENT_TYPE_PHYSICAL_TEST,
    REQUIREMENT_TYPE_POLITICAL_REVIEW,
    REQUIREMENT_TYPE_SINGLE_SUBJECT,
    batch_code_of,
    province_code_of,
    province_name_of,
)
from app.models.constraints import (
    AdmissionRequirement,
    MajorTuition,
    PhysicalRestriction,
    ProvinceExamRule,
    RuleDatasetStatus,
    SubjectRequirement,
)
from app.models.source import Source
from app.services import profile as profile_service

DEFAULT_BATCH = BATCH_DISPLAY_UG

# 执行一批校验所必需 / 可选的规则集（契约 8.4：必需集缺失 → 3001，可选集缺失 → partial）
REQUIRED_DATASETS: tuple[str, ...] = (
    DATASET_PROVINCE_EXAM_RULE,
    DATASET_SUBJECT_REQUIREMENT,
    DATASET_PHYSICAL_RESTRICTION,
)
OPTIONAL_DATASETS: tuple[str, ...] = (
    DATASET_MAJOR_TUITION,
    DATASET_ADMISSION_REQUIREMENT,
)


# --------------------------------------------------------------------------- #
# 通用小工具
# --------------------------------------------------------------------------- #
def _citation_of(source: Source | None) -> dict[str, Any]:
    if source is None:
        return {"source_name": "", "source_url": "", "year": 0}
    return {
        "source_name": source.source_name,
        "source_url": source.source_url,
        "year": source.year,
    }


def _sources_of(db: Session, source_ids: Sequence[int | None]) -> dict[int, Source]:
    ids = sorted({sid for sid in source_ids if sid})
    if not ids:
        return {}
    rows = db.scalars(select(Source).where(Source.id.in_(ids))).all()
    return {row.id: row for row in rows}


def _rule_missing(
    message: str,
    *,
    data_status: str,
    missing: Sequence[str],
    years: Mapping[str, int | None] | None = None,
) -> BizError:
    """构造 3001：``data`` 说明缺失数据集（契约 8.4 错误示例）。

    ``years`` 提供时附带各规则集的实际数据年度（按数据集最近可得年度取数，
    见 ``_resolve_rule_years``），便于定位"缺的是哪一年的数据"。
    """
    data: dict[str, Any] = {
        "data_status": data_status,
        "missing_rule_sets": sorted(set(missing)),
    }
    if years:
        data["data_years"] = {ds: years.get(ds) for ds in DATASET_VALUES}
    return BizError(message, BizCode.RULE_MISSING, data=data)


def _code_base(code: Any) -> str:
    """专业代码归一：去首尾空白、转大写，并去掉末位 K/T 标记（国控/特设标记不参与匹配）。"""
    return str(code or "").strip().upper().rstrip("KT")


def _class_name_by_major(db: Session, majors: Sequence[Major]) -> dict[int, str]:
    """专业 id → 专业类名（用专业代码前 4 位查 major 表 ``is_category=1`` 行）。

    major 表的既定设计（见 ``app/services/importers/majors.py``）：
    - ``major.category`` 存**学科门类**（如「医学」），不是专业类；
    - 93 个专业类以 ``is_category=1`` 行承载（如 code=1007 → 「药学类」），
      专业 → 专业类的从属关系由 **code 前 4 位**表达（100701 → 1007）。

    体检规则的 ``major_category`` 是专业类名，因此类级匹配必须走这条派生链，
    不能直接拿 ``major.category``（门类）去比。
    """
    prefixes = {_code_base(major.code)[:4] for major in majors if len(_code_base(major.code)) >= 4}
    if not prefixes:
        return {}
    rows = db.scalars(
        select(Major).where(Major.is_category.is_(True), Major.code.in_(sorted(prefixes)))
    ).all()
    name_by_prefix = {str(row.code or "").strip(): row.name for row in rows}
    result: dict[int, str] = {}
    for major in majors:
        prefix = _code_base(major.code)[:4]
        if prefix and prefix in name_by_prefix:
            result[major.id] = name_by_prefix[prefix]
    return result


def _rule_targets_major(
    rule_code: Any, rule_category: Any, major: Major, class_name: str | None
) -> bool:
    """体检规则是否命中某专业（单一真源，8.6 与 8.4 共用）。

    口径（与体检规则生成器 ``build_physical_restriction_import.py`` 对齐）：

    - 专业级条目（``major_code`` 非空）：代码归一后精确相等（K/T 后缀不影响）；
    - 类级条目（``major_category`` 非空）：与「专业代码前 4 位对应的专业类名」
      精确相等（如 100701 → 1007 → 药学类）。同时保留与 ``major.category``
      的精确相等，兼容把专业类名写进 category 列的历史种子数据
      （``constraint_seed``，测试环境用）。
    - **点名专业不上卷到类、类级条目也不下卷到专业**——不做任何扩展匹配。

    无 code 也无 category 的条目由调用方按"适用范围未知"单独处理，不走本函数。
    """
    code = _code_base(rule_code)
    if code:
        return code == _code_base(getattr(major, "code", ""))
    category = str(rule_category or "").strip()
    if not category:
        return False
    if class_name and category == class_name:
        return True
    return category == str(getattr(major, "category", "") or "").strip()


def _as_str_list(raw: Any) -> list[str]:
    """把库里的 ``mutex_groups`` 归一为字符串列表。

    数据侧可能给数组（``["艺术类与体育类不能兼报"]``）也可能给带 ``note`` 的对象
    （``{"提前批各类不得兼报": [...], "note": "…"}``）。对象形态按键与取值展开，
    跳过纯说明性的 ``note``，避免把整段散文当成"互斥组"。
    """
    if isinstance(raw, Mapping):
        out: list[str] = []
        for key, value in raw.items():
            if str(key).strip().lower() == "note":
                continue
            if isinstance(value, (list, tuple, set)):
                if str(key).strip():
                    out.append(str(key).strip())
                out.extend(str(item).strip() for item in value if str(item).strip())
            elif str(value).strip():
                out.append(str(value).strip())
        return out
    if isinstance(raw, (list, tuple, set)):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


def threshold_object(raw: Any) -> dict[str, Any] | None:
    """把库里 ``threshold`` 的自由文本转成契约 8.6 的 ``{operator, value}`` 对象。

    - ``"<5.0"`` / ``"<=5.0"`` / ``">170"`` / ``">=170"`` → ``lt`` / ``lte`` / ``gt`` / ``gte`` + 数值；
    - ``"1.0-2.0"`` 形态 → ``between`` + ``[lo, hi]``；
    - 其余（``"携带"`` / ``"异常"`` / ``"不限"``）→ ``in`` + 原字面量数组。

    始终保持"库里是什么就说什么"，不臆造阈值语义。
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if "—" in text or "~" in text:
        text = text.replace("—", "-").replace("~", "-")
    range_parts = [part.strip() for part in text.split("-") if part.strip()]
    if len(range_parts) == 2 and all(_is_number(part) for part in range_parts):
        return {"operator": "between", "value": [float(range_parts[0]), float(range_parts[1])]}
    for prefix, operator in (("<=", "lte"), (">=", "gte"), ("<", "lt"), (">", "gt")):
        if text.startswith(prefix):
            number = _to_number(text[len(prefix) :])
            if number is not None:
                return {"operator": operator, "value": number}
    return {"operator": "in", "value": [text]}


def _is_number(text: str) -> bool:
    return _to_number(text) is not None


def _to_number(text: str) -> float | None:
    cleaned = "".join(ch for ch in str(text) if ch.isdigit() or ch == ".")
    if not cleaned or cleaned == ".":
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# 规则集 data_status（契约 8.1 四值；8.7 rule_dataset_status 是唯一来源）
# --------------------------------------------------------------------------- #
def _count(db: Session, model: Any, *conditions: Any) -> int:
    stmt = select(func.count()).select_from(model)
    for condition in conditions:
        stmt = stmt.where(condition)
    return int(db.scalar(stmt) or 0)


def dataset_presence(
    db: Session, dataset: str, province_code: str, year: int, batch_code: str
) -> bool:
    """该规则集在本省本年是否真的有数据（用于推导 data_status）。"""
    province_name = province_name_of(province_code)
    province_match = lambda column: (column == province_code) | (column == "")  # noqa: E731
    if dataset == DATASET_PROVINCE_EXAM_RULE:
        return _count(
            db, ProvinceExamRule,
            ProvinceExamRule.province_code == province_code,
            ProvinceExamRule.year == year,
            ProvinceExamRule.batch_code == batch_code,
        ) > 0
    if dataset == DATASET_SUBJECT_REQUIREMENT:
        return _count(
            db, SubjectRequirement,
            province_match(SubjectRequirement.province_code)
            | (SubjectRequirement.province == province_name),
            SubjectRequirement.year == year,
        ) > 0
    if dataset == DATASET_PHYSICAL_RESTRICTION:
        return _count(
            db, PhysicalRestriction,
            province_match(PhysicalRestriction.province_code)
            | (PhysicalRestriction.province == province_name),
            PhysicalRestriction.year == year,
        ) > 0
    if dataset == DATASET_MAJOR_TUITION:
        return _count(
            db, MajorTuition,
            province_match(MajorTuition.province_code),
            MajorTuition.year == year,
        ) > 0
    if dataset == DATASET_ADMISSION_REQUIREMENT:
        return _count(
            db, AdmissionRequirement,
            province_match(AdmissionRequirement.province_code),
            AdmissionRequirement.year == year,
        ) > 0
    return False


def _latest_year_with_presence(
    db: Session, dataset: str, province_code: str, target_year: int, batch_code: str
) -> int | None:
    """该数据集「不晚于目标年份」的最近可得年份；无 → ``None``。

    **绝不向未来借数据**：目标年份之后才有的规则一律不用（考 2026 不能拿
    2027 的规则判）。口径与 ``dataset_presence`` 保持同一套条件。
    """
    province_name = province_name_of(province_code)
    province_match = lambda column: (column == province_code) | (column == "")  # noqa: E731
    if dataset == DATASET_PROVINCE_EXAM_RULE:
        return db.scalar(
            select(func.max(ProvinceExamRule.year)).where(
                ProvinceExamRule.province_code == province_code,
                ProvinceExamRule.batch_code == batch_code,
                ProvinceExamRule.year <= target_year,
            )
        )
    if dataset == DATASET_SUBJECT_REQUIREMENT:
        return db.scalar(
            select(func.max(SubjectRequirement.year)).where(
                province_match(SubjectRequirement.province_code)
                | (SubjectRequirement.province == province_name),
                SubjectRequirement.year <= target_year,
            )
        )
    if dataset == DATASET_PHYSICAL_RESTRICTION:
        return db.scalar(
            select(func.max(PhysicalRestriction.year)).where(
                province_match(PhysicalRestriction.province_code)
                | (PhysicalRestriction.province == province_name),
                PhysicalRestriction.year <= target_year,
            )
        )
    if dataset == DATASET_MAJOR_TUITION:
        return db.scalar(
            select(func.max(MajorTuition.year)).where(
                province_match(MajorTuition.province_code),
                MajorTuition.year <= target_year,
            )
        )
    if dataset == DATASET_ADMISSION_REQUIREMENT:
        return db.scalar(
            select(func.max(AdmissionRequirement.year)).where(
                province_match(AdmissionRequirement.province_code),
                AdmissionRequirement.year <= target_year,
            )
        )
    return None


def _resolve_rule_years(
    db: Session, province_code: str, target_year: int, batch_code: str
) -> dict[str, int | None]:
    """按数据集解析"最近可得年度"（契约 8.4/8.6 的 ``data_years`` 口径）。

    各规则集的发布节奏不同（省份模板/体检规则按年、选科要求提前发布且常滞后
    一年），而校验必须按**考生报考年份**一次定位全部规则。本函数为每个数据集
    取「不晚于目标年份的最近可得年份」，出接口时如实回传 ``data_years``，
    并据此把结果标 ``partial``——**不静默用旧数据冒充当年数据**。
    某数据集在所有年份都无数据 → ``None``，由必需集检查照常给出 3001。
    """
    return {
        dataset: (
            int(year) if (year := _latest_year_with_presence(
                db, dataset, province_code, target_year, batch_code
            )) is not None else None
        )
        for dataset in DATASET_VALUES
    }


def _dataset_states_for_years(
    db: Session,
    province_code: str,
    years: Mapping[str, int | None],
    *,
    declared_year: int,
    batch_code: str,
    exam_type: str,
) -> dict[str, str]:
    """每个规则集的 ``data_status``（契约 8.1 四值），按各自的实际数据年度判定。

    优先读 ``rule_dataset_status``（契约 8.7：管理端与导入维护的唯一来源）；
    未登记时按"表里是否真的有该省该年的记录"推导，推导只产出 available / unavailable，
    不会凭猜测给出 partial。已声明 available 但表里没有记录 → 降级为 unavailable（不撒谎）。
    """
    candidate_years = sorted({y for y in years.values() if y} | {declared_year})
    declared = {
        (row.dataset, int(row.year)): row.status
        for row in db.scalars(
            select(RuleDatasetStatus).where(
                RuleDatasetStatus.province_code == province_code,
                RuleDatasetStatus.year.in_(candidate_years),
                RuleDatasetStatus.batch_code == batch_code,
                RuleDatasetStatus.exam_type == exam_type,
            )
        ).all()
    }
    states: dict[str, str] = {}
    for dataset in DATASET_VALUES:
        year = years.get(dataset)
        if year is None:
            states[dataset] = DATA_STATUS_UNAVAILABLE
            continue
        present = dataset_presence(db, dataset, province_code, int(year), batch_code)
        value = declared.get((dataset, int(year)))
        if value not in DATA_STATUS_VALUES:
            value = DATA_STATUS_AVAILABLE if present else DATA_STATUS_UNAVAILABLE
        elif value == DATA_STATUS_AVAILABLE and not present:
            value = DATA_STATUS_UNAVAILABLE
        states[dataset] = value
    return states


def _dataset_states(
    db: Session, province_code: str, year: int, batch_code: str, exam_type: str = EXAM_TYPE_NORMAL
) -> dict[str, str]:
    """**精确年份**的规则集状态（8.3 等按年查询接口沿用；不做跨年回退）。

    校验接口（8.4/8.6）请使用 ``_resolve_rule_years`` + ``_dataset_states_for_years``。
    """
    years = {dataset: year for dataset in DATASET_VALUES}
    return _dataset_states_for_years(
        db, province_code, years,
        declared_year=year, batch_code=batch_code, exam_type=exam_type,
    )


def _overall_status(states: Sequence[str]) -> str:
    """由若干规则集状态归并出接口级 ``data_status``。"""
    if not states:
        return DATA_STATUS_UNAVAILABLE
    unique = set(states)
    if unique == {DATA_STATUS_AVAILABLE}:
        return DATA_STATUS_AVAILABLE
    if unique <= {DATA_STATUS_UNAVAILABLE}:
        return DATA_STATUS_UNAVAILABLE
    return DATA_STATUS_PARTIAL


# --------------------------------------------------------------------------- #
# 8.3 GET /api/provinces/{code}/rules
# --------------------------------------------------------------------------- #
def province_rules(
    db: Session,
    code: str,
    year: int,
    batch: str = DEFAULT_BATCH,
    *,
    exam_type: str = EXAM_TYPE_NORMAL,
) -> dict[str, Any]:
    """读取省份志愿模式模板（契约 8.3）。

    入参 ``code`` 为两位省代码（``41`` / ``36``）；兼容历史入参的省名。
    无对应版本时**仍返回 200**，``data_status: unavailable``、``rule: null``。
    """
    province_code = province_code_of(code)
    province_name = province_name_of(province_code)
    batch_code = batch_code_of(batch)
    states = _dataset_states(db, province_code, year, batch_code, exam_type)

    row = db.scalars(
        select(ProvinceExamRule).where(
            ProvinceExamRule.province_code == province_code,
            ProvinceExamRule.year == year,
            ProvinceExamRule.batch_code == batch_code,
            ProvinceExamRule.exam_type == exam_type,
        )
    ).first()

    status = states[DATASET_PROVINCE_EXAM_RULE]
    if row is None:
        status = DATA_STATUS_UNAVAILABLE

    payload: dict[str, Any] = {
        "province_code": province_code,
        "province": row.province if row is not None else province_name,
        "year": year,
        "batch": row.batch if row is not None else batch,
        "batch_code": batch_code,
        "exam_type": exam_type,
        "data_status": status,
        "rule": None,
        "sources": [],
        "missing_rule_sets": [] if row is not None else [DATASET_PROVINCE_EXAM_RULE],
    }
    if row is None:
        return payload

    source = _sources_of(db, [row.source_id]).get(row.source_id)
    if source is not None:
        payload["sources"] = [_citation_of(source)]
    elif status == DATA_STATUS_AVAILABLE:
        # 有规则但来源缺失 → 不能宣称"齐全且有正式来源"
        payload["data_status"] = DATA_STATUS_PARTIAL
        status = DATA_STATUS_PARTIAL

    if status in (DATA_STATUS_AVAILABLE, DATA_STATUS_PARTIAL):
        payload["rule"] = {
            "mode": row.mode,
            "volunteer_count": row.volunteer_count,
            "majors_per_group": row.majors_per_group,
            "has_adjust": row.has_adjust,
            "admit_method": row.admit_method,
            "ratio": row.ratio,
            "tie_rule": row.tie_rule,
            "mutex_groups": _as_str_list(row.mutex_groups),
            "collect_count": row.collect_count,
        }
    return payload


# --------------------------------------------------------------------------- #
# 8.6 GET /api/majors/{id}/requirements
# --------------------------------------------------------------------------- #
def _enrollment_notes(
    db: Session, province_code: str, year: int | None, major_id: int
) -> tuple[dict[str, Any], bool]:
    """从 ``admission_requirement`` 组装契约 8.6 的 ``enrollment_notes``。

    返回 ``(notes, present)``；未知项一律 ``null``，绝不以空数组冒充"无限制"。
    ``year`` 为该数据集的实际数据年度（``None`` = 全部年份均无数据）。
    """
    notes: dict[str, Any] = {
        "single_subject_req": None,
        "language_req": None,
        "gender_req": None,
        "interview_required": None,
        "political_review_required": None,
        "physical_test_required": None,
    }
    if year is None:
        return notes, False
    rows = list(
        db.scalars(
            select(AdmissionRequirement).where(
                (AdmissionRequirement.province_code == province_code)
                | (AdmissionRequirement.province_code == ""),
                AdmissionRequirement.year == year,
                AdmissionRequirement.major_id == major_id,
            )
        ).all()
    )
    for row in rows:
        value = row.requirement_value
        if row.requirement_type == REQUIREMENT_TYPE_SINGLE_SUBJECT:
            notes["single_subject_req"] = value if isinstance(value, Mapping) else None
        elif row.requirement_type == REQUIREMENT_TYPE_LANGUAGE:
            if isinstance(value, Mapping):
                notes["language_req"] = {
                    "allowed_languages": [str(x) for x in (value.get("allowed_languages") or [])]
                }
            else:
                notes["language_req"] = {"allowed_languages": []}
        elif row.requirement_type == REQUIREMENT_TYPE_GENDER:
            notes["gender_req"] = str(value) if value not in (None, "") else None
        elif row.requirement_type == REQUIREMENT_TYPE_INTERVIEW:
            notes["interview_required"] = bool(value)
        elif row.requirement_type == REQUIREMENT_TYPE_POLITICAL_REVIEW:
            notes["political_review_required"] = bool(value)
        elif row.requirement_type == REQUIREMENT_TYPE_PHYSICAL_TEST:
            notes["physical_test_required"] = bool(value)
    return notes, bool(rows)


def _tuition_of(
    db: Session, province_code: str, year: int | None, major: Major
) -> tuple[dict[str, Any] | None, bool]:
    """专业学费（契约 8.6 ``tuition``）。

    优先读 ``major_tuition``（按省份/年份/院校/专业）；未入库时回退到 ``major.tuition``
    的演示值（仅界面演示用，``note`` 如实说明）。两者都没有 → ``None`` + 列入 missing。
    ``year`` 为该数据集的实际数据年度（``None`` = 全部年份均无数据，跳过查询）。
    """
    row = None
    if year is not None:
        row = db.scalars(
            select(MajorTuition).where(
                MajorTuition.province_code == province_code,
                MajorTuition.year == year,
                MajorTuition.major_id == major.id,
            )
        ).first()
    if row is not None:
        return (
            {
                "amount": row.amount,
                "currency": row.currency,
                "period": row.period,
                "ownership": row.ownership,
                "note": row.note,
            },
            True,
        )
    fallback = getattr(major, "tuition", None)
    if fallback is None:
        return None, False
    return (
        {
            "amount": fallback,
            "currency": "CNY",
            "period": "year",
            "ownership": str(getattr(major, "ownership", "") or ""),
            "note": "演示值，非官方收费标准；正式学费由数据工程按 major_tuition 入库",
        },
        False,
    )


def major_requirements(
    db: Session, major_id: int, province: str, year: int
) -> dict[str, Any]:
    """一次取全某专业的选科 / 身体条件 / 学费（契约 8.6；产品书 6.2.9）。

    与 8.4 不同：这是**只读**接口，规则缺失不返回 3001，而是如实标注
    ``data_status`` 与 ``missing_rule_sets``，未知项用 ``null``。

    各规则集按「不晚于请求年份的最近可得年度」取数，实际数据年度通过
    ``data_years`` 如实回传（契约 v1.6）。
    """
    province_code = province_code_of(province)
    major = db.get(Major, major_id)
    if major is None:
        raise BizError(f"参数错误：专业不存在：{major_id}")

    batch_code = batch_code_of(DEFAULT_BATCH)
    years = _resolve_rule_years(db, province_code, year, batch_code)
    states = _dataset_states_for_years(
        db, province_code, years,
        declared_year=year, batch_code=batch_code, exam_type=EXAM_TYPE_NORMAL,
    )
    missing: list[str] = []

    province_name = province_name_of(province_code)

    req_row = None
    if years[DATASET_SUBJECT_REQUIREMENT] is not None:
        req_row = db.scalars(
            select(SubjectRequirement).where(
                (SubjectRequirement.province_code == province_code)
                | (SubjectRequirement.province == province_name),
                SubjectRequirement.year == years[DATASET_SUBJECT_REQUIREMENT],
                SubjectRequirement.major_id == major_id,
            )
        ).first()

    subject_req: dict[str, Any] | None = None
    if req_row is None:
        missing.append(DATASET_SUBJECT_REQUIREMENT)
    else:
        first_subject = str(req_row.first_subject or "").strip()
        subject_req = {
            "first": first_subject if first_subject and first_subject != "不限" else None,
            "secondary": [str(x) for x in (req_row.secondary_subjects or [])],
            "logic": req_row.logic,
        }

    # 类级匹配走「专业代码前 4 位 → is_category 行 → 专业类名」，与 8.4 同一函数。
    class_name = _class_name_by_major(db, [major]).get(major.id)
    target_match = []
    if class_name:
        target_match.append(PhysicalRestriction.major_category == class_name)
    if str(major.category or "").strip():
        target_match.append(PhysicalRestriction.major_category == major.category)
    base_code = _code_base(major.code)
    if base_code:
        target_match.append(PhysicalRestriction.major_code.like(f"{base_code}%"))
    restrictions: list[PhysicalRestriction] = []
    if years[DATASET_PHYSICAL_RESTRICTION] is not None and target_match:
        restrictions = [
            row
            for row in db.scalars(
                select(PhysicalRestriction).where(
                    PhysicalRestriction.year == years[DATASET_PHYSICAL_RESTRICTION],
                    (PhysicalRestriction.province_code == province_code)
                    | (PhysicalRestriction.province == province_name)
                    | (PhysicalRestriction.province == "")
                    | (PhysicalRestriction.province_code == ""),
                    or_(*target_match),
                )
            ).all()
            if _rule_targets_major(row.major_code, row.major_category, major, class_name)
        ]
    if states[DATASET_PHYSICAL_RESTRICTION] != DATA_STATUS_AVAILABLE or not restrictions:
        missing.append(DATASET_PHYSICAL_RESTRICTION)

    notes, notes_present = _enrollment_notes(db, province_code, years[DATASET_ADMISSION_REQUIREMENT], major_id)
    if not notes_present:
        missing.append(DATASET_ADMISSION_REQUIREMENT)

    tuition, tuition_present = _tuition_of(db, province_code, years[DATASET_MAJOR_TUITION], major)
    if tuition is None or not tuition_present:
        missing.append(DATASET_MAJOR_TUITION)

    source_ids = [req_row.source_id] if req_row is not None else []
    source_ids += [row.source_id for row in restrictions]
    used = sorted({sid for sid in source_ids if sid})
    sources = _sources_of(db, used)

    data_status = _overall_status(
        [
            states[DATASET_SUBJECT_REQUIREMENT],
            states[DATASET_PHYSICAL_RESTRICTION],
            states[DATASET_ADMISSION_REQUIREMENT],
            states[DATASET_MAJOR_TUITION],
        ]
    )
    if subject_req is None and not restrictions:
        data_status = DATA_STATUS_UNAVAILABLE

    return {
        "major_id": major_id,
        "name": major.name,
        "province_code": province_code,
        "year": year,
        "data_status": data_status,
        "data_years": {dataset: years[dataset] for dataset in DATASET_VALUES},
        "subject_req": subject_req,
        "physical_restrictions": [
            {
                "condition": row.condition,
                "threshold": threshold_object(row.threshold),
                "level": row.level,
                "detail": row.detail,
                "major_category": row.major_category,
                "citation": _citation_of(sources.get(row.source_id)),
            }
            for row in restrictions
        ],
        "tuition": tuition,
        "enrollment_notes": notes,
        "sources": [_citation_of(sources.get(sid)) for sid in used],
        "missing_rule_sets": sorted(set(missing)),
    }


# --------------------------------------------------------------------------- #
# 8.4 / 8.5 POST /api/eligibility/check
# --------------------------------------------------------------------------- #
def _restrictions_for(
    db: Session,
    province_code: str,
    year: int,
    *,
    years: Mapping[str, int | None] | None = None,
) -> list[dict[str, Any]]:
    province_name = province_name_of(province_code)
    rows = list(
        db.scalars(
            select(PhysicalRestriction).where(
                PhysicalRestriction.year == year,
                (PhysicalRestriction.province_code == province_code)
                | (PhysicalRestriction.province == province_name)
                | (PhysicalRestriction.province == "")
                | (PhysicalRestriction.province_code == ""),
            )
        ).all()
    )
    if not rows:
        raise _rule_missing(
            f"{province_name}{year} 年的身体条件限制规则数据缺失（维护中），无法校验体检结论",
            data_status=DATA_STATUS_SCHEMA_ONLY,
            missing=[DATASET_PHYSICAL_RESTRICTION],
            years=years,
        )
    sources = _sources_of(db, [row.source_id for row in rows])
    return [
        {
            "condition": row.condition,
            "threshold": row.threshold,
            "level": row.level,
            "detail": row.detail,
            "major_category": row.major_category,
            "major_code": row.major_code,
            "major_ids": [],
            "major_names": [],
            "citation": _citation_of(sources.get(row.source_id)),
        }
        for row in rows
    ]


def _pick_group_variants(
    reqs: list[dict[str, Any]], first_subject: str
) -> list[dict[str, Any]]:
    """同组多口径（跨科类/跨批次）时，按考生首选科目选择适用变体。

    背景：河南招生计划按科类（历史类/物理类）独立编组号，同一「校+组号」在
    两个科类下是**不同专业组**（如 101@历史类 与 101@物理类），各自带首选
    科目要求入库。考生实际填报的组必然属于其首选科类，因此：

    - 考生首选已填 → 只保留与之一致的变体（``不限``/空视为通配）；若全部
      变体都要求相反首选（即该组号只属于另一科类）→ 全部保留，由引擎按
      "首选科目不符"如实拦截；
    - 考生首选未填 → 全部保留，引擎对每个变体给出「未填写首选科目」的
      unknown（不猜、不放行）。

    仅在存在多口径时生效；单行时原样返回。
    """
    if len(reqs) <= 1 or not str(first_subject or "").strip():
        return reqs
    candidate = str(first_subject).strip()
    matched = [
        req for req in reqs
        if str(req.get("first_subject") or "").strip() in ("", "不限", candidate)
    ]
    return matched or reqs


def _subject_requirements_by_unit(
    db: Session,
    items: Sequence[Mapping[str, Any]],
    province_code: str,
    year: int,
    *,
    first_subject: str = "",
    years: Mapping[str, int | None] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """按志愿单位组装选科要求；任一专业缺规则 → 3001（契约 8.4）。

    ``first_subject`` 为考生首选科目，用于同组多口径（跨科类）时的变体选择
    （见 ``_pick_group_variants``）；``years`` 仅用于 3001 时回传各规则集实际
    数据年度（``data_years``），便于定位缺的是哪一年的数据。
    """
    targets = [(item, item.get("major_ids") or []) for item in items]
    major_ids = sorted({mid for _, mids in targets for mid in mids})
    if not major_ids and not any(item.get("school_id") and item.get("group_code") for item, _ in targets):
        return {}

    province_name = province_name_of(province_code)
    rows = list(
        db.scalars(
            select(SubjectRequirement).where(
                (SubjectRequirement.province_code == province_code)
                | (SubjectRequirement.province == province_name),
                SubjectRequirement.year == year,
                (SubjectRequirement.major_id.in_(major_ids) if major_ids else SubjectRequirement.id < 0),
            )
        ).all()
    )
    group_rows: list[SubjectRequirement] = []
    for item, _ in targets:
        school_id, group_code = item.get("school_id"), str(item.get("group_code") or "").strip()
        if school_id and group_code:
            group_rows.extend(
                db.scalars(
                    select(SubjectRequirement).where(
                        SubjectRequirement.province_code == province_code,
                        SubjectRequirement.year == year,
                        SubjectRequirement.school_id == school_id,
                        SubjectRequirement.group_code == group_code,
                        SubjectRequirement.major_id.is_(None),
                    )
                ).all()
            )
    rows.extend(group_rows)
    # Remove duplicate DB rows while preserving deterministic ordering.
    rows = list({row.id: row for row in sorted(rows, key=lambda row: row.id)}.values())
    majors = {m.id: m for m in db.scalars(select(Major).where(Major.id.in_(major_ids))).all()} if major_ids else {}
    sources = _sources_of(db, [row.source_id for row in rows])

    by_major: dict[int, list[dict[str, Any]]] = {}
    by_group: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for row in rows:
        entry = {
                "first_subject": row.first_subject,
                "secondary_subjects": list(row.secondary_subjects or []),
                "logic": row.logic,
                "batch_code": batch_code_of(row.batch) if str(row.batch or "").strip() else "",
                "major_ids": [row.major_id] if row.major_id is not None else [],
                "major_names": [majors[row.major_id].name] if row.major_id in majors else [],
                "citation": _citation_of(sources.get(row.source_id)),
            }
        if row.major_id is not None:
            by_major.setdefault(row.major_id, []).append(entry)
        elif row.school_id and row.group_code:
            by_group.setdefault((row.school_id, row.group_code), []).append(entry)

    result: dict[str, list[dict[str, Any]]] = {}
    missing_targets: list[str] = []
    for item in items:
        unit_id = str(item.get("unit_id") or "")
        mids = item.get("major_ids") or []
        target_batch = batch_code_of(str(item.get("batch") or DEFAULT_BATCH))
        group_key = (item.get("school_id"), str(item.get("group_code") or "").strip())
        group_reqs = [
            req for req in by_group.get(group_key, [])
            if not req["batch_code"] or req["batch_code"] == target_batch
        ] if all(group_key) else []
        group_reqs = _pick_group_variants(group_reqs, first_subject)
        reqs: list[dict[str, Any]] = []
        group_fallback_ids: list[int] = []
        for mid in mids:
            major_reqs = [
                req for req in by_major.get(mid, [])
                if not req["batch_code"] or req["batch_code"] == target_batch
            ]
            if major_reqs:
                reqs.extend(major_reqs)
            elif group_reqs:
                group_fallback_ids.append(mid)
            else:
                major = majors.get(mid)
                missing_targets.append(f"unit_id={unit_id}, major_id={mid}（{major.name if major else '专业未知'}）")
        if group_fallback_ids:
            for group_req in group_reqs:
                copy = dict(group_req)
                copy["major_ids"] = list(group_fallback_ids)
                copy["major_names"] = [majors[mid].name for mid in group_fallback_ids if mid in majors]
                reqs.append(copy)
        if not mids and group_reqs:
            reqs.extend(group_reqs)
        elif not mids and item.get("group_code"):
            missing_targets.append(f"unit_id={unit_id}, school_id={item.get('school_id')}, group_code={item.get('group_code')}")
        # Group requirements describe the whole target group, so attach the requested majors for traceability.
        normalized = []
        for req in reqs:
            copy = dict(req)
            normalized.append(copy)
        result[unit_id] = normalized
    if missing_targets:
        summary = "; ".join(missing_targets[:20])
        if len(missing_targets) > 20:
            summary += f"；另有 {len(missing_targets) - 20} 个目标"
        raise _rule_missing(
            f"以下目标在 {province_name}{year} 年缺少明确选科规则：{summary}",
            data_status=DATA_STATUS_SCHEMA_ONLY,
            missing=[DATASET_SUBJECT_REQUIREMENT],
            years=years,
        )
    return result


def _targeted_restrictions(
    db: Session,
    restrictions: Sequence[Mapping[str, Any]],
    items: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Attach stable target identities to physical rules; unknown category stays explicit."""
    major_ids = sorted({mid for item in items for mid in (item.get("major_ids") or [])})
    majors = {
        major.id: major
        for major in db.scalars(select(Major).where(Major.id.in_(major_ids))).all()
    } if major_ids else {}
    # 专业 → 专业类名（code 前 4 位 → is_category 行），类级体检规则的匹配链
    class_by_major = _class_name_by_major(db, list(majors.values()))
    output: list[dict[str, Any]] = []
    for raw in restrictions:
        rule = dict(raw)
        category = str(rule.get("major_category") or "").strip()
        code = str(rule.get("major_code") or "").strip()
        if not category and not code:
            condition_text = str(rule.get("condition") or "")
            if majors and ("军队院校" in condition_text or "公安院校" in condition_text):
                rule["major_ids"] = list(majors)
                rule["major_names"] = [major.name for major in majors.values()]
                output.append(rule)
                continue
            if majors:
                output.append({
                    "condition": "专业适用范围未知",
                    "threshold": "",
                    "level": "reject",
                    "detail": "体检规则未关联专业代码或专业类，无法确认是否适用于目标专业",
                    "major_ids": list(majors),
                    "major_names": [major.name for major in majors.values()],
                    "citation": rule.get("citation") or {"source_name": "", "source_url": "", "year": 0},
                })
            continue
        matched = [
            major for major in majors.values()
            if _rule_targets_major(code, category, major, class_by_major.get(major.id))
        ]
        if not matched:
            continue
        rule["major_ids"] = [major.id for major in matched]
        rule["major_names"] = [major.name for major in matched]
        output.append(rule)
    for mid, major in majors.items():
        if not str(major.category or "").strip() and not str(major.code or "").strip():
            output.append({
                "condition": "专业适用范围未知",
                "threshold": "",
                "level": "reject",
                "detail": "目标专业缺少专业代码和专业类映射，无法确认体检规则适用范围",
                "major_ids": [mid],
                "major_names": [major.name],
                "citation": {"source_name": "", "source_url": "", "year": 0},
            })
    for item in items:
        if not item.get("major_ids"):
            output.append({
                "condition": "专业适用范围未知",
                "threshold": "",
                "level": "reject",
                "detail": "志愿单位未提供专业目标，无法确认适用的体检限制",
                "major_ids": [],
                "major_names": [],
                "scope_unit_ids": [str(item.get("unit_id") or "")],
                "citation": {"source_name": "", "source_url": "", "year": 0},
            })
    return output


def _tuition_by_unit(
    db: Session, items: Sequence[Mapping[str, Any]], province_code: str, year: int | None
) -> dict[str, dict[str, Any]]:
    """按志愿单位组装学费（闸门 4）。

    优先 ``major_tuition``（含来源引用），回退 ``major.tuition`` 演示值。
    两者都没有 → 该单位不产出学费条目，引擎据此记 ``unknown``（绝不静默放行）。
    ``year`` 为该数据集的实际数据年度（``None`` = 全部年份均无数据）。
    """
    major_ids = sorted({mid for item in items for mid in (item.get("major_ids") or [])})
    if not major_ids:
        return {}
    majors = {m.id: m for m in db.scalars(select(Major).where(Major.id.in_(major_ids))).all()}

    rows = []
    if year is not None:
        rows = list(
            db.scalars(
                select(MajorTuition).where(
                    (MajorTuition.province_code == province_code) | (MajorTuition.province_code == ""),
                    MajorTuition.year == year,
                    MajorTuition.major_id.in_(major_ids),
                )
            ).all()
        )
    sources = _sources_of(db, [row.source_id for row in rows])
    tuition_by_major: dict[int, dict[str, Any]] = {}
    for row in rows:
        if row.major_id is None or row.amount is None:
            continue
        tuition_by_major[row.major_id] = {
            "amount": row.amount,
            "ownership": row.ownership,
            "note": row.note,
            "citation": _citation_of(sources.get(row.source_id)),
        }

    out: dict[str, dict[str, Any]] = {}
    for item in items:
        candidates: list[tuple[float, dict[str, Any]]] = []
        for mid in item.get("major_ids") or []:
            entry = tuition_by_major.get(mid)
            if entry is None:
                major = majors.get(mid)
                fallback = getattr(major, "tuition", None) if major is not None else None
                if fallback is None:
                    continue
                entry = {
                    "amount": fallback,
                    "ownership": str(getattr(major, "ownership", "") or ""),
                    "note": "演示值，非官方收费标准",
                }
            candidates.append((float(entry["amount"]), entry))
        if not candidates:
            continue
        # 取该志愿单位内最贵的专业作为代表（最保守：先暴露预算风险）
        _, top = max(candidates, key=lambda pair: pair[0])
        out[item.get("unit_id")] = top
    return out


def check_eligibility(
    db: Session, payload: Any, *, user: Any = None
) -> dict[str, Any]:
    """志愿单位批量资格校验（契约 8.4 游客 / 8.5 登录）。

    登录时额外返回 ``updated_profile``（写回 ``accept_adjustment`` 等显式提供的字段）。
    """
    profile = payload.profile
    province_code = province_code_of(getattr(profile, "province", "") or "")
    year = int(getattr(profile, "year", 0) or 0) or resolve_year(db, province_code)
    exam_type = str(getattr(profile, "exam_type", EXAM_TYPE_NORMAL) or EXAM_TYPE_NORMAL)
    items = [item.model_dump() for item in (payload.items or [])]
    batch_code = batch_code_of(DEFAULT_BATCH)

    # 各规则集按「不晚于报考年份的最近可得年度」取数（数据发布节奏不同：
    # 省份模板/体检规则按年发布，选科要求常滞后一年），实际年度如实回传
    # data_years，绝不静默用旧数据冒充当年数据。
    years = _resolve_rule_years(db, province_code, year, batch_code)
    states = _dataset_states_for_years(
        db, province_code, years,
        declared_year=year, batch_code=batch_code, exam_type=exam_type,
    )
    missing_required = [ds for ds in REQUIRED_DATASETS if states[ds] != DATA_STATUS_AVAILABLE]

    # 闸门 1：省份模板必须存在（契约 8.4：执行校验所必需的规则集缺失 → 3001）
    rule_year = years[DATASET_PROVINCE_EXAM_RULE]
    rule_row = None
    if rule_year is not None:
        rule_row = db.scalars(
            select(ProvinceExamRule).where(
                ProvinceExamRule.province_code == province_code,
                ProvinceExamRule.year == rule_year,
                ProvinceExamRule.batch_code == batch_code,
                ProvinceExamRule.exam_type == exam_type,
            )
        ).first()
    if rule_row is None:
        province_name = province_name_of(province_code)
        raise _rule_missing(
            f"{province_name}{year} 年的报考规则数据缺失（维护中），暂无法校验，请稍后再试",
            data_status=states.get(DATASET_PROVINCE_EXAM_RULE, DATA_STATUS_UNAVAILABLE),
            missing=missing_required or [DATASET_PROVINCE_EXAM_RULE],
            years=years,
        )

    if missing_required:
        labels = ", ".join(missing_required)
        raise _rule_missing(
            f"{province_name_of(province_code)}{year} 年以下必需规则集尚未达到可用状态：{labels}",
            data_status=_overall_status([states[ds] for ds in REQUIRED_DATASETS]),
            missing=missing_required,
            years=years,
        )

    # 必需集全部可用 → 三个必需数据集的年度必非空（state=available 蕴含表里有行）。
    subject_year = int(years[DATASET_SUBJECT_REQUIREMENT])  # type: ignore[arg-type]
    physical_year = int(years[DATASET_PHYSICAL_RESTRICTION])  # type: ignore[arg-type]

    source = _sources_of(db, [rule_row.source_id]).get(rule_row.source_id)
    province_rule = {
        "batch": rule_row.batch,
        "mutex_groups": _as_str_list(rule_row.mutex_groups),
        "citation": _citation_of(source),
    }

    rules = {
        "province_rule": province_rule,
        "subject_requirements": _subject_requirements_by_unit(
            db, items, province_code, subject_year,
            first_subject=str(getattr(profile, "first_subject", "") or ""),
            years=years,
        ),
        "physical_restrictions": _targeted_restrictions(
            db, _restrictions_for(db, province_code, physical_year, years=years), items
        ),
        "tuition": _tuition_by_unit(db, items, province_code, years[DATASET_MAJOR_TUITION]),
        "pathway_id": getattr(payload, "pathway_id", None),
    }

    result = engine.check_units(profile, items, rules)

    # 8.4：出参首字段是 data_status。必需集齐全时，看可选集是否也齐全；
    # 必需集用到滞后年度（如 2026 报考用 2025 选科要求）同样降级 partial——
    # "数据齐全"与"数据正好是当年"是两回事，如实标注（data_years 给出年度）。
    fallback_used = any(
        years[ds] is not None and int(years[ds]) != year for ds in REQUIRED_DATASETS
    )
    optional_states = [states[ds] for ds in OPTIONAL_DATASETS]
    partial = fallback_used or any(state != DATA_STATUS_AVAILABLE for state in optional_states)
    result = {
        "data_status": DATA_STATUS_PARTIAL if partial else DATA_STATUS_AVAILABLE,
        "data_years": {dataset: years[dataset] for dataset in DATASET_VALUES},
        **result,
    }

    if user is not None:
        updated = profile_service.save_from_constraint_profile(db, user.id, profile)
        result["updated_profile"] = updated
    return result


def resolve_year(db: Session, province: str) -> int:
    """未指定年份时取该省最新已有规则的年份；无数据则取当前年份。"""
    province_code = province_code_of(province)
    row = db.scalars(
        select(ProvinceExamRule.year)
        .where(ProvinceExamRule.province_code == province_code)
        .order_by(ProvinceExamRule.year.desc())
    ).first()
    if row:
        return int(row)
    return datetime.now().year
