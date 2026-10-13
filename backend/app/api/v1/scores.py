"""一分一段查询接口。

契约：docs/api-contract.md 6.1 节 ``GET /api/scores/segment``。

返回口径：``score`` 对应 ``cumulative_rank``（累计人数，即位次）与 ``same_score_count``
（同分人数 = 本分数累计人数 − 上一分数累计人数）。

数据缺失时不编造数字：沿用契约 §8.3 的处理方式，仍返回 HTTP 200，
用 ``data_status`` 说明是 ``schema_only``（结构已就绪、尚未导入）还是
``unavailable``（该省 / 年 / 科类没有对应版本），数值字段为 ``null``。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.response import BizError, ok
from app.db.session import get_db
from app.models.base_data import ScoreSegment
from app.models.source import Source

router = APIRouter(prefix="/scores", tags=["一分一段"])

# 与 6.1 约定一致：按分数或位次查询都需要省份 / 年份 / 科类定位版本
DATA_STATUS_AVAILABLE = "available"
DATA_STATUS_SCHEMA_ONLY = "schema_only"
DATA_STATUS_UNAVAILABLE = "unavailable"


def _citation(db: Session, source_id: int) -> dict[str, Any] | None:
    source = db.get(Source, source_id)
    if source is None:
        return None
    return {
        "source_name": source.source_name,
        "source_url": source.source_url,
        "year": source.year,
    }


@router.get("/segment", summary="分数 ↔ 位次换算（一分一段）")
def score_segment(
    province: str = Query(..., description="省份，如 河南"),
    year: int = Query(..., description="年份"),
    subject_type: str = Query(..., description="科类，如 物理类"),
    score: int | None = Query(default=None, ge=0, le=750, description="分数，二选一"),
    rank: int | None = Query(default=None, ge=1, description="位次，二选一"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """契约 6.1：Auth no；按 ``score`` 或 ``rank`` 其中之一查询。"""
    if score is None and rank is None:
        raise BizError("参数错误：score 与 rank 至少提供一个")

    stmt = (
        select(ScoreSegment)
        .where(
            ScoreSegment.province == province,
            ScoreSegment.year == year,
            ScoreSegment.subject_type == subject_type,
        )
        .order_by(ScoreSegment.score)
    )
    rows = list(db.scalars(stmt).all())
    if not rows:
        return ok(
            {
                "province": province,
                "year": year,
                "subject_type": subject_type,
                "data_status": DATA_STATUS_SCHEMA_ONLY,
                "score": score,
                "cumulative_rank": None,
                "same_score_count": None,
                "citations": [],
                "missing_rule_sets": ["score_segment"],
            }
        )

    by_score = {row.score: row for row in rows}

    if rank is not None and score is None:
        # 位次 → 分数：取「累计人数 >= 位次」的最小分数（即该位次所在分数）
        candidates = [row for row in rows if row.cumulative_rank >= rank]
        if not candidates:
            return ok(
                {
                    "province": province,
                    "year": year,
                    "subject_type": subject_type,
                    "data_status": DATA_STATUS_UNAVAILABLE,
                    "score": None,
                    "cumulative_rank": rank,
                    "same_score_count": None,
                    "citations": [],
                    "missing_rule_sets": [],
                }
            )
        hit = min(candidates, key=lambda row: row.score)
    else:
        hit = by_score.get(int(score))  # type: ignore[arg-type]
        if hit is None:
            return ok(
                {
                    "province": province,
                    "year": year,
                    "subject_type": subject_type,
                    "data_status": DATA_STATUS_UNAVAILABLE,
                    "score": score,
                    "cumulative_rank": None,
                    "same_score_count": None,
                    "citations": [],
                    "missing_rule_sets": [],
                }
            )

    upper = by_score.get(hit.score + 1)
    same_score_count = (
        hit.cumulative_rank - upper.cumulative_rank if upper is not None else hit.cumulative_rank
    )
    citation = _citation(db, hit.source_id)
    return ok(
        {
            "province": province,
            "year": year,
            "subject_type": subject_type,
            "data_status": DATA_STATUS_AVAILABLE,
            "score": hit.score,
            "cumulative_rank": hit.cumulative_rank,
            "same_score_count": max(0, same_score_count),
            "citations": [citation] if citation else [],
            "missing_rule_sets": [],
        }
    )
