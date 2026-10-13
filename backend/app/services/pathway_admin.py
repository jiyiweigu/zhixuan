"""途径与资格规则维护（tasks.md 8.6；产品书 6.6.6–6.6.7）。

核心约束：**规则必须附官方来源**——``source`` 三要素缺一即 4001，规则不入库。
这是 8.6 的验收条件「未填来源无法保存规则」，由 app/services/source_guard.py 统一实现。

写操作（新建/修改途径、新建/修改规则）全部留痕（tasks.md 8.1）。
专项实施区域（``pathway_region``）在此只读：该名单属 ③ 号数据管道产出（tasks.md 2.3），
管理端暂不提供编辑入口（如需维护另开任务）。
"""

from __future__ import annotations

import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.response import BizCode, BizError
from app.models.audit import (
    ACTION_PATHWAY_CREATE,
    ACTION_PATHWAY_UPDATE,
    ACTION_RULE_CREATE,
    ACTION_RULE_UPDATE,
)
from app.models.knowledge import AdminUser
from app.models.pathway import Pathway, PathwayEligibility, PathwayRegion
from app.models.source import Source
from app.services import audit as audit_service
from app.services import source_guard

__all__ = [
    "create_pathway",
    "create_rule",
    "list_pathways",
    "list_regions",
    "list_rules",
    "pathway_item",
    "region_item",
    "rule_item",
    "update_pathway",
    "update_rule",
]

PATHWAY_ID_PREFIX = "p_"
PATHWAY_ID_BYTES = 6


def _citation(source: Source | None) -> dict[str, Any]:
    if source is None:
        return {"source_name": "", "source_url": "", "year": 0}
    return {
        "source_name": source.source_name,
        "source_url": source.source_url,
        "year": source.year,
    }


def _new_pathway_id(db: Session) -> str:
    """生成途径 id，形如 ``p_1a2b3c4d5e6f``；与 users.id 同风格。"""
    for _ in range(10):
        candidate = f"{PATHWAY_ID_PREFIX}{secrets.token_hex(PATHWAY_ID_BYTES)}"
        if db.get(Pathway, candidate) is None:
            return candidate
    raise BizError("途径 id 生成失败，请重试", BizCode.INTERNAL_ERROR)


# --------------------------------------------------------------------------- #
# 序列化
# --------------------------------------------------------------------------- #
def pathway_item(pathway: Pathway, source: Source | None = None) -> dict[str, Any]:
    """途径字典项（产品书 6.6.6「同 6.2.1 结构」）。"""
    return {
        "pathway_id": pathway.id,
        "name": pathway.name,
        "category": pathway.category,
        "batch": pathway.batch,
        "target_group": pathway.target_group,
        "apply_time": pathway.apply_time,
        "description": pathway.description,
        "priority": pathway.priority,
        "data_status": pathway.data_status,
        "year": pathway.year,
        "source": _citation(source),
    }


def rule_item(rule: PathwayEligibility, source: Source | None = None) -> dict[str, Any]:
    """资格规则项（产品书 7.2 pathway_eligibility 字段）。"""
    return {
        "rule_id": rule.id,
        "pathway_id": rule.pathway_id,
        "province": rule.province,
        "rule_type": rule.rule_type,
        "rule_desc": rule.rule_desc,
        "params": dict(rule.params or {}),
        "year": rule.year,
        "source": _citation(source),
    }


def region_item(region: PathwayRegion, source: Source | None = None) -> dict[str, Any]:
    """专项实施区域项（产品书 6.6.8：county_name / county_code / source_name）。"""
    return {
        "region_id": region.id,
        "pathway_id": region.pathway_id,
        "province": region.province,
        "county_name": region.county_name,
        "county_code": region.county_code,
        "year": region.year,
        "source_name": source.source_name if source else "",
        "source_url": source.source_url if source else "",
    }


# --------------------------------------------------------------------------- #
# 途径字典
# --------------------------------------------------------------------------- #
def list_pathways(
    db: Session, *, category: str = "", priority: str = "", data_status: str = ""
) -> list[dict[str, Any]]:
    """管理端途径列表（读库表，返回数组，与用户端 6.2.1 形状一致）。"""
    stmt = select(Pathway)
    if category.strip():
        stmt = stmt.where(Pathway.category == category.strip())
    if priority.strip():
        stmt = stmt.where(Pathway.priority == priority.strip())
    if data_status.strip():
        stmt = stmt.where(Pathway.data_status == data_status.strip())
    rows = list(db.scalars(stmt.order_by(Pathway.id.asc())).all())
    sources = _sources_of(db, [row.source_id for row in rows])
    return [pathway_item(row, sources.get(row.source_id)) for row in rows]


def _sources_of(db: Session, source_ids: list[int]) -> dict[int, Source]:
    ids = sorted({sid for sid in source_ids if sid})
    if not ids:
        return {}
    rows = db.scalars(select(Source).where(Source.id.in_(ids))).all()
    return {row.id: row for row in rows}


def create_pathway(
    db: Session, payload: Any, admin: AdminUser, *, client_ip: str = ""
) -> dict[str, Any]:
    """新建途径（产品书 6.6.6）。缺来源 → 4001。"""
    source_guard.require_source(
        payload.source.source_name, payload.source.source_url, payload.source.year
    )
    year = source_guard.require_year(payload.year or payload.source.year)
    source = source_guard.ensure_source(db, payload.source)

    pathway = Pathway(
        id=_new_pathway_id(db),
        name=str(payload.name).strip(),
        category=str(payload.category or "").strip(),
        batch=str(payload.batch or "").strip(),
        target_group=str(payload.target_group or "").strip(),
        apply_time=str(payload.apply_time or "").strip(),
        description=payload.description or "",
        priority=payload.priority,
        data_status=payload.data_status,
        year=year,
        source_id=source.id,
    )
    db.add(pathway)
    audit_service.record_audit(
        db,
        admin,
        ACTION_PATHWAY_CREATE,
        target_type="pathway",
        target_id=pathway.id,
        detail={"name": pathway.name, "year": year, "source_name": source.source_name},
        client_ip=client_ip,
    )
    db.commit()
    return {"pathway_id": pathway.id}


def update_pathway(
    db: Session, pathway_id: str, payload: Any, admin: AdminUser, *, client_ip: str = ""
) -> None:
    """修改途径（产品书 6.6.6）。不存在 → 1001；缺来源 → 4001。"""
    pathway = db.get(Pathway, pathway_id)
    if pathway is None:
        raise BizError("途径不存在", BizCode.PARAM_ERROR)

    source_guard.require_source(
        payload.source.source_name, payload.source.source_url, payload.source.year
    )
    year = source_guard.require_year(payload.year or payload.source.year)
    source = source_guard.ensure_source(db, payload.source)

    pathway.name = str(payload.name).strip()
    pathway.category = str(payload.category or "").strip()
    pathway.batch = str(payload.batch or "").strip()
    pathway.target_group = str(payload.target_group or "").strip()
    pathway.apply_time = str(payload.apply_time or "").strip()
    pathway.description = payload.description or ""
    pathway.priority = payload.priority
    pathway.data_status = payload.data_status
    pathway.year = year
    pathway.source_id = source.id

    audit_service.record_audit(
        db,
        admin,
        ACTION_PATHWAY_UPDATE,
        target_type="pathway",
        target_id=pathway_id,
        detail={"name": pathway.name, "year": year},
        client_ip=client_ip,
    )
    db.commit()


# --------------------------------------------------------------------------- #
# 资格规则
# --------------------------------------------------------------------------- #
def list_rules(
    db: Session, *, pathway_id: str = "", province: str = "", rule_type: str = ""
) -> list[dict[str, Any]]:
    """资格规则列表（可按途径 / 省份 / 类型过滤）。"""
    stmt = select(PathwayEligibility)
    if pathway_id.strip():
        stmt = stmt.where(PathwayEligibility.pathway_id == pathway_id.strip())
    if province.strip():
        stmt = stmt.where(PathwayEligibility.province == province.strip())
    if rule_type.strip():
        stmt = stmt.where(PathwayEligibility.rule_type == rule_type.strip())
    rows = list(db.scalars(stmt.order_by(PathwayEligibility.id.asc())).all())
    sources = _sources_of(db, [row.source_id for row in rows])
    return [rule_item(row, sources.get(row.source_id)) for row in rows]


def _load_rule(db: Session, rule_id: int) -> PathwayEligibility:
    rule = db.get(PathwayEligibility, rule_id)
    if rule is None:
        raise BizError("资格规则不存在", BizCode.PARAM_ERROR)
    return rule


def create_rule(
    db: Session, payload: Any, admin: AdminUser, *, client_ip: str = ""
) -> dict[str, Any]:
    """新建资格规则（产品书 6.6.7）。**未填来源 → 4001，规则不入库**（tasks.md 8.6 验收）。"""
    source_guard.require_source(
        payload.source.source_name, payload.source.source_url, payload.source.year
    )
    year = source_guard.require_year(payload.year or payload.source.year)

    if db.get(Pathway, payload.pathway_id) is None:
        raise BizError(f"参数错误：途径不存在：{payload.pathway_id}")

    source = source_guard.ensure_source(db, payload.source)
    rule = PathwayEligibility(
        pathway_id=payload.pathway_id,
        province=str(payload.province or "").strip(),
        rule_type=payload.rule_type,
        rule_desc=payload.rule_desc or "",
        params=dict(payload.params or {}),
        year=year,
        source_id=source.id,
    )
    db.add(rule)
    db.flush()

    audit_service.record_audit(
        db,
        admin,
        ACTION_RULE_CREATE,
        target_type="rule",
        target_id=rule.id,
        detail={
            "pathway_id": rule.pathway_id,
            "rule_type": rule.rule_type,
            "province": rule.province,
            "source_name": source.source_name,
        },
        client_ip=client_ip,
    )
    db.commit()
    return {"rule_id": rule.id}


def update_rule(
    db: Session, rule_id: int, payload: Any, admin: AdminUser, *, client_ip: str = ""
) -> None:
    """修改资格规则（产品书 6.6.7）。不存在 → 1001；缺来源 → 4001。"""
    rule = _load_rule(db, rule_id)

    source_guard.require_source(
        payload.source.source_name, payload.source.source_url, payload.source.year
    )
    year = source_guard.require_year(payload.year or payload.source.year)

    if payload.pathway_id != rule.pathway_id and db.get(Pathway, payload.pathway_id) is None:
        raise BizError(f"参数错误：途径不存在：{payload.pathway_id}")

    source = source_guard.ensure_source(db, payload.source)
    rule.pathway_id = payload.pathway_id
    rule.province = str(payload.province or "").strip()
    rule.rule_type = payload.rule_type
    rule.rule_desc = payload.rule_desc or ""
    rule.params = dict(payload.params or {})
    rule.year = year
    rule.source_id = source.id

    audit_service.record_audit(
        db,
        admin,
        ACTION_RULE_UPDATE,
        target_type="rule",
        target_id=rule_id,
        detail={"pathway_id": rule.pathway_id, "rule_type": rule.rule_type},
        client_ip=client_ip,
    )
    db.commit()


# --------------------------------------------------------------------------- #
# 专项实施区域（只读）
# --------------------------------------------------------------------------- #
def list_regions(
    db: Session, *, pathway_id: str = "", province: str = "", limit: int = 500
) -> list[dict[str, Any]]:
    """专项实施区域名单（产品书 6.6.8）。数据由 ③ 号按 tasks.md 2.3 入库。"""
    stmt = select(PathwayRegion)
    if pathway_id.strip():
        stmt = stmt.where(PathwayRegion.pathway_id == pathway_id.strip())
    if province.strip():
        stmt = stmt.where(PathwayRegion.province == province.strip())
    rows = list(db.scalars(stmt.order_by(PathwayRegion.id.asc()).limit(max(1, min(limit, 2000)))).all())
    sources = _sources_of(db, [row.source_id for row in rows])
    return [region_item(row, sources.get(row.source_id)) for row in rows]
