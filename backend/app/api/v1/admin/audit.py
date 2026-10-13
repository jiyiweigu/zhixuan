"""操作留痕查询接口（tasks.md 8.1）。

产品书 6.6 未定义该接口；但 8.1 的验收条件是「操作记录含操作人 / 时间 / 动作」，
留痕若只能读数据库就不便核查，故补一个只读查询口供 ⑤ 管理端展示操作流水。
已在 PR 描述中提请队长确认（属**追加**接口，不影响既有契约）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core import pagination
from app.core.response import ok
from app.db.session import get_db
from app.services import audit as audit_service

router = APIRouter(prefix="/audit-logs", tags=["管理端·留痕"])


@router.get("", summary="操作留痕列表")
def list_audit_logs(
    action: str = Query(default="", description="按动作过滤，如 doc.create"),
    admin_username: str = Query(default="", description="按操作人过滤"),
    page: int = Query(default=pagination.PAGE_DEFAULT, ge=1),
    page_size: int = Query(default=pagination.PAGE_SIZE_DEFAULT, ge=1, le=pagination.PAGE_SIZE_MAX),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        audit_service.list_audit_logs(
            db, action=action, admin_username=admin_username, page=page, page_size=page_size
        )
    )
