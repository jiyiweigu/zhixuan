"""用户扩展数据表（产品书第 7.3 节）。

``users`` 与 ``profiles`` 两张表已在 0001 迁移中落地（见 app/models/user.py、profile.py），
本模块补齐该节剩余的两张表：收藏与志愿方案。

命名说明：第 7.3 节把账号表记作 ``user``、档案表记作 ``user_profile``，
而 0001 迁移与既有业务代码使用的是 ``users`` / ``profiles``。
为避免改写已合并的代码与迁移，这里保留既有表名，仅新增表沿用第 7 章的命名。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow
from app.models.constants import USER_ID_MAX_LENGTH


class UserFavorite(Base):
    """收藏（院校 / 专业）。"""

    __tablename__ = "user_favorite"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(USER_ID_MAX_LENGTH), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    target_type: Mapped[str] = mapped_column(String(16), comment="school / major")
    target_id: Mapped[str] = mapped_column(String(64), comment="被收藏对象 ID")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UserPlan(Base):
    """志愿方案（tasks.md 6.6 方案保存 / 命名 / 编辑）。

    ``items`` 保存方案生成接口（/api/plans）输出的结构化条目，
    按 JSON 原样落库，保证重新打开方案时与生成时逐字段一致。
    """

    __tablename__ = "user_plan"

    id: Mapped[str] = mapped_column(String(USER_ID_MAX_LENGTH), primary_key=True, comment="方案 ID，形如 plan_xxxx")
    user_id: Mapped[str] = mapped_column(
        String(USER_ID_MAX_LENGTH), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100), comment="方案名称，用户可自定义")
    strategy: Mapped[str] = mapped_column(
        String(16), default="balanced", comment="倾向：冲 / 稳 / 保 或 balanced"
    )
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, comment="冲—稳—保条目")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
