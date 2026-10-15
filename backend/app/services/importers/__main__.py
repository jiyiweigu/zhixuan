"""一键导入入口。

    cd backend && .venv/Scripts/python.exe -m app.services.importers
    # 数据本体不在仓库里时指定根目录
    ZHIXUAN_DATA_ROOT=D:/桌面/zhixuan-local-data .venv/Scripts/python.exe -m app.services.importers

顺序即依赖顺序：``source`` 必须先落库，``pathway`` 又必须先于 ``pathway_region`` /
``pathway_eligibility``（两者有指向途径的外键）；``major`` 必须先于录取分的专业挂接
（``import_major_links`` 按专业名写 ``school_major_score.major_id``）。

退出码：字典类数据集（随仓库分发，缺了就是环境问题）缺失 → 1；
数据本体类（按需下载，缺了属正常）缺失 → 仅提示，不影响退出码。
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy.orm import Session

from app.services.importers import ImportReport, SourceRegistry, data_root
from app.services.importers.eligibility import import_eligibility
from app.services.importers.enrollment_rules import import_enrollment_rules
from app.services.importers.majors import import_majors
from app.services.importers.major_links import import_major_links
from app.services.importers.pathway_regions import import_pathway_regions
from app.services.importers.pathways import import_pathways
from app.services.importers.province_exam_rule import import_province_exam_rules
from app.services.importers.school_life import import_school_life
from app.services.importers.school_profiles import import_school_profiles
from app.services.importers.schools import import_schools
from app.services.importers.score_segment import import_score_segments
from app.services.importers.school_major_score import import_school_major_scores
from app.services.importers.sources import import_sources

# 随仓库分发的字典类数据集（缺失视为环境错误）
REQUIRED_DATASETS = {"source", "pathway", "pathway_region", "pathway_eligibility",
                     "province_exam_rule", "major"}


def run_all(session: Session, root: Path) -> list[ImportReport]:
    """按依赖顺序导入全部数据集，返回逐数据集报告。"""
    registry = SourceRegistry(session)
    registry.load_registry(root / "sources" / "source-table.json")

    reports: list[ImportReport] = [
        import_sources(session, root / "sources" / "source-table.json"),
        import_pathways(session, root / "dictionaries" / "pathways-26.json", registry),
        import_pathway_regions(session, root / "dictionaries" / "pathway-regions.json", registry),
        import_eligibility(
            session, root / "dictionaries" / "pathway-eligibility.json", registry
        ),
        import_province_exam_rules(
            session, root / "dictionaries" / "province-exam-rule.json", registry
        ),
        import_schools(session, root / "schools" / "schools_merged.json", registry),
        # 画像 / 生活信息 / 招生章程要点：均以 school 为前提（数据文件同为 ③ 的产出物）
        import_school_profiles(session, root / "schools" / "school_profile_rows.json", registry),
        import_school_life(session, root / "schools" / "school_life_rows.json", registry),
        import_enrollment_rules(
            session, root / "schools" / "enrollment_rule_rows.json", registry
        ),
        import_majors(session, root / "majors" / "majors.json", registry),
        import_score_segments(session, root / "score_segment", registry),
        import_school_major_scores(session, root / "school_major_score", registry),
        # 依赖 major 表：把录取分按专业名挂到专业库（整数外键）
        import_major_links(session, registry),
    ]

    if registry.unresolved:
        detail = "、".join(
            f"{key}×{count}" for key, count in sorted(registry.unresolved.items())
        )
        reports[0].note(f"未能解析的来源引用：{detail}")
    return reports


def main(argv: list[str] | None = None) -> int:
    from app.db.session import SessionLocal

    root = Path(argv[0]) if argv else data_root()
    print(f"数据根目录：{root}")
    if not root.is_dir():
        print(f"数据根目录不存在：{root}")
        return 1

    with SessionLocal() as session:
        reports = run_all(session, root)
        session.commit()

    problems = 0
    for report in reports:
        print("  " + report.describe())
        for note in report.notes:
            print(f"       · {note}")
        if report.missing_file and report.dataset in REQUIRED_DATASETS:
            print(f"       ✗ 必需数据集缺失：{report.missing_file}")
            problems += 1
        if report.accounted != report.read:
            print(f"       ✗ 行数对不上：读入 {report.read} 但只解释了 {report.accounted}")
            problems += 1

    print(f"\n合计新增 {sum(r.created for r in reports)} / 更新 {sum(r.updated for r in reports)}")
    if problems:
        print(f"存在 {problems} 个问题")
        return 1
    print("导入完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
