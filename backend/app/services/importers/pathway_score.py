"""升学途径参考分导入（``pathway_score``，产品书 7.2）。

数据文件：``data/output/pathway_score.json``（**顶层数组**，实测 10 行）
产出方：③ ``data/collectors/c_pathway_score.py``

业务键：``(pathway_id, school_id, province, year)``
—— 这是**当前表结构能表达的最大身份**，但小于 ③ 产出的真实粒度。

⚠️ 身份缺口：③ 按「专业组」发布，表里没有对应列
--------------------------------------------------
同一 ``(途径, 院校, 省, 年)`` 下，③ 还区分：

- ``subject_type``：历史类 / 物理类（老高考为文/理，新高考为 3+1+2 的选考方向）；
- ``group_code``：院校专业组代号（河南 2025 起为专业组志愿，301 / 302 组投档线不同）。

实测 10 行只对应 **4 个**身份组。「河南财经政法大学 · 国家专项计划 · 301 组」
历史类 579 分、物理类 567 分是两条不同事实，而 ``pathway_score`` 表
**没有** ``subject_type`` / ``group_code`` 列 —— 硬灌的后果是后者覆盖前者
（10 行变 4 行，且最终留下哪一行取决于文件行序），属静默数据丢失。

按铁律 3「宁可缺，不可猜」，同一身份组出现多行时**整组跳过**并上报
``identity_ambiguous_no_subject_type``，不任选一行、不取平均、不拿最高分充数。
解除条件只有一个：迁移给 ``pathway_score`` 补 ``subject_type``（及 ``group_code``），
补完本导入器会自动按 (…, subject_type, group_code) 分组，无需改其它逻辑。
这一条已列进交给队长的待办清单，属**结构裁决**，不在导入层单方面决定。

其它口径
--------
- ``pathway_name`` → ``pathway.id``：按 ``pathway.name`` 精确匹配（26 类字典同源）。
  匹配不到跳过并上报 ``unknown_pathway_name``——**不**新建途径行（途径是字典，
  只能由 ③ 的字典扩充）。
- ``school_name`` → ``school.id``：按名称精确匹配；匹配不到跳过并上报
  ``unknown_school_name``，不降级、不猜。
- ``min_score`` / ``min_rank`` 缺失留 ``NULL``（模型本就允许），不按位次反推分数。
- 行内 ``batch`` / ``group_name`` / ``max_score`` / ``admitted_num`` 等表里没有的列
  **不落库也不报错**（客观超出表结构，同 ``school_major_score`` 对多余列的处理）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base_data import School
from app.models.pathway import Pathway, PathwayScore
from app.services.importers import ImportReport, SourceRegistry, int_of, load_rows, text_of

# 表结构能表达的身份
Identity = tuple[str, int, str, int]


def import_pathway_scores(
    db: Session, path: Path, registry: SourceRegistry
) -> ImportReport:
    report = ImportReport(dataset="pathway_score")
    rows = load_rows(path)
    if rows is None:
        report.missing_file = str(path)
        return report

    unknown_pathways: dict[str, int] = {}
    unknown_schools: dict[str, int] = {}
    groups: dict[Identity, list[dict[str, Any]]] = {}

    # 第一遍：逐行解析身份（解析不到的行当场跳过，保证行数守恒）
    for row in rows:
        pathway_name = text_of(row, "pathway_name")
        school_name = text_of(row, "school_name")
        province = text_of(row, "province")
        year = int_of(row, "year")

        if not pathway_name or not school_name or not province or year is None:
            report.read += 1
            report.skip("missing_identity_field")
            continue

        pathway = db.scalar(select(Pathway).where(Pathway.name == pathway_name))
        if pathway is None:
            report.read += 1
            unknown_pathways[pathway_name] = unknown_pathways.get(pathway_name, 0) + 1
            report.skip("unknown_pathway_name")
            continue

        school = db.scalar(select(School).where(School.name == school_name))
        if school is None:
            report.read += 1
            unknown_schools[school_name] = unknown_schools.get(school_name, 0) + 1
            report.skip("unknown_school_name")
            continue

        groups.setdefault((pathway.id, school.id, province, year), []).append(row)

    # 第二遍：身份组唯一才落库，多行即整组跳过（见模块 docstring 的身份缺口）
    ambiguous_groups = 0
    for (pathway_id, school_id, province, year), members in sorted(groups.items()):
        if len(members) > 1:
            ambiguous_groups += 1
            for _ in members:
                report.read += 1
                report.skip("identity_ambiguous_no_subject_type")
            continue

        row = members[0]
        report.read += 1

        source = registry.resolve(row)
        if source is None:
            report.skip("unresolvable_source")
            continue

        min_score = int_of(row, "min_score")
        min_rank = int_of(row, "min_rank")

        existing = db.scalar(
            select(PathwayScore).where(
                PathwayScore.pathway_id == pathway_id,
                PathwayScore.school_id == school_id,
                PathwayScore.province == province,
                PathwayScore.year == year,
            )
        )

        if existing is None:
            db.add(
                PathwayScore(
                    pathway_id=pathway_id,
                    school_id=school_id,
                    province=province,
                    year=year,
                    min_score=min_score,
                    min_rank=min_rank,
                    source_id=source.id,
                )
            )
            report.created += 1
            continue

        changed = False
        if existing.min_score != min_score:
            existing.min_score = min_score
            changed = True
        if existing.min_rank != min_rank:
            existing.min_rank = min_rank
            changed = True
        if existing.source_id != source.id:
            existing.source_id = source.id
            changed = True

        if changed:
            report.updated += 1
        else:
            report.unchanged += 1

    db.flush()
    report.note(
        f"数据文件：{path}（身份 pathway_id + school_id + province + year）"
    )
    if ambiguous_groups:
        report.note(
            f"身份粒度不足：{ambiguous_groups} 个身份组各含多行（差异仅在 "
            "subject_type / group_code），整组跳过未落库 "
            f"{report.skip_reasons.get('identity_ambiguous_no_subject_type', 0)} 行 —— "
            "pathway_score 表缺 subject_type 列，补列后自动可分组，"
            "详见 PR 说明与待办清单（结构裁决）"
        )
    if unknown_pathways:
        detail = "、".join(f"{name}×{count}" for name, count in sorted(unknown_pathways.items()))
        report.note(f"途径字典未收录的名称：{detail}")
    if unknown_schools:
        detail = "、".join(f"{name}×{count}" for name, count in sorted(unknown_schools.items()))
        report.note(f"院校库未收录、无法挂接的校名：{detail}")
    return report
