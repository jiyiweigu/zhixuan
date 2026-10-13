"""分页工具（产品书 6.0.3 分页结构）。

统一分页包形状 ``{items, total, page, page_size}``，供院校、专业等列表接口复用，
避免各模块各写一套 offset/limit 与 total 统计。

``total`` 取过滤后的总数（与 page 无关），因此前端可据此渲染页码；
越界 page 返回空 items 但 total 不变，不报错。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

PAGE_DEFAULT = 1
PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 100

Row = TypeVar("Row")


def normalize_page(page: int, page_size: int) -> tuple[int, int]:
    """把页码与每页条数收敛到合法区间。"""
    return max(PAGE_DEFAULT, int(page)), max(1, min(int(page_size), PAGE_SIZE_MAX))


def envelope(items: list[Any], total: int, page: int, page_size: int) -> dict[str, Any]:
    """组装分页包（产品书 6.0.3）。"""
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def count_of(db: Session, stmt: Select[Any]) -> int:
    """按 stmt 的过滤条件统计总条数（忽略排序与分页）。"""
    return int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)


def page_rows(db: Session, stmt: Select[Any], *, page: int, page_size: int) -> list[Any]:
    """取指定页的行。调用方须保证 stmt 带确定性排序。"""
    page, page_size = normalize_page(page, page_size)
    return list(db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all())


def paginate(
    db: Session,
    stmt: Select[Any],
    *,
    page: int,
    page_size: int,
    serializer: Callable[[Any], dict[str, Any]],
) -> dict[str, Any]:
    """执行查询并返回分页包（序列化与行一一对应时用这个）。

    需要批量补充字段（如一次性查全页的来源）时，改用
    ``count_of`` + ``page_rows`` + ``envelope`` 三步自行组装。
    """
    page, page_size = normalize_page(page, page_size)
    total = count_of(db, stmt)
    rows = page_rows(db, stmt, page=page, page_size=page_size)
    return envelope([serializer(row) for row in rows], total, page, page_size)
