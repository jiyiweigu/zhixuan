"""院校检索、详情、画像与并排对比业务逻辑（tasks.md 7.1、7.2；产品书 6.5.1–6.5.5）。

数据一律来自库表（school / school_major_score / school_profile / school_life / source），
因此 ③ 号按 tasks.md 2.5 把真实数据入库后本模块自动生效；
本地开发与测试的种子数据见 app/services/school_seed.py。

三条硬性约定：
1. **来源可追溯**：任何事实性字段都随来源展示。院校自身的来源由其录取分 / 画像 /
   生活信息所引用的 source 汇总而来（第 7.1 节把 school 定为不含 source_id 的基础字典，
   故不在此表上编造来源）；画像的 ``source_note`` 为必填。
2. **不做推断**：库中没有的数据一律返回空值 / 空数组并显式标记 ``available``，
   不猜测、也不用同类院校均值填充。
3. **分页稳定**：列表统一按主键升序（等同数据集录入顺序），保证翻页不重不漏。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core import pagination
from app.core.response import BizError
from app.models.base_data import School, SchoolMajorScore
from app.models.constants import DATA_STATUS_AVAILABLE, DATA_STATUS_SCHEMA_ONLY, MAX_COMPARE_SCHOOLS
from app.models.school_profile import SchoolLife, SchoolProfile
from app.models.source import Source

__all__ = [
    "citations_by_school",
    "compare_item",
    "compare_schools",
    "get_life",
    "get_profile",
    "get_school",
    "life_item",
    "profile_payload",
    "school_list_item",
    "school_summary",
    "search_schools",
]


# --------------------------------------------------------------------------- #
# 来源
# --------------------------------------------------------------------------- #
def citation_of_source(source: Source | None) -> dict[str, Any] | None:
    """source 行转来源三要素。"""
    if source is None:
        return None
    return {
        "source_name": source.source_name,
        "source_url": source.source_url,
        "year": source.year,
    }


def citation_of_life(life: SchoolLife) -> dict[str, Any]:
    """生活信息的来源三要素（第 7.4 节把三要素就地冗余在 school_life 上）。"""
    return {
        "source_name": life.source_name,
        "source_url": life.source_url,
        "year": life.year,
    }


def _dedupe_citations(citations: list[dict[str, Any] | None]) -> list[dict[str, Any]]:
    """按三要素去重，并按年份倒序、来源名升序排列，保证输出稳定。"""
    seen: set[tuple] = set()
    result: list[dict[str, Any]] = []
    for item in citations:
        if not item:
            continue
        key = (item.get("source_name"), item.get("source_url"), item.get("year"))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    result.sort(key=lambda item: (-int(item.get("year") or 0), str(item.get("source_name") or "")))
    return result


def citations_by_school(db: Session, school_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    """批量取一组院校的来源三要素（录取分 + 画像 + 生活信息）。

    列表接口一页最多 100 所院校，用三条查询一次算完，避免逐行 N+1。
    """
    if not school_ids:
        return {}

    grouped: dict[int, list[dict[str, Any] | None]] = {sid: [] for sid in school_ids}

    score_rows = db.execute(
        select(SchoolMajorScore.school_id, Source)
        .join(Source, Source.id == SchoolMajorScore.source_id)
        .where(SchoolMajorScore.school_id.in_(school_ids))
    ).all()
    for school_id, source in score_rows:
        grouped[school_id].append(citation_of_source(source))

    profile_rows = db.execute(
        select(SchoolProfile.school_id, Source)
        .join(Source, Source.id == SchoolProfile.source_id)
        .where(SchoolProfile.school_id.in_(school_ids))
    ).all()
    for school_id, source in profile_rows:
        grouped[school_id].append(citation_of_source(source))

    for life in db.scalars(select(SchoolLife).where(SchoolLife.school_id.in_(school_ids))).all():
        grouped[life.school_id].append(citation_of_life(life))

    return {sid: _dedupe_citations(items) for sid, items in grouped.items()}


def citations_of_school(db: Session, school_id: int) -> list[dict[str, Any]]:
    """单所院校的来源三要素。"""
    return citations_by_school(db, [school_id]).get(school_id, [])


def _source_note(source: Source | None) -> str:
    """画像的来源说明（产品书 6.5.3 标注为必填）。"""
    if source is None:
        return ""
    return f"来源：{source.source_name}（{source.year} 年）"


# --------------------------------------------------------------------------- #
# 序列化
# --------------------------------------------------------------------------- #
def school_summary(school: School) -> dict[str, Any]:
    """院校基础字段（产品书 6.5.1 的 items[] 字段集）。"""
    return {
        "school_id": school.id,
        "name": school.name,
        "code": school.code or "",
        "province": school.province,
        "city": school.city,
        "level": school.level,
        "type": school.type,
        "ownership": school.ownership,
    }


def school_list_item(school: School, citations: list[dict[str, Any]]) -> dict[str, Any]:
    """检索列表项 = 基础字段 + 来源三要素。

    来源键名用 ``citations``，与 docs/api-contract.md 第 6 节「每项含 citations」一致
    （详情接口按产品书 6.5.2 叫 ``sources``，两者差异已提请队长统一，见 PR 描述）。
    """
    return {**school_summary(school), "citations": citations}


def profile_payload(
    school: School, profile: SchoolProfile | None, source: Source | None
) -> dict[str, Any]:
    """画像响应（产品书 6.5.3）。无画像数据时结构完整但显式标记 available=False。"""
    if profile is None:
        return {
            "school_id": school.id,
            "name": school.name,
            "available": False,
            "tuition_range": None,
            "accommodation_fee": None,
            "campus_list": [],
            "established_year": None,
            "master_phd_points": None,
            "first_class_major_count": None,
            "faculty_count": None,
            "student_faculty_ratio": None,
            "source_note": "",
            "citations": [],
            # data_status 只用契约「跨层词表」四值；说明文字放 data_note
            "data_status": DATA_STATUS_SCHEMA_ONLY,
            "data_note": "暂无画像数据，待数据工程按 tasks.md 2.5 入库",
        }

    citation = citation_of_source(source)
    return {
        "school_id": school.id,
        "name": school.name,
        "available": True,
        "tuition_range": profile.tuition_range or None,
        "accommodation_fee": profile.accommodation_fee or None,
        "campus_list": list(profile.campus_list or []),
        "established_year": profile.established_year,
        "master_phd_points": profile.master_phd_points or None,
        "first_class_major_count": profile.first_class_major_count,
        "faculty_count": profile.faculty_count,
        "student_faculty_ratio": profile.student_faculty_ratio or None,
        "source_note": _source_note(source),
        "citations": [citation] if citation else [],
        "data_status": DATA_STATUS_AVAILABLE,
    }


def life_item(life: SchoolLife) -> dict[str, Any]:
    """生活信息项（产品书 6.5.4）。``reliability`` 供前端决定是否默认折叠（tasks.md 7.3）。"""
    return {
        "category": life.category,
        "content": life.content,
        "source_type": life.source_type,
        "source_name": life.source_name,
        "source_url": life.source_url,
        "year": life.year,
        "reliability": life.reliability,
    }


# --------------------------------------------------------------------------- #
# 检索（tasks.md 7.1）
# --------------------------------------------------------------------------- #
def search_schools(
    db: Session,
    *,
    keyword: str = "",
    province: str = "",
    level: str = "",
    school_type: str = "",
    ownership: str = "",
    page: int = pagination.PAGE_DEFAULT,
    page_size: int = pagination.PAGE_SIZE_DEFAULT,
) -> dict[str, Any]:
    """多条件院校检索 + 分页（产品书 6.5.1）。

    条件之间为「与」关系；``keyword`` 在名称、城市、简介三处做模糊匹配。
    空条件表示不限制，因此无参调用返回全部院校（分页）。
    """
    conditions = []
    if province.strip():
        conditions.append(School.province == province.strip())
    if level.strip():
        conditions.append(School.level == level.strip())
    if school_type.strip():
        conditions.append(School.type == school_type.strip())
    if ownership.strip():
        conditions.append(School.ownership == ownership.strip())
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        conditions.append(
            or_(School.name.like(like), School.city.like(like), School.intro.like(like))
        )

    stmt = select(School)
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(School.id.asc())

    page, page_size = pagination.normalize_page(page, page_size)
    total = pagination.count_of(db, stmt)
    rows = pagination.page_rows(db, stmt, page=page, page_size=page_size)
    citations = citations_by_school(db, [row.id for row in rows])
    items = [school_list_item(row, citations.get(row.id, [])) for row in rows]
    return pagination.envelope(items, total, page, page_size)


def get_school(db: Session, school_id: int) -> dict[str, Any] | None:
    """院校详情（产品书 6.5.2）；不存在返回 None。

    来源键名用 ``sources``（产品书 6.5.2 原文），与列表接口的 ``citations``
    存在命名差异，已提请队长统一（见 PR 描述）。
    """
    school = db.get(School, school_id)
    if school is None:
        return None
    return {
        **school_summary(school),
        "website": school.website or "",
        "intro": school.intro or "",
        "sources": citations_of_school(db, school_id),
    }


def get_profile(db: Session, school_id: int) -> dict[str, Any] | None:
    """院校画像（tasks.md 7.2）；院校不存在返回 None。"""
    school = db.get(School, school_id)
    if school is None:
        return None
    profile = db.scalar(select(SchoolProfile).where(SchoolProfile.school_id == school_id))
    source = db.get(Source, profile.source_id) if profile is not None else None
    return profile_payload(school, profile, source)


def get_life(db: Session, school_id: int, category: str = "") -> dict[str, Any] | None:
    """院校生活信息（tasks.md 7.3；产品书 6.5.4）；院校不存在返回 None。

    返回 ``items`` 与 ``categories``（该校已有信息的分类总集，供前端渲染筛选标签，
    不随 category 过滤变化），便于前端在筛选后仍能展示完整分类。
    """
    school = db.get(School, school_id)
    if school is None:
        return None

    all_rows = list(
        db.scalars(
            select(SchoolLife).where(SchoolLife.school_id == school_id).order_by(SchoolLife.id.asc())
        ).all()
    )
    categories: list[str] = []
    for row in all_rows:
        if row.category and row.category not in categories:
            categories.append(row.category)

    wanted = category.strip()
    rows = [row for row in all_rows if not wanted or row.category == wanted]
    return {
        "school_id": school.id,
        "name": school.name,
        "items": [life_item(row) for row in rows],
        "total": len(rows),
        "categories": categories,
    }


# --------------------------------------------------------------------------- #
# 并排对比（产品书 6.5.5）
# --------------------------------------------------------------------------- #
# 并排表中「可能缺失」的画像指标：缺失时置 null 并记入 missing，不做任何推断
PROFILE_METRICS = (
    "tuition_range",
    "accommodation_fee",
    "campus_count",
    "established_year",
    "master_phd_points",
    "first_class_major_count",
    "faculty_count",
    "student_faculty_ratio",
)


def _text(value: str | None) -> str | None:
    """空串按缺失处理（库中未填的字符串列存的是 ''）。"""
    return value or None


def compare_item(
    school: School, profile: SchoolProfile | None, source: Source | None
) -> dict[str, Any]:
    """并排表中的一行（产品书 6.5.5：层次 / 学费 / 一流专业数 / 师生比 / 校区数等）。

    无画像数据时画像指标一律 null 并列入 ``missing``，不猜测、不用同类院校均值填充
    （口径同本模块开头第 2 条）。
    """
    campuses = list(profile.campus_list or []) if profile is not None else []
    metrics: dict[str, Any] = {
        "tuition_range": _text(profile.tuition_range) if profile else None,
        "accommodation_fee": _text(profile.accommodation_fee) if profile else None,
        "campus_count": len(campuses) or None,
        "established_year": profile.established_year if profile else None,
        "master_phd_points": profile.master_phd_points if profile else None,
        "first_class_major_count": profile.first_class_major_count if profile else None,
        "faculty_count": profile.faculty_count if profile else None,
        "student_faculty_ratio": _text(profile.student_faculty_ratio) if profile else None,
    }
    citation = citation_of_source(source)
    return {
        "school_id": school.id,
        "name": school.name,
        "code": school.code or "",
        "province": school.province,
        "city": school.city,
        "level": school.level,
        "type": school.type,
        "ownership": school.ownership,
        **metrics,
        "profile_available": profile is not None,
        "missing": [field for field in PROFILE_METRICS if metrics[field] is None],
        "sources": [citation] if citation else [],
    }


def compare_schools(db: Session, school_ids: list[int]) -> dict[str, Any]:
    """多所院校关键指标并排（产品书 6.5.5）。

    - 展示顺序 = 入参顺序（去重后保留首次出现），与用户在页面上勾选的顺序一致；
    - 任一 id 不存在 → BizError(1001)：静默丢校会让并排表缺列，与用户所见不符；
    - 单次上限 ``MAX_COMPARE_SCHOOLS``，请求模型已先行拦截，这里再兜一次。
    """
    ordered: list[int] = []
    for school_id in school_ids:
        if school_id not in ordered:
            ordered.append(school_id)

    if not ordered:
        raise BizError("请至少选择一所院校进行对比")
    if len(ordered) > MAX_COMPARE_SCHOOLS:
        raise BizError(f"最多同时对比 {MAX_COMPARE_SCHOOLS} 所院校")

    rows = db.scalars(select(School).where(School.id.in_(ordered))).all()
    by_id = {row.id: row for row in rows}

    absent = [school_id for school_id in ordered if school_id not in by_id]
    if absent:
        raise BizError("院校不存在：" + "、".join(str(i) for i in absent))

    profiles = {
        profile.school_id: profile
        for profile in db.scalars(
            select(SchoolProfile).where(SchoolProfile.school_id.in_(ordered))
        ).all()
    }
    source_ids = [profile.source_id for profile in profiles.values()]
    sources: dict[int, Source] = {}
    if source_ids:
        sources = {
            source.id: source
            for source in db.scalars(select(Source).where(Source.id.in_(source_ids))).all()
        }

    items: list[dict[str, Any]] = []
    for school_id in ordered:
        profile = profiles.get(school_id)
        source = sources.get(profile.source_id) if profile is not None else None
        items.append(compare_item(by_id[school_id], profile, source))

    return {"items": items, "count": len(items), "max_compare": MAX_COMPARE_SCHOOLS}
