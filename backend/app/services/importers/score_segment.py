"""一分一段导入（``score_segment``）。

数据文件：``data/score_segment/score_segment_*.json``（键 ``segments``），一次可导多份：
- 2026 历史类 / 物理类（③ 的考试院扫描件 OCR 产物，454 / 462 行）；
- 2022–2025 河南 / 江西（渠道数据集产物，共约 11,694 行）。

业务键：``(province, year, subject_type, batch, score)``。

溯源是**两套写法**，本导入器都支持（见 ``SourceRegistry.resolve``）：
2022–2025 的行内带 ``source_id: SRC-GAOAKAO-COMPASS``（但 ``source_url`` 故意留空），
2026 的把三要素放在文件级 ``meta``，行内只有 province/year/subject_type/score。

⚠️ 2026 的 ``meta.source_id``（``SRC-HENAN-SCORE-SEG-2026``）**未登记在
``source-table.json`` 里**——③ 用了但没登记。本导入器按 ``meta`` 的三要素落库
（可追溯，不编造），同时把该缺口写进报告。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base_data import ScoreSegment
from app.services.importers import (
    ImportReport,
    SourceRegistry,
    int_of,
    load_dataset,
    rows_of,
    text_of,
)
from app.services.importers.vocab import province_name_of


def import_score_segment_file(
    db: Session, path: Path, registry: SourceRegistry, report: ImportReport
) -> None:
    """导入单个一分一段文件，结果累加进 ``report``。"""
    payload = load_dataset(path)
    if payload is None:
        report.missing_file = str(path)
        return

    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}

    rows = rows_of(payload, "segments")
    if not rows:
        report.note(f"{path.name}：无 segments 行")
        return

    for row in rows:
        report.read += 1

        province = province_name_of(text_of(row, "province"))
        year = int_of(row, "year")
        subject_type = text_of(row, "subject_type")
        score = int_of(row, "score")
        cumulative_rank = int_of(row, "cumulative_rank")

        if province is None or not subject_type or score is None or cumulative_rank is None:
            report.skip("missing_required_field")
            continue
        if year is None:
            report.skip("missing_year")
            continue

        source = registry.resolve(row, meta)
        if source is None:
            report.skip("unresolvable_source")
            continue

        batch = text_of(row, "batch")

        existing = db.scalar(
            select(ScoreSegment).where(
                ScoreSegment.province == province,
                ScoreSegment.year == year,
                ScoreSegment.subject_type == subject_type,
                ScoreSegment.batch == batch,
                ScoreSegment.score == score,
            )
        )

        if existing is None:
            db.add(
                ScoreSegment(
                    province=province,
                    year=year,
                    subject_type=subject_type,
                    batch=batch,
                    score=score,
                    cumulative_rank=cumulative_rank,
                    source_id=source.id,
                )
            )
            report.created += 1
            continue

        if existing.cumulative_rank != cumulative_rank or existing.source_id != source.id:
            existing.cumulative_rank = cumulative_rank
            existing.source_id = source.id
            report.updated += 1
        else:
            report.unchanged += 1


def import_score_segments(
    db: Session, directory: Path, registry: SourceRegistry
) -> ImportReport:
    """导入目录下全部 ``score_segment_*.json``（按文件名排序，结果可复现）。"""
    report = ImportReport(dataset="score_segment")
    if not directory.is_dir():
        report.missing_file = str(directory)
        return report

    files = sorted(directory.glob("score_segment*.json"))
    if not files:
        report.missing_file = str(directory / "score_segment*.json")
        return report

    for path in files:
        import_score_segment_file(db, path, registry, report)

    db.flush()
    report.note(f"数据文件：{len(files)} 份（{'、'.join(p.name for p in files)}）")
    return report
