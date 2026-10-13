"""来源强制校验（产品书第 7 章、6.0.4；tasks.md 8.2、8.6）。

第 7 章规定「所有事实表必须含 source_name / source_url / year 三要素（或外键 source_id），
缺失拒绝入库」；产品书 6.0.4 把这种情况单列为错误码 **4001**（「缺少来源信息，拒绝入库」，
前端标红提示），与 1001 参数校验失败区分开。

管理端语料导入与规则维护共用本模块，保证两处口径一致——
「未填来源无法保存」这一验收条件只实现一次。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.response import BizCode, BizError
from app.models.constants import YEAR_MAX, YEAR_MIN
from app.models.source import Source

MISSING_SOURCE_MESSAGE = "缺少来源信息（source_name / source_url / year），拒绝入库"


def missing_source_fields(
    source_name: str = "", source_url: str = "", year: int = 0
) -> list[str]:
    """返回缺失（或占位为 0）的来源字段名，供错误提示与留痕使用。"""
    missing: list[str] = []
    if not str(source_name or "").strip():
        missing.append("source_name")
    if not str(source_url or "").strip():
        missing.append("source_url")
    if not int(year or 0):
        missing.append("year")
    return missing


def require_source(source_name: str = "", source_url: str = "", year: int = 0) -> None:
    """缺任一来源要素则抛 4001。"""
    missing = missing_source_fields(source_name, source_url, year)
    if missing:
        raise BizError(f"{MISSING_SOURCE_MESSAGE}：缺少 {'、'.join(missing)}", BizCode.MISSING_SOURCE)


def require_year(year: int, *, field: str = "year") -> int:
    """年份须落在合理区间（与各事实表 CHECK 口径一致），否则 1001。"""
    value = int(year or 0)
    if not (YEAR_MIN <= value <= YEAR_MAX):
        raise BizError(f"参数错误：{field} 需在 {YEAR_MIN}–{YEAR_MAX} 之间")
    return value


def ensure_source(db: Session, payload: Any) -> Source:
    """按三要素取回或新建 source 行（幂等）。

    ``payload`` 需含 ``source_name`` / ``source_url`` / ``year``，可选 ``source_type``；
    调用前应已执行 ``require_source`` / ``require_year`` 校验。
    """
    name = str(payload.source_name).strip()
    url = str(payload.source_url).strip()
    year = int(payload.year)
    source_type = getattr(payload, "source_type", None)

    existing = db.scalar(
        select(Source).where(
            Source.source_name == name,
            Source.source_url == url,
            Source.year == year,
        )
    )
    if existing is not None:
        if source_type and not existing.source_type:
            existing.source_type = source_type
        return existing

    source = Source(source_name=name, source_url=url, year=year, source_type=source_type)
    db.add(source)
    db.flush()
    return source
