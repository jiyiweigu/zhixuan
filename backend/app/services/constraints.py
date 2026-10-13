"""报考约束业务层（产品书 6.2.6–6.2.9；8.5 四道闸门的数据与编排）。

本层只做两件事：**从规则表读数据**（IO）+ **调用纯函数引擎**（app/engine/constraints.py）。
判定逻辑一律在引擎里，服务层不做二次改判，避免"双份真相"（8.5 风险清单）。

契约对齐（docs/api-contract.md v1.3）：

- 8.3 ``GET /api/provinces/{code}/rules``：入参是**两位省代码**（河南 ``41`` / 江西 ``36``），
  出参含 ``province_code`` / ``batch_code`` / ``exam_type`` / ``data_status`` / 嵌套 ``rule`` /
  ``sources`` / ``missing_rule_sets``；**无对应版本仍返回 200 + ``unavailable``**，不返回虚构模板；
- 8.6 ``GET /api/majors/{id}/requirements``：``threshold`` 为对象、``tuition`` 完整、
  缺失规则集列入 ``missing_rule_sets``、未知要求用 ``null`` 而不是空数组冒充"无限制"；
- 8.4 ``POST /api/eligibility/check``：出参首字段为 ``data_status``。

规则数据缺失 → **校验接口**返回 ``3001``，绝不静默放行（8.5 实现纪律第 3 条、7.6 约束第 5 条）：

- 执行校验所必需的规则集（省份模板 / 选科 / 身体条件）任一缺失 → 3001
- 可选规则集（学费 / 章程要求）缺失 → 降级为 ``partial``，相关闸门进 ``unknowns``

``null``（未填）只进 ``unknowns``，不判合格（8.1）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from sqlalchemy import func, select
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


def _rule_missing(message: str, *, data_status: str, missing: Sequence[str]) -> BizError:
    """构造 3001：``data`` 说明缺失数据集（契约 8.4 错误示例）。"""
    return BizError(
        message,
        BizCode.RULE_MISSING,
        data={"data_status": data_status, "missing_rule_sets": sorted(set(missing))},
    )


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


def _dataset_states(
    db: Session, province_code: str, year: int, batch_code: str, exam_type: str = EXAM_TYPE_NORMAL
) -> dict[str, str]:
    """每个规则集的 ``data_status``（契约 8.1 四值）。

    优先读 ``rule_dataset_status``（契约 8.7：管理端与导入维护的唯一来源）；
    未登记时按"表里是否真的有该省该年的记录"推导，推导只产出 available / unavailable，
    不会凭猜测给出 partial。已声明 available 但表里没有记录 → 降级为 unavailable（不撒谎）。
    """
    declared = {
        row.dataset: row.status
        for row in db.scalars(
            select(RuleDatasetStatus).where(
                RuleDatasetStatus.province_code == province_code,
                RuleDatasetStatus.year == year,
                RuleDatasetStatus.batch_code == batch_code,
                RuleDatasetStatus.exam_type == exam_type,
            )
        ).all()
    }
    states: dict[str, str] = {}
    for dataset in DATASET_VALUES:
        present = dataset_presence(db, dataset, province_code, year, batch_code)
        value = declared.get(dataset)
        if value not in DATA_STATUS_VALUES:
            value = DATA_STATUS_AVAILABLE if present else DATA_STATUS_UNAVAILABLE
        elif value == DATA_STATUS_AVAILABLE and not present:
            value = DATA_STATUS_UNAVAILABLE
        states[dataset] = value
    return states


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
    db: Session, province_code: str, year: int, major_id: int
) -> tuple[dict[str, Any], bool]:
    """从 ``admission_requirement`` 组装契约 8.6 的 ``enrollment_notes``。

    返回 ``(notes, present)``；未知项一律 ``null``，绝不以空数组冒充"无限制"。
    """
    notes: dict[str, Any] = {
        "single_subject_req": None,
        "language_req": None,
        "gender_req": None,
        "interview_required": None,
        "political_review_required": None,
        "physical_test_required": None,
    }
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
    db: Session, province_code: str, year: int, major: Major
) -> tuple[dict[str, Any] | None, bool]:
    """专业学费（契约 8.6 ``tuition``）。

    优先读 ``major_tuition``（按省份/年份/院校/专业）；未入库时回退到 ``major.tuition``
    的演示值（仅界面演示用，``note`` 如实说明）。两者都没有 → ``None`` + 列入 missing。
    """
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
    """
    province_code = province_code_of(province)
    major = db.get(Major, major_id)
    if major is None:
        raise BizError(f"参数错误：专业不存在：{major_id}")

    batch_code = batch_code_of(DEFAULT_BATCH)
    states = _dataset_states(db, province_code, year, batch_code)
    missing: list[str] = []

    province_name = province_name_of(province_code)

    req_row = db.scalars(
        select(SubjectRequirement).where(
            (SubjectRequirement.province_code == province_code)
            | (SubjectRequirement.province == province_name),
            SubjectRequirement.year == year,
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

    restrictions = list(
        db.scalars(
            select(PhysicalRestriction).where(
                PhysicalRestriction.year == year,
                (PhysicalRestriction.province_code == province_code)
                | (PhysicalRestriction.province == province_name)
                | (PhysicalRestriction.province == "")
                | (PhysicalRestriction.province_code == ""),
                (PhysicalRestriction.major_category == (major.category or ""))
                | (PhysicalRestriction.major_code == (major.code or ""))
                | (PhysicalRestriction.major_category == ""),
            )
        ).all()
    )
    if states[DATASET_PHYSICAL_RESTRICTION] != DATA_STATUS_AVAILABLE or not restrictions:
        missing.append(DATASET_PHYSICAL_RESTRICTION)

    notes, notes_present = _enrollment_notes(db, province_code, year, major_id)
    if not notes_present:
        missing.append(DATASET_ADMISSION_REQUIREMENT)

    tuition, tuition_present = _tuition_of(db, province_code, year, major)
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
def _restrictions_for(db: Session, province_code: str, year: int) -> list[dict[str, Any]]:
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
            "citation": _citation_of(sources.get(row.source_id)),
        }
        for row in rows
    ]


def _subject_requirements_by_unit(
    db: Session, items: Sequence[Mapping[str, Any]], province_code: str, year: int
) -> dict[str, list[dict[str, Any]]]:
    """按志愿单位组装选科要求；任一专业缺规则 → 3001（契约 8.4）。"""
    major_ids = sorted({mid for item in items for mid in (item.get("major_ids") or [])})
    if not major_ids:
        return {}

    province_name = province_name_of(province_code)
    rows = list(
        db.scalars(
            select(SubjectRequirement).where(
                (SubjectRequirement.province_code == province_code)
                | (SubjectRequirement.province == province_name),
                SubjectRequirement.year == year,
                SubjectRequirement.major_id.in_(major_ids),
            )
        ).all()
    )
    have = {row.major_id for row in rows if row.major_id is not None}
    missing = [mid for mid in major_ids if mid not in have]
    if missing:
        names = list(db.scalars(select(Major.name).where(Major.id.in_(missing))).all())
        label = "、".join(names) if names else "、".join(str(x) for x in missing)
        raise _rule_missing(
            f"以下专业在 {province_name}{year} 年的选科要求数据缺失（维护中）：{label}",
            data_status=DATA_STATUS_SCHEMA_ONLY,
            missing=[DATASET_SUBJECT_REQUIREMENT],
        )

    majors = {m.id: m for m in db.scalars(select(Major).where(Major.id.in_(major_ids))).all()}
    sources = _sources_of(db, [row.source_id for row in rows])

    by_major: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        if row.major_id is None:
            continue
        by_major.setdefault(row.major_id, []).append(
            {
                "first_subject": row.first_subject,
                "secondary_subjects": list(row.secondary_subjects or []),
                "logic": row.logic,
                "major_ids": [row.major_id],
                "major_names": [majors[row.major_id].name] if row.major_id in majors else [],
                "citation": _citation_of(sources.get(row.source_id)),
            }
        )

    result: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        unit_id = item.get("unit_id")
        reqs: list[dict[str, Any]] = []
        for mid in item.get("major_ids") or []:
            reqs.extend(by_major.get(mid, []))
        result[unit_id] = reqs
    return result


def _tuition_by_unit(
    db: Session, items: Sequence[Mapping[str, Any]], province_code: str, year: int
) -> dict[str, dict[str, Any]]:
    """按志愿单位组装学费（闸门 4）。

    优先 ``major_tuition``（含来源引用），回退 ``major.tuition`` 演示值。
    两者都没有 → 该单位不产出学费条目，引擎据此记 ``unknown``（绝不静默放行）。
    """
    major_ids = sorted({mid for item in items for mid in (item.get("major_ids") or [])})
    if not major_ids:
        return {}
    majors = {m.id: m for m in db.scalars(select(Major).where(Major.id.in_(major_ids))).all()}

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

    states = _dataset_states(db, province_code, year, batch_code, exam_type)
    missing_required = [ds for ds in REQUIRED_DATASETS if states[ds] != DATA_STATUS_AVAILABLE]

    # 闸门 1：省份模板必须存在（契约 8.4：执行校验所必需的规则集缺失 → 3001）
    rule_row = db.scalars(
        select(ProvinceExamRule).where(
            ProvinceExamRule.province_code == province_code,
            ProvinceExamRule.year == year,
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
        )

    source = _sources_of(db, [rule_row.source_id]).get(rule_row.source_id)
    province_rule = {
        "batch": rule_row.batch,
        "mutex_groups": _as_str_list(rule_row.mutex_groups),
        "citation": _citation_of(source),
    }

    rules = {
        "province_rule": province_rule,
        "subject_requirements": _subject_requirements_by_unit(db, items, province_code, year),
        "physical_restrictions": _restrictions_for(db, province_code, year),
        "tuition": _tuition_by_unit(db, items, province_code, year),
    }

    result = engine.check_units(profile, items, rules)

    # 8.4：出参首字段是 data_status。必需集齐全时，看可选集是否也齐全。
    optional_states = [states[ds] for ds in OPTIONAL_DATASETS]
    partial = any(state != DATA_STATUS_AVAILABLE for state in optional_states)
    result = {
        "data_status": DATA_STATUS_PARTIAL if partial else DATA_STATUS_AVAILABLE,
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
