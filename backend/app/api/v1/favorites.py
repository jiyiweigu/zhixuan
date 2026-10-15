"""收藏接口（契约 6.1 节 ``/api/user/favorites``）。

- ``GET    /api/user/favorites``                        当前用户的收藏列表
- ``POST   /api/user/favorites``                        新增收藏（幂等）
- ``DELETE /api/user/favorites?target_type=&target_id=`` 取消收藏

全部要求登录（Auth: yes）：缺令牌 1002。收藏对象只能为 ``school`` / ``major``，
取值非法返回 1001。同一 (用户, 类型, 对象) 重复收藏按幂等处理，返回已存在的记录，
避免前端重复点击写入重复行。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.response import BizError, ok
from app.db.session import get_db
from app.models.user import User
from app.models.user_data import UserFavorite
from app.schemas.core import FavoriteWrite
from app.services import majors as majors_service
from app.services import schools as schools_service

router = APIRouter(prefix="/user/favorites", tags=["收藏"])


def _resolve_name(db: Session, target_type: str, target_id: str) -> str:
    """尽量把收藏对象解析为可读名称；解析不到时回退为 ID，不报错。"""
    try:
        if target_type == "school":
            detail = schools_service.get_school(db, int(target_id))
        elif target_type == "major":
            detail = majors_service.get_major(db, int(target_id))
        else:
            detail = None
        if detail:
            return str(detail.get("name") or target_id)
    except Exception:  # noqa: BLE001 - 名称仅为展示优化，任何失败都回退为 ID
        pass
    return target_id


def _serialize(db: Session, row: UserFavorite) -> dict[str, Any]:
    return {
        "favorite_id": row.id,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "target_name": _resolve_name(db, row.target_type, row.target_id),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("", summary="我的收藏")
def list_favorites(
    target_type: str = Query(default="", description="按类型过滤：school / major"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(UserFavorite).where(UserFavorite.user_id == user.id)
    if target_type:
        stmt = stmt.where(UserFavorite.target_type == target_type)
    rows = list(db.scalars(stmt.order_by(UserFavorite.created_at.desc(), UserFavorite.id.desc())).all())
    return ok([_serialize(db, row) for row in rows])


@router.post("", summary="新增收藏")
def create_favorite(
    payload: FavoriteWrite,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """幂等：同一 (用户, 类型, 对象) 已存在时直接返回既有记录。"""
    existing = db.scalar(
        select(UserFavorite).where(
            UserFavorite.user_id == user.id,
            UserFavorite.target_type == payload.target_type,
            UserFavorite.target_id == payload.target_id,
        )
    )
    if existing is not None:
        return ok(_serialize(db, existing))

    row = UserFavorite(
        user_id=user.id, target_type=payload.target_type, target_id=payload.target_id
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ok(_serialize(db, row))


@router.delete("", summary="取消收藏")
def delete_favorite(
    target_type: str = Query(..., description="school / major"),
    target_id: str = Query(..., description="被收藏对象 ID"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """未收藏时同样返回成功（幂等删除），避免前端需要先查询再删除。"""
    if target_type not in ("school", "major"):
        raise BizError("参数错误：target_type 只能为 school 或 major")
    db.execute(
        delete(UserFavorite).where(
            UserFavorite.user_id == user.id,
            UserFavorite.target_type == target_type,
            UserFavorite.target_id == target_id,
        )
    )
    db.commit()
    return ok(None)
