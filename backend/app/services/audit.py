"""管理端操作留痕（tasks.md 8.1）。

写入时机：管理端的每一次**写操作**与登录成功都会落一条 ``admin_audit_log``。
记录内容满足 8.1 验收条件「操作记录含操作人 / 时间 / 动作」：
``admin_id`` + ``admin_username``（操作人）、``created_at``（时间）、
``action``（动作），并按需附带 ``target_type`` / ``target_id`` / ``detail``。

两条约定：
1. ``record_audit`` 只 ``add``、不 ``commit``，与调用方自身的业务改动在同一事务提交，
   避免出现「业务成功但留痕丢失」或反之；
2. ``detail`` 绝不写入口令、令牌等凭据（调用方负责只传业务字段）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import pagination
from app.models.audit import AdminAuditLog
from app.models.knowledge import AdminUser

__all__ = [
    "audit_item",
    "list_audit_logs",
    "record_audit",
]


def record_audit(
    db: Session,
    admin: AdminUser,
    action: str,
    *,
    target_type: str = "",
    target_id: Any = "",
    detail: dict[str, Any] | None = None,
    client_ip: str = "",
) -> AdminAuditLog:
    """写入一条留痕（不提交，由调用方随业务改动一并提交）。"""
    row = AdminAuditLog(
        admin_id=admin.id,
        admin_username=admin.username,
        action=action,
        target_type=target_type or "",
        target_id=str(target_id or ""),
        detail=dict(detail or {}),
        client_ip=client_ip or "",
    )
    db.add(row)
    return row


def audit_item(row: AdminAuditLog) -> dict[str, Any]:
    """留痕列表项。"""
    return {
        "log_id": row.id,
        "admin_id": row.admin_id,
        "admin_username": row.admin_username,
        "action": row.action,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "detail": dict(row.detail or {}),
        "client_ip": row.client_ip,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_audit_logs(
    db: Session,
    *,
    action: str = "",
    admin_username: str = "",
    page: int = pagination.PAGE_DEFAULT,
    page_size: int = pagination.PAGE_SIZE_DEFAULT,
) -> dict[str, Any]:
    """按动作 / 操作人查询留痕，最近的在先（供 ⑤ 管理端展示与核查）。"""
    stmt = select(AdminAuditLog)
    if action.strip():
        stmt = stmt.where(AdminAuditLog.action == action.strip())
    if admin_username.strip():
        stmt = stmt.where(AdminAuditLog.admin_username == admin_username.strip())
    stmt = stmt.order_by(AdminAuditLog.id.desc())
    return pagination.paginate(
        db, stmt, page=page, page_size=page_size, serializer=audit_item
    )
