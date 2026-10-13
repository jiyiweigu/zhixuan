"""演示数据标记。

契约（docs/api-contract.md）要求所有事实性数据必须携带来源三要素
source_name / source_url / year，缺一不得入库、不得展示。

真实数据管道接入前，各接口统一使用下面的演示来源；
前端据此把内容标注为"演示数据（非官方）"，不得当作政策或分数线展示。
"""

from __future__ import annotations

DEMO_SOURCE: dict[str, object] = {
    "source_name": "演示数据（非官方）",
    "source_url": "https://example.invalid/mock",
    "year": 2026,
}


def demo_citation() -> dict[str, object]:
    """返回一份独立的演示来源副本，避免调用方互相污染。"""
    return dict(DEMO_SOURCE)
