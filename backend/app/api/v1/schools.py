"""院校检索、详情、画像与并排对比接口（tasks.md 7.1、7.2；产品书 6.5.1–6.5.5）。

鉴权：产品书 6.5.1–6.5.5 均为「鉴权：否」，故本文件全部接口对游客开放。

契约变更（需队长登记，见 PR 描述）：
- ``GET /api/schools`` 由「返回院校数组」改为**分页包**
  ``{items, total, page, page_size}``（产品书 6.0.3 / 6.5.1，tasks.md 7.1 要求分页）。
  这是**破坏性变更**：`docs/api-contract.md` 第 6 节、`frontend/src/api/index.ts`
  与 `frontend/src/types/api.d.ts` 需同步，三者为队长维护的共享文件。
- 新增 ``GET /api/schools/{school_id}``、``/profile``、``/life``、``POST /compare`` 四个接口。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core import pagination
from app.core.response import BizError, ok
from app.db.session import get_db
from app.schemas.core import SchoolCompareRequest
from app.services import schools as schools_service

router = APIRouter(prefix="/schools", tags=["院校检索"])


@router.get("", summary="院校检索（多条件 + 分页）")
def search_schools(
    keyword: str = Query("", description="关键词，匹配院校名称 / 城市 / 简介"),
    province: str = Query("", description="所在省份，如 河南"),
    level: str = Query("", description="办学层次：本科 / 专科"),
    school_type: str = Query("", alias="type", description="院校类型：综合 / 理工 / 师范…"),
    ownership: str = Query("", description="办学性质：公办 / 民办"),
    is_985: bool | None = Query(
        None, description="院校层次：true 仅 985，false 仅非 985，不传不限制"
    ),
    is_211: bool | None = Query(
        None, description="院校层次：true 仅 211，false 仅非 211，不传不限制"
    ),
    dual_class: str = Query("", description="院校层次标记精确匹配，如 双一流"),
    page: int = Query(pagination.PAGE_DEFAULT, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(
        pagination.PAGE_SIZE_DEFAULT, ge=1, le=pagination.PAGE_SIZE_MAX, description="每页条数"
    ),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """组合条件筛选（条件之间为「与」），结果分页返回，每项带来源三要素。

    每项同时返回院校层次 ``is_985`` / ``is_211`` / ``dual_class``（2026-10-14 起可用）。
    """
    return ok(
        schools_service.search_schools(
            db,
            keyword=keyword,
            province=province,
            level=level,
            school_type=school_type,
            ownership=ownership,
            is_985=is_985,
            is_211=is_211,
            dual_class=dual_class,
            page=page,
            page_size=page_size,
        )
    )


@router.post("/compare", summary="院校并排对比")
def compare_schools(
    payload: SchoolCompareRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """多所院校关键指标并排（产品书 6.5.5）。

    按传入顺序返回（去重后保留首次出现），单次上限 5 所；任一院校不存在 → 1001。
    路径声明在 ``/{school_id}`` 之前，避免被动态段抢先匹配。
    """
    return ok(schools_service.compare_schools(db, payload.school_ids))


@router.get("/{school_id}", summary="院校详情")
def get_school(
    school_id: int,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """院校概况 + 来源清单。"""
    detail = schools_service.get_school(db, school_id)
    if detail is None:
        raise BizError(f"院校不存在：{school_id}")
    return ok(detail)


@router.get("/{school_id}/profile", summary="院校画像")
def get_school_profile(
    school_id: int,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """学费 / 师资 / 校区等画像（tasks.md 7.2），``source_note`` 必填。

    该校暂无画像数据时返回结构完整、``available=false`` 的空态，而非报错，
    便于前端区分「无此院校」（1001）与「有院校但暂无画像」。
    """
    profile = schools_service.get_profile(db, school_id)
    if profile is None:
        raise BizError(f"院校不存在：{school_id}")
    return ok(profile)


@router.get("/{school_id}/life", summary="院校生活信息")
def get_school_life(
    school_id: int,
    category: str = Query("", description="分类过滤：宿舍 / 食堂 / 交通 / 校园环境…"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """生活信息，逐条带来源与可靠性标注；非官方来源由前端默认折叠（tasks.md 7.3）。"""
    life = schools_service.get_life(db, school_id, category)
    if life is None:
        raise BizError(f"院校不存在：{school_id}")
    return ok(life)
