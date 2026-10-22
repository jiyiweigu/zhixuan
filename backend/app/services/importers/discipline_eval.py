"""学科评估导入（``discipline_eval``，tasks.md 2.5）。

数据文件：``data/output/discipline_eval.json``（**顶层数组**，实测 409 行）
产出方：③ ``data/collectors/c_discipline.py``

业务键：``(school_id, discipline_name, round)``
----------------------------------------------
一份数据内实测无重复；但同一学科在不同轮次（第四轮 / 第五轮）是不同事实，
故 ``round`` 必须进身份——合并会把两轮等级压成一行。

口径：③ 的产出混了两件不同的事，本导入器只落其中一件
--------------------------------------------------
``c_discipline.py`` 的 docstring 写明「两源合并后按 (school_name, discipline_name,
round) 去重」，于是同一份文件里装着：

1. **教育部学位中心第四轮学科评估结果**（离线种子，20 行）——带 ``grade``
   （``A+`` / ``A-`` / ``B+`` …），``year`` 为公布年份 2017，是真正的评估结论；
2. **掌上高考院校库「重点学科」字段**（在线增量，389 行）——**没有等级**
   （``grade`` 全空），``year`` 是抓取年份 2026，却被统一打上 ``round = "第四轮"``。

两者语义不同：「获评 B+」是评估结论，「是重点学科」只是收录关系。
若把后者按 ``round=第四轮 / grade=""`` 写进库，接口就会对用户显示
「第四轮学科评估：—」，属于**事实性错误**，还会污染按 ``grade`` 排序的学科强弱维度。

故本导入器只落**带等级的评估结果**；无等级的行按 ``grade_absent_not_evaluation``
跳过并计入报告，等 ③ / 队长裁决走哪条路：

- 单列数据集（如 ``school_key_discipline``，一校多学科，不含等级）；或
- 契约给 ``round`` 增加「重点学科」枚举，明确它不是评估轮次。

这正是铁律 3「口径歧义一律跳过并上报，不自行裁剪或补全」的适用场景，
**不是**导入器能力不足：去掉那个 ``if not grade`` 就能全量落库，只是会写脏语义。

其余口径
--------
- ``school_name`` → ``school.id``：按名称精确匹配（院校业务键是 ``name``，
  与 ``importers/schools.py`` 一致）；匹配不到跳过并上报 ``unknown_school_name``，
  并把待补的校名计进 ``notes``——**不**按模糊匹配猜，也**不**降级成自建院校行。
- ``round`` 缺省**不推断**：缺失即 ``missing_round`` 跳过（不默认成「第四轮」）。
- 来源三要素由行内自带（``source_name`` / ``source_url`` / ``year``）解析；
  缺失仍走 ``unresolvable_source``。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base_data import DisciplineEval, School
from app.services.importers import ImportReport, SourceRegistry, load_rows, text_of


def import_discipline_evals(
    db: Session, path: Path, registry: SourceRegistry
) -> ImportReport:
    report = ImportReport(dataset="discipline_eval")
    rows = load_rows(path)
    if rows is None:
        report.missing_file = str(path)
        return report

    unknown_schools: dict[str, int] = {}
    graded = 0

    for row in rows:
        report.read += 1

        school_name = text_of(row, "school_name")
        discipline = text_of(row, "discipline_name")
        grade = text_of(row, "grade")
        round_name = text_of(row, "round")

        if not school_name or not discipline:
            report.skip("missing_school_or_discipline")
            continue
        if not round_name:
            report.skip("missing_round")
            continue
        # 无等级 = 「重点学科」收录关系，不是评估结论（见模块 docstring）
        if not grade:
            report.skip("grade_absent_not_evaluation")
            continue

        school = db.scalar(select(School).where(School.name == school_name))
        if school is None:
            unknown_schools[school_name] = unknown_schools.get(school_name, 0) + 1
            report.skip("unknown_school_name")
            continue

        source = registry.resolve(row)
        if source is None:
            report.skip("unresolvable_source")
            continue

        graded += 1
        existing = db.scalar(
            select(DisciplineEval).where(
                DisciplineEval.school_id == school.id,
                DisciplineEval.discipline_name == discipline,
                DisciplineEval.round == round_name,
            )
        )

        if existing is None:
            db.add(
                DisciplineEval(
                    school_id=school.id,
                    discipline_name=discipline,
                    grade=grade,
                    round=round_name,
                    source_id=source.id,
                )
            )
            report.created += 1
            continue

        changed = False
        if existing.grade != grade:
            existing.grade = grade
            changed = True
        if existing.source_id != source.id:
            existing.source_id = source.id
            changed = True

        if changed:
            report.updated += 1
        else:
            report.unchanged += 1

    db.flush()
    report.note(f"数据文件：{path}（业务键 school_id + discipline_name + round）")
    report.note(
        f"仅落带等级的评估结果 {graded} 行；"
        f"跳过 {report.skip_reasons.get('grade_absent_not_evaluation', 0)} 行"
        "「重点学科」收录关系（无等级、round 却被标为第四轮），待 ③/队长裁决是否单列数据集"
        "（见 PR 说明）"
    )
    if unknown_schools:
        detail = "、".join(f"{name}×{count}" for name, count in sorted(unknown_schools.items()))
        report.note(f"院校库未收录、无法挂接的校名：{detail}")
    return report
