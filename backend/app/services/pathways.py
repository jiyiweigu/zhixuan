"""升学途径目录业务逻辑（tasks.md 4.1）。

数据来自 app/data/pathways/catalog.json，由数据工程按 tasks.md 2.4 补齐 26 类途径字典。
资格判定不在此模块：design.md D6 要求判定结论必须由确定性规则引擎产出，
见 app/services/eligibility.py。
"""

from __future__ import annotations

from typing import Any

from app.core import dataset


def list_pathways(
    category: str | None = None,
    priority: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """返回升学途径目录，支持按分类 / 优先级 / 状态过滤。"""
    items = [dict(item) for item in dataset.load_catalog()]
    if category:
        items = [item for item in items if item.get("category") == category]
    if priority:
        items = [item for item in items if item.get("priority") == priority]
    if status:
        items = [item for item in items if item.get("status") == status]
    return items


def get_pathway(pathway_id: str) -> dict[str, Any] | None:
    """按 id 返回途径详情；不存在时返回 None。"""
    for item in dataset.load_catalog():
        if item["id"] == pathway_id:
            detail = dict(item)
            detail["citations"] = [
                {
                    "source_name": item["source_name"],
                    "source_url": item["source_url"],
                    "year": item["year"],
                }
            ]
            detail["evaluable"] = bool(item.get("rule_set"))
            return detail
    return None


# 途径 id → 专项计划 program 前缀。仅专项类途径有实施区域名单，
# 其余途径返回空列表并说明「本途径无实施区域概念」，不伪造区域。
REGION_PROGRAMS = {
    "national": "national",
    "college": "college",
    "local": "local",
}


def _program_of(pathway_id: str) -> str | None:
    for prefix, program in REGION_PROGRAMS.items():
        if pathway_id.startswith(prefix):
            return program
    return None


def regions_of(pathway_id: str, province: str = "") -> dict[str, Any]:
    """返回某途径的实施区域名单（契约 6.1 ``GET /api/pathways/{id}/regions``）。

    名单未核验（``verified=false`` 且 counties 为空）时 ``data_status`` 为
    ``schema_only``，如实说明「结构已就绪、名单待核验」，不返回可报考结论。
    """
    program = _program_of(pathway_id)
    if program is None:
        return {
            "pathway_id": pathway_id,
            "province": province or None,
            "data_status": "unavailable",
            "regions": [],
            "citations": [],
            "missing_rule_sets": [],
            "note": "本途径不设实施区域名单（区域限制仅适用于专项计划类途径）。",
        }

    matched = [
        item
        for item in dataset.load_regions()
        if item.get("program") == program and (not province or item.get("province") == province)
    ]
    citations: list[dict[str, Any]] = []
    regions: list[dict[str, Any]] = []
    pending = False
    for item in matched:
        citation = {
            "source_name": item["source_name"],
            "source_url": item["source_url"],
            "year": item["year"],
        }
        if citation not in citations:
            citations.append(citation)
        counties = list(item.get("counties") or [])
        if not counties:
            pending = True
        regions.append(
            {
                "province": item.get("province"),
                "program": item.get("program"),
                "program_name": item.get("program_name"),
                "scope": item.get("scope"),
                "verified": bool(item.get("verified")),
                "expected_count": item.get("expected_count"),
                "counties": counties,
                "definition": item.get("definition", ""),
                "citation": citation,
            }
        )

    if not matched:
        status = "unavailable"
        missing = ["pathway_region"]
    elif pending:
        status = "schema_only"
        missing = ["pathway_region"]
    else:
        status = "available"
        missing = []

    return {
        "pathway_id": pathway_id,
        "province": province or None,
        "data_status": status,
        "regions": regions,
        "citations": citations,
        "missing_rule_sets": missing,
    }
