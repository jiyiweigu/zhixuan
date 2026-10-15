"""专业检索与详情业务逻辑（tasks.md 7.1；产品书 6.5.6、6.5.7）。

数据来自库表 ``major``（第 7.1 节的基础字典）。真实数据由 ③ 号按 tasks.md 2.5 采集入库，
本地开发与测试的种子见 app/services/school_seed.py。

关于 6.5.7 的两个字段：产品书要求返回 ``intro``（专业介绍）与 ``first_class_schools``
（把该专业建为一流本科专业建设点的院校），但第 7.1 节的 ``major`` 表既无 intro 列，
也没有「某校某专业为一流建设点」这类数据。按「缺来源不展示、绝不臆测」的约定，
本模块如实返回空值并在 ``data_status`` 中说明，不编造内容。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core import pagination
from app.models.base_data import Major
from app.models.constants import DATA_STATUS_PARTIAL

__all__ = [
    "get_major",
    "major_summary",
    "search_majors",
]

# 6.5.7 中暂无数据来源的字段说明（随响应返回，前端可据此隐藏对应区块）
MISSING_FIELD_NOTE = (
    "intro（专业介绍）列已存在（迁移 0008 已加 major.intro），但目前无数据来源"
    "（张的专业简介未入库）；first_class_schools（一流专业建设点院校）既无对应列也无来源。"
    "核心字段（名称 / 代码 / 学科门类 / 学位）来自教育部《普通高等学校本科专业目录（2025年）》。"
)


def major_summary(major: Major) -> dict[str, Any]:
    """列表项（产品书 6.5.6；``first_class`` 为本表实有字段，追加返回）。"""
    return {
        "major_id": major.id,
        "name": major.name,
        "code": major.code or "",
        "category": major.category,
        "degree": major.degree,
        "first_class": major.first_class,
    }


def search_majors(
    db: Session,
    *,
    category: str = "",
    keyword: str = "",
    page: int = pagination.PAGE_DEFAULT,
    page_size: int = pagination.PAGE_SIZE_DEFAULT,
) -> dict[str, Any]:
    """多条件专业检索 + 分页（产品书 6.5.6）。

    ``category`` 为学科门类精确匹配，``keyword`` 在专业名称与专业代码上模糊匹配。
    """
    conditions = []
    if category.strip():
        conditions.append(Major.category == category.strip())
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        conditions.append(or_(Major.name.like(like), Major.code.like(like)))

    stmt = select(Major)
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(Major.id.asc())

    return pagination.paginate(
        db, stmt, page=page, page_size=page_size, serializer=major_summary
    )


def get_major(db: Session, major_id: int) -> dict[str, Any] | None:
    """专业详情（产品书 6.5.7）；不存在返回 None。"""
    major = db.get(Major, major_id)
    if major is None:
        return None
    intro = (major.intro or "").strip()
    return {
        **major_summary(major),
        "intro": intro,
        "first_class_schools": [],
        # data_status 只用契约「跨层词表」四值；说明文字放 data_note，不塞进枚举字段
        # 专业库已按教育部目录落库（938 行）：intro 有值即 partial 之上，仍缺一流专业建设点院校
        "data_status": DATA_STATUS_PARTIAL,
        "data_note": MISSING_FIELD_NOTE,
    }
