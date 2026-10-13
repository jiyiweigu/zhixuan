"""管理端操作留痕表（tasks.md 8.1）。

产品书第 7 章未定义独立的审计表，但 8.1 的验收条件是「非管理员被拒；**操作记录**
含操作人 / 时间 / 动作」——审核类操作由 ``review_task.reviewer`` / ``reviewed_at``
承载，而语料导入、规则维护等写操作此前没有任何落库记录。

故此处新增 ``admin_audit_log`` 一张表，只记管理端**写操作**与登录：
- 记录「谁（admin_id + admin_username 冗余，账号改名后仍可追溯）、何时（created_at）、
  做了什么（action）、对什么（target_type + target_id）、结果明细（detail）」；
- 只追加不修改，任何一条留痕都不提供更新接口。

⚠️ 该表不在产品书第 7 章的表清单内，属为满足 8.1 验收而新增，
已在 PR 描述中提请队长确认（若队长要求改由结构化日志承载，删除本表与相关调用即可，
不影响其余接口）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow

ACTION_MAX_LENGTH = 64
TARGET_TYPE_MAX_LENGTH = 32
TARGET_ID_MAX_LENGTH = 64
ADMIN_USERNAME_MAX_LENGTH = 50
CLIENT_IP_MAX_LENGTH = 64

# 动作常量（第 7 章「枚举字段用常量，禁止魔法值」）
ACTION_ADMIN_LOGIN = "admin.login"
ACTION_DOC_CREATE = "doc.create"
ACTION_DOC_DELETE = "doc.delete"
ACTION_PATHWAY_CREATE = "pathway.create"
ACTION_PATHWAY_UPDATE = "pathway.update"
ACTION_RULE_CREATE = "rule.create"
ACTION_RULE_UPDATE = "rule.update"
# 人工审核闭环（tasks.md 8.5：三类操作“必须留痕”）
ACTION_REVIEW_APPROVE = "review.approve"
ACTION_REVIEW_CORRECT = "review.correct"
ACTION_REVIEW_REJECT = "review.reject"
# 索引重建（tasks.md 8.3）
ACTION_INDEX_REBUILD = "index.rebuild"

# 报考约束规则维护（v1.1 6.6：省份模板 / 选科要求 / 身体条件三组）
ACTION_CONSTRAINT_RULE_CREATE = "constraint_rule.create"
ACTION_CONSTRAINT_RULE_UPDATE = "constraint_rule.update"


class AdminAuditLog(Base):
    """管理端操作留痕（tasks.md 8.1）。"""

    __tablename__ = "admin_audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("admin_user.id"), index=True)
    admin_username: Mapped[str] = mapped_column(
        String(ADMIN_USERNAME_MAX_LENGTH),
        index=True,
        comment="操作人账号名（冗余保存，账号改名后仍可追溯到当时身份）",
    )
    action: Mapped[str] = mapped_column(
        String(ACTION_MAX_LENGTH), index=True, comment="动作，如 doc.create / rule.update"
    )
    target_type: Mapped[str] = mapped_column(
        String(TARGET_TYPE_MAX_LENGTH), default="", comment="对象类型：doc / pathway / rule …"
    )
    target_id: Mapped[str] = mapped_column(
        String(TARGET_ID_MAX_LENGTH), default="", comment="对象标识"
    )
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, comment="操作结果明细（不含任何口令 / 令牌）"
    )
    client_ip: Mapped[str] = mapped_column(String(CLIENT_IP_MAX_LENGTH), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<AdminAuditLog {self.admin_username} {self.action} #{self.id}>"
