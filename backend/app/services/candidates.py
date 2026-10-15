"""志愿方案候选数据源：真实库（``school_major_score`` × ``school``）（tasks.md 6.3）。

``app/services/plans.py`` 的分档 / 排序 / 风险逻辑本身不依赖数据来源，
只要候选是「一所院校一条、带 min_score 与来源三要素」即可。
本模块负责把库内录取分整理成这个形状，替代 ``app/data/plans/candidates_demo.json``。

口径约束（与数据侧红线一致，宁可缺不可猜）
------------------------------------------
1. **只取普通本科批**：``batch_code_of(batch) == undergraduate_regular``。
   库内 2022 / 2024 的「本一 / 本二 / 本科 / 本科一批」尚未按契约 8.3 归一为
   ``batch_code``，为避免跨批次混合（批次线不同、投档序列不同），一律**不纳入**
   候选并如实上报原因，等数据侧收敛后再开放。
2. **不跨考试制度**：``subject_type`` 必须精确匹配（物理类 / 历史类 / 理科 / 文科）。
   2024 两省 ``subject_type`` 整列为空，故 2024 年不作为任何科类的候选。
3. **分档用院校最低录取分**（投档线口径）：同校同年同批次同科类取
   ``min(min_score)``，并记录取到该分数的专业名与位次，供依据说明使用。
4. **来源三要素缺一不入候选**：解析不到 ``source_name`` / ``source_url`` / ``year``
   的行跳过并计数，绝不静默写入。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base_data import School, SchoolMajorScore
from app.models.constants import BATCH_CODE_UG, batch_code_of
from app.models.source import Source

CANDIDATE_LIMIT_DEFAULT = 400


def _citation_of(row: SchoolMajorScore, source: Source | None) -> dict[str, Any] | None:
    """来源三要素：优先取 source 表登记，缺任一项返回 None（该行不参与候选）。"""
    name = (source.source_name if source else "") or ""
    url = (source.source_url if source else "") or ""
    year = (source.year if source else None)
    if not name.strip() or not url.strip() or not isinstance(year, int):
        return None
    return {"source_name": name, "source_url": url, "year": year}


def db_candidates(
    db: Session,
    *,
    province: str,
    subject_type: str = "",
    year: int | None = None,
    limit: int = CANDIDATE_LIMIT_DEFAULT,
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    """把库内录取分整理为候选；返回 ``(candidates, meta)``。

    ``meta`` 始终如实说明数据状态与未纳入原因，供方案响应写入 ``data_note``。
    """
    province = str(province or "").strip()
    subject_type = str(subject_type or "").strip()
    meta: dict[str, Any] = {
        "province": province,
        "subject_type": subject_type,
        "year": year,
        "count": 0,
        "years": [],
        "skipped": {},
        "notes": [],
    }
    if not province:
        meta["notes"].append("未提供省份，无法从库内取候选")
        return (), meta
    if not subject_type:
        # 科类是分档比较的前提：同校的「物理类」与「历史类」不是同一群体，
        # 混在一起取最低分等于跨考试制度比较（数据红线），故直接不取候选。
        meta["notes"].append("未提供科类（subject_type），为避免跨考试制度混合，未取候选")
        return (), meta

    stmt = (
        select(SchoolMajorScore, School, Source)
        .join(School, School.id == SchoolMajorScore.school_id)
        .outerjoin(Source, Source.id == SchoolMajorScore.source_id)
        .where(
            SchoolMajorScore.province == province,
            SchoolMajorScore.school_id.is_not(None),
            SchoolMajorScore.min_score.is_not(None),
        )
    )
    rows = db.execute(stmt).all()

    years: set[int] = set()
    skipped: dict[str, int] = {}
    pooled = 0
    # school_id -> 取到的院校最低录取分那一行
    best: dict[int, tuple[SchoolMajorScore, School, Source | None]] = {}

    for score, school, source in rows:
        years.add(int(score.year))
        if batch_code_of(score.batch) != BATCH_CODE_UG:
            skipped["batch_not_unified"] = skipped.get("batch_not_unified", 0) + 1
            continue
        if year is not None and int(score.year) != int(year):
            continue
        if subject_type and (score.subject_type or "").strip() != subject_type:
            skipped["subject_type_mismatch"] = skipped.get("subject_type_mismatch", 0) + 1
            continue
        if _citation_of(score, source) is None:
            skipped["citation_missing"] = skipped.get("citation_missing", 0) + 1
            continue
        pooled += 1
        current = best.get(int(score.school_id))
        if current is None or int(score.min_score) < int(current[0].min_score):
            best[int(score.school_id)] = (score, school, source)

    meta["years"] = sorted(years)
    meta["skipped"] = skipped

    candidates: list[dict[str, Any]] = []
    for school_id, (score, school, source) in sorted(best.items()):
        citation = _citation_of(score, source)
        candidates.append(
            {
                # 与演示候选同形状：院校层次数据同源落库，供排序依据与展示使用
                "school_id": str(school_id),
                "name": school.name,
                "province": school.province or "",
                "city": school.city or "",
                "major": score.major_name or "",
                "subject_requirement": (score.subject_type or "").strip(),
                "min_score": int(score.min_score),
                "min_rank": score.min_rank,
                "admission_year": int(score.year),
                "batch": score.batch or "",
                "is_985": bool(school.is_985),
                "is_211": bool(school.is_211),
                "dual_class": school.dual_class or "",
                **(citation or {}),
            }
        )

    candidates.sort(key=lambda item: (-int(item["min_score"]), item["name"]))
    if len(candidates) > limit:
        candidates = candidates[:limit]

    meta["count"] = len(candidates)
    meta["pooled_rows"] = pooled
    if not candidates:
        if "batch_not_unified" in skipped and not pooled:
            meta["notes"].append(
                "库内该省录取分的批次尚未按契约 8.3 归一为 batch_code，"
                "为避免跨批次混合未纳入候选（见 batch 归一待裁决）"
            )
        else:
            meta["notes"].append("库内没有匹配该省份 / 科类 / 普通本科批的录取分数据")
    return tuple(candidates), meta
