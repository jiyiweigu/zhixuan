"""专业基础库导入（``major``，845 个专业 + 93 个专业类 = **938 行**）。

兼容两种数据文件形态（同一张表、两代数据集）：

**① 合并数据集（装载链路的主源）** ``merged/major.json``：键 ``records``，
行自带 ``id``（合并脚本显式分配：专业 1..845、专业类 846..938）与 ``source_id``。
``school_major_score.major_id`` 直接引用这套 id，故此时必须**显式落 id**——与 ``school``
同理，否则一旦有行被跳过，自增主键整体错位，11 万行引用会静默全错（最难发现的一类错误）。

**② 原始专业库（随仓库分发）** ``data/majors/majors.json``：键 ``classes`` / ``majors``
（无 id）；以 ``code`` 为幂等键落库（自增分配），来源从文件级 ``meta`` 三要素解析。

两态共用规则
------------
- ``code`` 幂等 + ``name`` 防重：同名不同码 → 跳过上报，不覆盖既有行；
- ``category`` 存**学科门类**（与 ``/api/majors?category=`` 的精确匹配语义一致）；
- 93 个专业类作为 ``is_category=True`` 的行一并落库——录取分里「按类招生」的条目
  就是它们；专业 → 专业类的从属关系由 ``code`` 前 4 位表达（``080901`` → ``0809``），
  不额外落列；
- 行级来源优先、回退文件级 ``meta`` 三要素；缺来源的行跳过上报（三要素红线）。

未落库的字段（如实上报，不静默）
--------------------------------
- ``is_special``（特设）/ ``is_state_controlled``（国控）/ ``code_len`` / ``code_type``：
  ``major`` 表无对应列，仅在报告中说明；
- 12 个学科门类本身不是可填报条目，不入库，仅用于给专业打 ``category``；
- 合并数据的 ``first_class``（专业类名）：``major.first_class`` 的语义是
  「一流本科专业建设点」，两者不是一回事，不落列（归属关系用 code 前 4 位表达）。

⚠️ **切换数据源（①↔②）时应清库重装**：两态的 id 分配顺序不同（②按 classes→majors
自增，①按专业→专业类显式），混装会令下游 ``major_id`` 引用错位。混装时的 id 冲突
会被检测并计数上报（``id_conflicts``），不会静默覆盖。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base_data import Major
from app.services.importers import (
    ImportReport,
    SourceRegistry,
    int_of,
    load_dataset,
    rows_of,
    text_of,
)

# 可被数据文件覆盖的字段（幂等更新白名单）。
# 注意：不含 ``id``（幂等键）、不含 ``first_class``（语义见模块 docstring）。
_WRITABLE = ("name", "code", "category", "degree", "intro")


def _row_pairs(payload: dict[str, Any]) -> list[tuple[dict[str, Any], bool]]:
    """返回 ``[(行, 是否专业类)]``（稳定顺序，便于复核）。

    合并数据集（``records``）按文件顺序；原始库 ``classes`` 在前、``majors`` 在后。
    """
    merged = rows_of(payload, "records")
    if merged:
        return [(dict(row), bool(row.get("is_category"))) for row in merged]

    pairs: list[tuple[dict[str, Any], bool]] = []
    for row in rows_of(payload, "classes"):
        pairs.append(({**row, "name": row.get("class_name"), "code": row.get("class_code")}, True))
    for row in rows_of(payload, "majors"):
        pairs.append((dict(row), False))
    return pairs


def import_majors(db: Session, path: Path, registry: SourceRegistry) -> ImportReport:
    report = ImportReport(dataset="major")
    payload = load_dataset(path)
    if payload is None:
        report.missing_file = str(path)
        return report

    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else None

    special = 0
    controlled = 0
    classes = 0
    explicit_ids = 0
    id_conflicts = 0
    for row, is_class in _row_pairs(payload):
        report.read += 1

        name = text_of(row, "name") or text_of(row, "class_name")
        code = text_of(row, "code") or text_of(row, "class_code")
        if not name or not code:
            report.skip("missing_name_or_code")
            continue

        category = text_of(row, "category") or text_of(row, "menlei")
        if not category:
            # category 是检索的精确匹配键，缺门类会让该行筛不出来 → 跳过并上报
            report.skip("missing_category")
            continue

        # 来源随记录登记（major 属基础字典，表内无 source_id 列）；
        # 行级来源优先，回退文件级 meta 三要素
        if registry.resolve(row, meta) is None:
            report.skip("unresolvable_source")
            continue

        if row.get("is_special"):
            special += 1
        if row.get("is_state_controlled"):
            controlled += 1
        if is_class:
            classes += 1

        values = {
            "name": name,
            "code": code,
            "category": category,
            "degree": text_of(row, "degree") or text_of(row, "degree_note"),
            "intro": text_of(row, "intro"),
        }

        existing = db.scalar(select(Major).where(Major.code == code))
        if existing is None:
            same_name = db.scalar(select(Major).where(Major.name == name))
            if same_name is not None:
                # 同名不同码：数据自相矛盾，跳过上报，不覆盖既有行
                report.skip("name_conflict")
                continue
            entity = Major(**values, is_category=is_class)
            rid = int_of(row, "id")
            if rid is not None and db.get(Major, rid) is None:
                entity.id = rid  # 显式落 id：下游 major_id 引用按此对齐
                explicit_ids += 1
            elif rid is not None:
                id_conflicts += 1  # id 已被占用（跨数据源混装），保留既有行、如实上报
            db.add(entity)
            report.created += 1
            continue

        changed = False
        for field in _WRITABLE:
            value = values[field]
            # 已落库的画像类补充（如 intro / first_class）不因本文件缺列而被清空
            if value and getattr(existing, field) != value:
                setattr(existing, field, value)
                changed = True
        if bool(existing.is_category) != is_class:
            existing.is_category = is_class
            changed = True

        if changed:
            report.updated += 1
        else:
            report.unchanged += 1

    db.flush()
    report.note(f"数据文件：{path}（业务键 code；专业类 {classes} 行 is_category=True）")
    report.note("category 存学科门类；专业与专业类的从属关系由 code 前 4 位表达")
    if explicit_ids:
        report.note(f"显式落 id {explicit_ids} 行（合并数据集格式；下游 major_id 直接引用）")
    if id_conflicts:
        report.note(
            f"⚠ {id_conflicts} 行的显式 id 已被占用（疑似跨数据源混装），"
            "已保留既有行、未覆盖——如属数据源切换请清库重装"
        )
    if special or controlled:
        report.note(
            f"is_special（特设）{special} 行、is_state_controlled（国控）{controlled} 行："
            "major 表无对应列，未落库（如实登记，待裁决是否加列）"
        )
    return report
