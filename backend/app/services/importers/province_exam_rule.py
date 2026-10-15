"""省份志愿模式模板导入（``province_exam_rule``，闸门 1）。

数据文件：``data/dictionaries/province-exam-rule.json``（7 条）
业务键：``(province_code, year, batch_code, exam_type)``——契约 8.7 的唯一键，
模型侧由 ``ix_province_exam_rule_lookup`` 唯一索引保证。

三处必须在导入时收敛（契约 8.7 明确要求，见迁移 0007 的文档字符串）：

1. ``province_code``：③ 在字典里写两位（``41``），在样本包里写六位（``410000``），
   统一归一到两位。
2. ``category_group`` → ``exam_type``：数据源列名必须映射为契约枚举
   （普通 / 艺术 / 体育）。``艺术类 / 体育类`` 一行覆盖两类，唯一键无法承载 →
   归一失败，跳过并上报，**不拆行也不猜**。
3. ``batch`` 只作展示：唯一键用机器键 ``batch_code``，河南「普通本科批」与
   江西「本科批次」经 ``batch_code`` 归一后不再区分。

``data_status``（含 ``schema_only``）是规则可用性的唯一来源，
本导入器把它写进 ``rule_dataset_status``，供 8.1 与闸门判定读取——
``schema_only`` 的规则**禁止**用于实际志愿计算（须返回 3001）。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.constraints import ProvinceExamRule, RuleDatasetStatus
from app.models.constants import (
    BATCH_DISPLAY_UG,
    DATASET_PROVINCE_EXAM_RULE,
    EXAM_MODE_GROUP,
)
from app.services.importers import (
    ImportReport,
    SourceRegistry,
    bool_of,
    int_of,
    load_dataset,
    rows_of,
    text_of,
)
from app.services.importers.vocab import (
    data_status_of,
    exam_type_of,
    province_code_of,
    province_name_of,
)


def _mutex_of(row: dict) -> dict | list:
    value = row.get("mutex_groups")
    if isinstance(value, (dict, list)):
        return value
    return {}


def import_province_exam_rules(
    db: Session, path: Path, registry: SourceRegistry
) -> ImportReport:
    report = ImportReport(dataset="province_exam_rule")
    payload = load_dataset(path)
    if payload is None:
        report.missing_file = str(path)
        return report

    for row in rows_of(payload, "rules"):
        report.read += 1

        province_code = province_code_of(text_of(row, "province_code"))
        province = province_name_of(text_of(row, "province"))
        year = int_of(row, "year")
        batch_code = text_of(row, "batch_code")

        # 数据源列名为 category_group；兼容已归一为 exam_type 的行
        raw_exam_type = text_of(row, "exam_type") or text_of(row, "category_group")
        exam_type = exam_type_of(raw_exam_type)

        if province_code is None or province is None:
            report.skip("province_not_in_vocabulary")
            continue
        if year is None:
            report.skip("missing_year")
            continue
        if not batch_code:
            report.skip("missing_batch_code")
            continue
        if exam_type is None:
            # 含「艺术类 / 体育类」这类一行两类
            report.skip("exam_type_not_in_vocabulary")
            continue

        source = registry.resolve(row)
        if source is None:
            report.skip("unresolvable_source")
            continue

        status = data_status_of(text_of(row, "data_status"))
        if status is None:
            report.skip("data_status_not_in_vocabulary")
            continue

        existing = db.scalar(
            select(ProvinceExamRule).where(
                ProvinceExamRule.province_code == province_code,
                ProvinceExamRule.year == year,
                ProvinceExamRule.batch_code == batch_code,
                ProvinceExamRule.exam_type == exam_type,
            )
        )

        values = {
            "province": province,
            "batch": text_of(row, "batch") or BATCH_DISPLAY_UG,
            "mode": text_of(row, "mode") or EXAM_MODE_GROUP,
            "volunteer_count": int_of(row, "volunteer_count") or 0,
            "majors_per_group": int_of(row, "majors_per_group"),
            "has_adjust": bool_of(row, "has_adjust"),
            "admit_method": text_of(row, "admit_method") or "parallel",
            "ratio": text_of(row, "ratio") or "1:1",
            "tie_rule": text_of(row, "tie_rule"),
            "mutex_groups": _mutex_of(row),
            "collect_count": int_of(row, "collect_count"),
            "source_id": source.id,
        }

        if existing is None:
            db.add(
                ProvinceExamRule(
                    province_code=province_code,
                    year=year,
                    batch_code=batch_code,
                    exam_type=exam_type,
                    **values,
                )
            )
            report.created += 1
        else:
            changed = False
            for field, value in values.items():
                if getattr(existing, field) != value:
                    setattr(existing, field, value)
                    changed = True
            if changed:
                report.updated += 1
            else:
                report.unchanged += 1

        _upsert_dataset_status(db, province_code, year, batch_code, exam_type, status, row)

    db.flush()
    report.note(f"数据文件：{path}")
    report.note("data_status 已同步写入 rule_dataset_status（schema_only 不得用于志愿计算）")
    return report


def _upsert_dataset_status(
    db: Session,
    province_code: str,
    year: int,
    batch_code: str,
    exam_type: str,
    status: str,
    row: dict,
) -> None:
    """把该规则集的 data_status 写入 ``rule_dataset_status``（幂等）。"""
    existing = db.scalar(
        select(RuleDatasetStatus).where(
            RuleDatasetStatus.province_code == province_code,
            RuleDatasetStatus.year == year,
            RuleDatasetStatus.batch_code == batch_code,
            RuleDatasetStatus.exam_type == exam_type,
            RuleDatasetStatus.dataset == DATASET_PROVINCE_EXAM_RULE,
        )
    )
    note = text_of(row, "note") or text_of(row, "change_2026")
    if existing is None:
        db.add(
            RuleDatasetStatus(
                province_code=province_code,
                year=year,
                batch_code=batch_code,
                exam_type=exam_type,
                dataset=DATASET_PROVINCE_EXAM_RULE,
                status=status,
                note=note,
            )
        )
        return
    if existing.status != status:
        existing.status = status
    if note and existing.note != note:
        existing.note = note
