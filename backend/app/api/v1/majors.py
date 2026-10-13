"""专业检索与详情接口（tasks.md 7.1；产品书 6.5.6、6.5.7）。

鉴权：产品书 6.5.6 / 6.5.7 均为「鉴权：否」，故对游客开放。

契约变更（需队长登记）：``GET /api/majors`` 与 ``GET /api/majors/{major_id}``
为新增接口，`docs/api-contract.md` 尚无对应条目。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core import pagination
from app.core.response import BizError, ok
from app.db.session import get_db
from app.services import majors as majors_service

router = APIRouter(prefix="/majors", tags=["专业检索"])


@router.get("", summary="专业检索（多条件 + 分页）")
def search_majors(
    category: str = Query("", description="学科门类，如 工学 / 经济学"),
    keyword: str = Query("", description="关键词，匹配专业名称 / 专业代码"),
    page: int = Query(pagination.PAGE_DEFAULT, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(
        pagination.PAGE_SIZE_DEFAULT, ge=1, le=pagination.PAGE_SIZE_MAX, description="每页条数"
    ),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """按学科门类与关键词组合筛选，结果分页返回。"""
    return ok(
        majors_service.search_majors(
            db, category=category, keyword=keyword, page=page, page_size=page_size
        )
    )


@router.get("/{major_id}", summary="专业详情")
def get_major(
    major_id: int,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """专业详情；暂时无数据来源的字段在 ``data_status`` 中说明。"""
    detail = majors_service.get_major(db, major_id)
    if detail is None:
        raise BizError(f"专业不存在：{major_id}")
    return ok(detail)
