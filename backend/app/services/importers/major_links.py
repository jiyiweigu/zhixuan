"""录取分 → 专业库挂接（``school_major_score.major_id`` 回填）。

为什么不复用 ``data/scripts/backfill_major_id.py``
--------------------------------------------------
③ 的那份脚本是把 ``major_id`` 回填进 **JSON 文件**，且约定取值为**专业代码字符串**
（6/7 位国标码，专业类取 4 位类码）；库表 ``school_major_score.major_id`` 是**指向
``major.id`` 的整数外键**，两者不同源。故库侧按同一套匹配口径重新实现：
命中即写整数 ``major.id``，未命中原样留 NULL。

匹配口径（与 ③ 完全一致，宁可缺不可猜）
--------------------------------------
1. **精确匹配**：``major_name`` 与 ``major.name`` 全等 → 命中（专业类行也算命中，按类招生）；
2. **零歧义归一后匹配**：仅去空白/换行、全角括号转半角；
3. **不做**同义词推断、不猜错字、不把「试验班 / 职业本科专业」硬挂到相近专业上；
4. 未命中 → ``major_id`` 保持 NULL，计入 ``unmatched_major_name``，原因见报告。

幂等：只填空值，已挂接且仍存在于 ``major`` 表的行计入 ``unchanged``（不重复写、不覆盖）。
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base_data import Major, SchoolMajorScore
from app.services.importers import ImportReport, SourceRegistry

DATASET = "school_major_score.major_id"


def _norm(value: str) -> str:
    """零歧义归一：去空白/换行、全角括号转半角（不涉及语义）。"""
    text = re.sub(r"[\s\u3000]+", "", str(value or ""))
    return text.replace("（", "(").replace("）", ")")


def import_major_links(db: Session, registry: SourceRegistry | None = None) -> ImportReport:
    """把 ``school_major_score.major_id`` 按专业名挂到 ``major`` 表（整数 id）。"""
    report = ImportReport(dataset=DATASET)

    index: dict[str, tuple[int, bool]] = {}
    for major_id, name, is_category in db.execute(
        select(Major.id, Major.name, Major.is_category)
    ).all():
        index.setdefault(str(name).strip(), (int(major_id), bool(is_category)))
    if not index:
        report.missing_file = "major 表为空（需先导入 data/majors/majors.json）"
        return report
    normalized = {_norm(key): value for key, value in index.items()}

    known_ids = {major_id for major_id, _ in index.values()}
    matched_category = 0
    unmatched_top: dict[str, int] = {}

    rows = db.execute(
        select(SchoolMajorScore.id, SchoolMajorScore.major_name, SchoolMajorScore.major_id)
    ).all()
    for row_id, major_name, current_id in rows:
        report.read += 1

        if current_id is not None:
            if int(current_id) in known_ids:
                report.unchanged += 1
            else:
                report.skip("stale_major_id")
            continue

        raw = str(major_name or "").strip()
        if not raw:
            report.skip("blank_major_name")
            continue

        hit = index.get(raw) or normalized.get(_norm(raw))
        if hit is None:
            report.skip("unmatched_major_name")
            unmatched_top[raw] = unmatched_top.get(raw, 0) + 1
            continue

        major_id, is_category = hit
        db.execute(
            SchoolMajorScore.__table__.update()
            .where(SchoolMajorScore.id == row_id)
            .values(major_id=major_id)
        )
        report.updated += 1
        if is_category:
            matched_category += 1

    db.flush()
    report.note(
        f"匹配口径：精确 → 零歧义归一（不推断同义词）；命中的专业类行 {matched_category} 行"
        "（按类招生，非具体专业）"
    )
    if unmatched_top:
        top = "、".join(
            f"{name}×{count}"
            for name, count in sorted(unmatched_top.items(), key=lambda kv: -kv[1])[:5]
        )
        report.note(
            f"未匹配 {sum(unmatched_top.values())} 行保持 major_id=NULL（试验班 / 职业本科 / "
            f"院校自设专业等，属客观缺失）：出现最多的为 {top}"
        )
    return report
