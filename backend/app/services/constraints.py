"""报考约束业务层（产品书 6.2.6–6.2.9；8.5 四道闸门的数据与编排）。

本层只做两件事：**从规则表读数据**（IO）+ **调用纯函数引擎**（app/engine/constraints.py）。
判定逻辑一律在引擎里，服务层不做二次改判，避免"双份真相"（8.5 风险清单）。

规则数据缺失 → 返回 ``3001``，**绝不静默放行**（8.5 实现纪律第 3 条、7.6 约束第 5 条）：

- 省份模板缺失 → 3001
- 志愿单位内某专业的选科要求缺失 → 3001
- 身体条件规则表在该省该年为空 → 3001

``null``（未填）只进 ``unknowns``，不判合格（6.1.4 注）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.response import BizCode, BizError
from app.engine import constraints as engine
from app.models.base_data import Major
from app.models.constraints import (
    PhysicalRestriction,
    ProvinceExamRule,
    SubjectRequirement,
)
from app.models.source import Source
from app.services import profile as profile_service

DEFAULT_BATCH = "本科批"


def _citation_of(source: Source | None) -> dict[str, Any]:
    if source is None:
        return {"source_name": "", "source_url": "", "year": 0}
    return {
        "source_name": source.source_name,
        "source_url": source.source_url,
        "year": source.year,
    }


def _sources_of(db: Session, source_ids: Sequence[int]) -> dict[int, Source]:
    ids = sorted({sid for sid in source_ids if sid})
    if not ids:
        return {}
    rows = db.scalars(select(Source).where(Source.id.in_(ids))).all()
    return {row.id: row for row in rows}


def _rule_missing(message: str) -> BizError:
    return BizError(message, BizCode.RULE_MISSING)


# --------------------------------------------------------------------------- #
# 6.2.6 GET /api/provinces/{code}/rules
# --------------------------------------------------------------------------- #
def province_rules(
    db: Session, province: str, year: int, batch: str = DEFAULT_BATCH
) -> dict[str, Any]:
    """读取省份志愿模式模板（6.2.6）。无记录 → 3001。"""
    row = db.scalars(
        select(ProvinceExamRule).where(
            ProvinceExamRule.province == province,
            ProvinceExamRule.year == year,
            ProvinceExamRule.batch == batch,
        )
    ).first()
    if row is None:
        raise _rule_missing(
            f"{province}{year} 年「{batch}」志愿模式规则数据缺失（维护中），"
            "请稍后再试或联系管理员"
        )
    source = _sources_of(db, [row.source_id]).get(row.source_id)
    return {
        "province": row.province,
        "year": row.year,
        "batch": row.batch,
        "mode": row.mode,
        "volunteer_count": row.volunteer_count,
        "majors_per_group": row.majors_per_group,
        "has_adjust": row.has_adjust,
        "admit_method": row.admit_method,
        "ratio": row.ratio,
        "tie_rule": row.tie_rule,
        "mutex_groups": list(row.mutex_groups or []),
        "collect_count": row.collect_count,
        "sources": [_citation_of(source)],
    }


# --------------------------------------------------------------------------- #
# 6.2.9 GET /api/majors/{id}/requirements
# --------------------------------------------------------------------------- #
def major_requirements(
    db: Session, major_id: int, province: str, year: int
) -> dict[str, Any]:
    """一次取全某专业的选科 / 身体条件 / 学费（6.2.9）。缺规则 → 3001。"""
    major = db.get(Major, major_id)
    if major is None:
        raise BizError(f"参数错误：专业不存在：{major_id}")

    req_row = db.scalars(
        select(SubjectRequirement).where(
            SubjectRequirement.province == province,
            SubjectRequirement.year == year,
            SubjectRequirement.major_id == major_id,
        )
    ).first()
    if req_row is None:
        raise _rule_missing(
            f"专业「{major.name}」在 {province}{year} 年的选科要求数据缺失（维护中）"
        )

    restrictions = list(
        db.scalars(
            select(PhysicalRestriction).where(
                PhysicalRestriction.year == year,
                (PhysicalRestriction.province == province)
                | (PhysicalRestriction.province == ""),
                (PhysicalRestriction.major_category == (major.category or ""))
                | (PhysicalRestriction.major_code == (major.code or ""))
                | (PhysicalRestriction.major_category == ""),
            )
        ).all()
    )

    sources = _sources_of(
        db, [req_row.source_id] + [r.source_id for r in restrictions]
    )
    return {
        "major_id": major_id,
        "name": major.name,
        "subject_req": {
            "first": req_row.first_subject,
            "secondary": list(req_row.secondary_subjects or []),
            "logic": req_row.logic,
            "citation": _citation_of(sources.get(req_row.source_id)),
        },
        "physical_restrictions": [
            {
                "condition": r.condition,
                "threshold": r.threshold,
                "level": r.level,
                "detail": r.detail,
                "major_category": r.major_category,
                "citation": _citation_of(sources.get(r.source_id)),
            }
            for r in restrictions
        ],
        "tuition": {
            "amount": getattr(major, "tuition", None),
            "ownership": getattr(major, "ownership", ""),
            "note": "按办学性质分档，具体以当年招生计划为准",
        },
        "enrollment_notes": {
            "single_subject_req": getattr(major, "single_subject_req", ""),
            "language_req": getattr(major, "language_req", ""),
            "gender_req": getattr(major, "gender_req", ""),
            "interview_required": getattr(major, "interview_required", False),
        },
        "sources": [_citation_of(sources.get(sid)) for sid in sorted({req_row.source_id} | {r.source_id for r in restrictions})],
    }


# --------------------------------------------------------------------------- #
# 6.2.7 / 6.2.8 POST /api/eligibility/check
# --------------------------------------------------------------------------- #
def _restrictions_for(db: Session, province: str, year: int) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(PhysicalRestriction).where(
                PhysicalRestriction.year == year,
                (PhysicalRestriction.province == province) | (PhysicalRestriction.province == ""),
            )
        ).all()
    )
    if not rows:
        raise _rule_missing(
            f"{province}{year} 年的身体条件限制规则数据缺失（维护中），无法校验体检结论"
        )
    sources = _sources_of(db, [r.source_id for r in rows])
    return [
        {
            "condition": r.condition,
            "threshold": r.threshold,
            "level": r.level,
            "detail": r.detail,
            "major_category": r.major_category,
            "major_code": r.major_code,
            "citation": _citation_of(sources.get(r.source_id)),
        }
        for r in rows
    ]


def _subject_requirements_by_unit(
    db: Session, items: Sequence[Mapping[str, Any]], province: str, year: int
) -> dict[str, list[dict[str, Any]]]:
    """按志愿单位组装选科要求；任一专业缺规则 → 3001。"""
    major_ids = sorted({mid for item in items for mid in (item.get("major_ids") or [])})
    if not major_ids:
        return {}

    rows = list(
        db.scalars(
            select(SubjectRequirement).where(
                SubjectRequirement.province == province,
                SubjectRequirement.year == year,
                SubjectRequirement.major_id.in_(major_ids),
            )
        ).all()
    )
    have = {row.major_id for row in rows if row.major_id is not None}
    missing = [mid for mid in major_ids if mid not in have]
    if missing:
        names = list(
            db.scalars(select(Major.name).where(Major.id.in_(missing))).all()
        )
        label = "、".join(names) if names else "、".join(str(x) for x in missing)
        raise _rule_missing(
            f"以下专业在 {province}{year} 年的选科要求数据缺失（维护中）：{label}"
        )

    majors = {m.id: m for m in db.scalars(select(Major).where(Major.id.in_(major_ids))).all()}
    sources = _sources_of(db, [r.source_id for r in rows])

    by_major: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        if row.major_id is None:
            continue
        by_major.setdefault(row.major_id, []).append(
            {
                "first_subject": row.first_subject,
                "secondary_subjects": list(row.secondary_subjects or []),
                "logic": row.logic,
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
    db: Session, items: Sequence[Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    major_ids = sorted({mid for item in items for mid in (item.get("major_ids") or [])})
    if not major_ids:
        return {}
    majors = {m.id: m for m in db.scalars(select(Major).where(Major.id.in_(major_ids))).all()}
    out: dict[str, dict[str, Any]] = {}
    for item in items:
        amounts = [
            getattr(majors[mid], "tuition", None)
            for mid in (item.get("major_ids") or [])
            if mid in majors and getattr(majors[mid], "tuition", None) is not None
        ]
        if not amounts:
            continue
        top = max(amounts)
        representative = next(
            (majors[mid] for mid in (item.get("major_ids") or []) if mid in majors and getattr(majors[mid], "tuition", None) == top),
            None,
        )
        out[item.get("unit_id")] = {
            "amount": top,
            "ownership": getattr(representative, "ownership", ""),
            "note": "",
        }
    return out


def check_eligibility(
    db: Session, payload: Any, *, user: Any = None
) -> dict[str, Any]:
    """志愿单位批量资格校验（6.2.7 游客 / 6.2.8 登录）。

    登录时额外返回 ``updated_profile``（写回 ``accept_adjustment`` 等显式提供的字段）。
    """
    profile = payload.profile
    province = str(getattr(profile, "province", "") or "河南")
    year = int(getattr(profile, "year", 0) or 0) or resolve_year(db, province)
    items = [item.model_dump() for item in (payload.items or [])]

    # 闸门 1：省份模板必须存在
    rule_row = db.scalars(
        select(ProvinceExamRule).where(
            ProvinceExamRule.province == province,
            ProvinceExamRule.year == year,
            ProvinceExamRule.batch == DEFAULT_BATCH,
        )
    ).first()
    if rule_row is None:
        raise _rule_missing(
            f"{province}{year} 年的报考规则数据缺失（维护中），暂无法校验，请稍后再试"
        )
    source = _sources_of(db, [rule_row.source_id]).get(rule_row.source_id)
    province_rule = {
        "batch": rule_row.batch,
        "mutex_groups": list(rule_row.mutex_groups or []),
        "citation": _citation_of(source),
    }

    rules = {
        "province_rule": province_rule,
        "subject_requirements": _subject_requirements_by_unit(db, items, province, year),
        "physical_restrictions": _restrictions_for(db, province, year),
        "tuition": _tuition_by_unit(db, items),
    }

    result = engine.check_units(profile, items, rules)

    if user is not None:
        updated = profile_service.save_from_constraint_profile(db, user.id, profile)
        result["updated_profile"] = updated
    return result


def resolve_year(db: Session, province: str) -> int:
    """未指定年份时取该省最新已有规则的年份；无数据则取当前年份。"""
    row = db.scalars(
        select(ProvinceExamRule.year)
        .where(ProvinceExamRule.province == province)
        .order_by(ProvinceExamRule.year.desc())
    ).first()
    if row:
        return int(row)
    return datetime.now().year
