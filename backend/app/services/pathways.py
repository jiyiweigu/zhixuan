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
