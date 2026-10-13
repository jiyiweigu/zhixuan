"""数据统计接口（产品书 6.6.11；tasks.md 8.7）。

``GET /stats`` 实时聚合库内数据，不缓存——验收条件「统计页数据与库内一致」
因此天然成立（每次调用都重新计数）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.response import ok
from app.db.session import get_db
from app.services import stats as stats_service

router = APIRouter(tags=["管理端·统计"])


@router.get("/stats", summary="数据统计（语料覆盖度 / 问答量 / 低置信清单）")
def overview(db: Session = Depends(get_db)) -> dict[str, Any]:
    return ok(stats_service.overview(db))
