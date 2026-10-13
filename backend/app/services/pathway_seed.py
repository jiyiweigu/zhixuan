"""途径字典入库（tasks.md 8.6 的本地种子）。

背景：用户端 ``GET /api/pathways`` 目前仍读 ``app/data/pathways/catalog.json``
（app/services/pathways.py），而管理端途径维护写的是库表 ``pathway``（产品书 7.2）。
为让管理端页面一开就有内容、且规则能引用真实的 ``pathway_id``，本模块把该文件
幂等导入 ``pathway`` 表。

字段映射（文件 → 表）：
    audience        → target_group
    key_dates[]     → apply_time（分号连接）
    condition_summary → description
    status「数据规划中」→ data_status=planned，其余（可查询 / 可判定）→ ready

用法：
    cd backend && .venv/Scripts/python.exe -m app.services.pathway_seed

注：用户端是否改为读库由队长决定（已列入 PR 待确认事项），本模块不改动用户端行为。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core import dataset
from app.models.pathway import Pathway
from app.services import source_guard

STATUS_PLANNED = "数据规划中"


def _data_status(status: str) -> str:
    """「数据规划中」→ planned；可查询 / 可判定 → ready。"""
    return "planned" if str(status or "").strip() == STATUS_PLANNED else "ready"


def seed_pathways(db: Session) -> dict[str, int]:
    """把 catalog.json 幂等写入 pathway 表，返回新增行数。"""
    created = 0
    for item in dataset.load_catalog():
        pathway_id = str(item["id"])
        if db.get(Pathway, pathway_id) is not None:
            continue
        source_guard.require_source(
            item.get("source_name"), item.get("source_url"), item.get("year")
        )
        source = source_guard.ensure_source(db, _SourceStub(item))
        db.add(
            Pathway(
                id=pathway_id,
                name=str(item.get("name") or pathway_id),
                category=str(item.get("category") or ""),
                batch=str(item.get("batch") or ""),
                target_group=str(item.get("audience") or ""),
                apply_time="；".join(str(day) for day in (item.get("key_dates") or [])),
                description=str(item.get("condition_summary") or ""),
                priority=str(item.get("priority") or "P2"),
                data_status=_data_status(item.get("status")),
                year=int(item.get("year") or 0),
                source_id=source.id,
            )
        )
        created += 1
    db.commit()
    return {"pathway": created}


class _SourceStub:
    """把字典项适配成 ``ensure_source`` 需要的来源三要素结构。"""

    def __init__(self, item: dict[str, Any]) -> None:
        self.source_name = str(item.get("source_name") or "")
        self.source_url = str(item.get("source_url") or "")
        self.year = int(item.get("year") or 0)
        self.source_type: str | None = None


def main() -> int:
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        created = seed_pathways(db)
    print(f"途径字典入库完成：新增 pathway {created['pathway']} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
