"""院校专业录取分导入（``school_major_score``）。

数据文件：``data/school_major_score/school_major_score_{year}_{省份}.json``（键 ``scores``）。
③ 首期可用 6 份（河南 / 江西 × 2022 / 2024 / 2025，共 **116,036 行**），
2023 两省整表不可用（河南院校字段全空、江西分数位次全空）。
数据本体不随仓库分发，``data/samples/school_major_score.json`` 是 ③ 专为建表联调准备的
12 行样本，含**两类边界**：2 行 ``school_id`` 空（院校改名）、2 行 ``subject_type`` 空（2024 整列缺失）。

``school_id`` 是**位置耦合**的整数，必须加防护
---------------------------------------------
实测确认（2026-10-13）：③ 的 ``school_id`` **等于** ``data/schools/schools_merged.json``
的 **1-based 行序号**——北京大学 51、清华大学 55、安徽财经大学 243，
与 ``data/samples/school.json`` 里带的 ``id`` 完全一致。

⇒ 它只在「院校库用同一份文件、同一顺序、零跳过地导入」时才正确。
一旦有院校行被跳过，后续 id 会整体错位，**116,036 行的院校归属会静默全错**。
本导入器加两道防护：

1. **建表侧**：``import_schools`` 直接采用 ③ 的 ``id`` 作主键（不再依赖自增顺序），
   任何一行被跳过都不会让后续 id 位移；
2. **消费侧**：``school_id`` 必须在 ``school`` 表存在，否则**跳过并上报**
   ``unknown_school_id``，绝不把未知 id 降级成 NULL——那等于把「错位」
   伪装成「客观缺失」，是最难发现的一类错误。

幂等靠「身份键 + 序数匹配」，不靠唯一键
-------------------------------------
表上没有天然唯一键：③ 的 ``major_id`` 首期恒空，同一院校同年同批次同专业组下
可能出现多行（样本里就有一例：243/河南/2025/本科批/物理类/560 分/101279 位次
出现两次，分别是 ``major_code=14`` 公共管理类与 ``major_code=12`` 国际商务）。

故按身份键 ``(school_id, province, year, batch, subject_type, group_code, major_code)``
分组，组内**按出现序数**与库中既有行一一对应：第 n 次出现的行对应组内第 n 行，
超出既有行数才新增。这样既可零丢失地保留同键多行，二次执行又必然 0 新增。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.base_data import Major, School, SchoolMajorScore
from app.models.pathway import Pathway
from app.services.importers import (
    ImportReport,
    SourceRegistry,
    int_of,
    load_dataset,
    rows_of,
    text_of,
)
from app.services.importers.vocab import province_name_of

_ROW_KEYS = ("scores", "records")

# 可被新行覆盖的字段（身份键字段与自增主键不在内）
_MUTABLE = (
    "major_id",
    "major_name",
    "min_score",
    "min_rank",
    "avg_score",
    "plan_count",
    "exam_system",
    "pathway_id",
)

_Identity = tuple[int | None, str, int, str, str, str, str]


def _identity_of(row: dict[str, Any]) -> _Identity | None:
    """抽身份键；省名 / 年份缺失或省名未收录时返回 None。"""
    province = province_name_of(text_of(row, "province"))
    year = int_of(row, "year")
    if province is None or year is None:
        return None
    return (
        int_of(row, "school_id"),
        province,
        year,
        text_of(row, "batch"),
        text_of(row, "subject_type"),
        text_of(row, "group_code"),
        text_of(row, "major_code"),
    )


def _identity_query(key: _Identity) -> Select[tuple[SchoolMajorScore]]:
    """身份键 → 查既有行的条件（``school_id`` 为空时必须用 IS NULL）。"""
    school_id, province, year, batch, subject_type, group_code, major_code = key
    conditions = [
        SchoolMajorScore.province == province,
        SchoolMajorScore.year == year,
        SchoolMajorScore.batch == batch,
        SchoolMajorScore.subject_type == subject_type,
        SchoolMajorScore.group_code == group_code,
        SchoolMajorScore.major_code == major_code,
    ]
    if school_id is None:
        conditions.append(SchoolMajorScore.school_id.is_(None))
    else:
        conditions.append(SchoolMajorScore.school_id == school_id)
    return select(SchoolMajorScore).where(*conditions).order_by(SchoolMajorScore.id)


def import_school_major_score_file(
    db: Session, path: Path, registry: SourceRegistry, report: ImportReport
) -> None:
    """导入单个录取分文件，结果累加进 ``report``。"""
    payload = load_dataset(path)
    if payload is None:
        report.missing_file = str(path)
        return

    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}

    rows: list[dict[str, Any]] = []
    for key in _ROW_KEYS:
        rows = rows_of(payload, key)
        if rows:
            break
    if not rows:
        report.note(f"{path.name}：无 {' / '.join(_ROW_KEYS)} 行")
        return

    # 身份键 → 该组的既有行（按 id 升序，保证跨次执行的序数对应稳定）
    buckets: dict[_Identity, list[SchoolMajorScore]] = {}
    cursor: dict[_Identity, int] = {}
    admit_count_carried = 0
    data_status_seen: set[str] = set()

    for row in rows:
        report.read += 1

        if text_of(row, "admit_count"):
            admit_count_carried += 1
        status = text_of(row, "data_status")
        if status:
            data_status_seen.add(status)

        identity = _identity_of(row)
        if identity is None:
            report.skip("missing_required_field")
            continue

        # ① 来源：行内三要素 → 行内 source_id 查来源表 → 数据集级 meta
        source = registry.resolve(row, meta)
        if source is None:
            report.skip("unresolvable_source")
            continue

        # ② 院校：位置 id 必须真实存在，未知一律跳过上报（绝不降级成 NULL）
        school_id = identity[0]
        if school_id is not None and db.get(School, school_id) is None:
            report.skip("unknown_school_id")
            continue

        major_id = int_of(row, "major_id")
        if major_id is not None and db.get(Major, major_id) is None:
            report.skip("unknown_major_id")
            continue

        pathway_id = text_of(row, "pathway_id") or None
        if pathway_id is not None and db.get(Pathway, pathway_id) is None:
            report.skip("unknown_pathway")
            continue

        values: dict[str, Any] = {
            "major_id": major_id,
            "major_name": text_of(row, "major_name"),
            "min_score": int_of(row, "min_score"),
            "min_rank": int_of(row, "min_rank"),
            "avg_score": int_of(row, "avg_score"),
            # ③ §2.4：admit_count（实际录取数）≠ plan_count（计划数），本表不混填，
            # 只读 plan_count，admit_count 仅作辅助统计不计入。
            "plan_count": int_of(row, "plan_count"),
            "exam_system": text_of(row, "exam_system"),
            "pathway_id": pathway_id,
        }

        bucket = buckets.get(identity)
        if bucket is None:
            bucket = list(db.scalars(_identity_query(identity)).all())
            buckets[identity] = bucket
            cursor[identity] = 0

        ordinal = cursor[identity]
        cursor[identity] = ordinal + 1
        target = bucket[ordinal] if ordinal < len(bucket) else None

        if target is None:
            entity = SchoolMajorScore(
                school_id=school_id,
                province=identity[1],
                year=identity[2],
                batch=identity[3],
                subject_type=identity[4],
                group_code=identity[5],
                major_code=identity[6],
                source_id=source.id,
                **values,
            )
            db.add(entity)
            # 入桶：同键的后续出现才能继续按序对应
            bucket.append(entity)
            report.created += 1
            continue

        changed = False
        if target.source_id != source.id:
            target.source_id = source.id
            changed = True
        for field in _MUTABLE:
            if getattr(target, field) != values[field]:
                setattr(target, field, values[field])
                changed = True
        if changed:
            report.updated += 1
        else:
            report.unchanged += 1

    db.flush()
    report.note(f"数据文件：{path.name}")
    if admit_count_carried:
        report.note(
            f"③ 携带 admit_count 的行 {admit_count_carried} 行——第 7 章无此列，未入库（待裁决）"
        )
    if data_status_seen:
        report.note(f"③ 的 data_status 取值：{'、'.join(sorted(data_status_seen))}")


def import_school_major_scores(
    db: Session, directory: Path, registry: SourceRegistry
) -> ImportReport:
    """导入目录下全部 ``school_major_score*.json``（按文件名排序，结果可复现）。"""
    report = ImportReport(dataset="school_major_score")
    if not directory.is_dir():
        report.missing_file = str(directory)
        return report

    files = sorted(directory.glob("school_major_score*.json"))
    if not files:
        report.missing_file = str(directory / "school_major_score*.json")
        return report

    for path in files:
        import_school_major_score_file(db, path, registry, report)

    report.note(f"数据文件：{len(files)} 份（{'、'.join(p.name for p in files)}）")
    return report
