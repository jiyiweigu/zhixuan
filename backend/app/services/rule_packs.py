"""规则导入包落库 CLI（选科要求 / 体检限制 → 契约 8.8 导入通道）。

    cd backend
    python -m app.services.rule_packs --subject-dir  ../data/staged/subject-requirement-import
    python -m app.services.rule_packs --physical-dir ../data/staged/physical-restriction-import

**口径升级时必须 ``--reset-subject`` / ``--reset-physical``**：导入包一旦重新生成
（如逻辑键加入批次/首选科目、列表值变化），旧行与新包按新键并不冲突，直接导入会
与新包混存 → 闸门②的变体选择被污染。重置会先清空该表再逐包导入，保证"库里 =
当前包"。

落库一律走 ``rule_admin.import_rule_dataset``（与 ``POST /api/admin/rule-datasets/import``
同一服务路径），CLI 不复刻任何校验逻辑。幂等语义：包内任一行逻辑键已在库 ⇒ 整批
拒绝（服务层行为），CLI 将该情形记为 ``skip``（整批事务 ⇒ 全在或全不在）。

退出码：0 = 全部落库且行数与包内条目逐一相符；1 = 存在失败/数字不符；2 = 环境问题
（缺管理员、缺目录等）。中文输出建议 ``PYTHONIOENCODING=utf-8``。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select

from app.core.response import BizError
from app.db.session import SessionLocal
from app.models.constants import (
    DATASET_PHYSICAL_RESTRICTION,
    DATASET_SUBJECT_REQUIREMENT,
)
from app.models.constraints import PhysicalRestriction, RuleDatasetStatus, SubjectRequirement
from app.models.knowledge import AdminUser
from app.schemas.admin import RuleDatasetImportRequest
from app.services import rule_admin

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SUBJECT_DIR = ROOT / "data" / "staged" / "subject-requirement-import"
DEFAULT_PHYSICAL_DIR = ROOT / "data" / "staged" / "physical-restriction-import"

_MODEL_BY_DATASET = {
    DATASET_SUBJECT_REQUIREMENT: SubjectRequirement,
    DATASET_PHYSICAL_RESTRICTION: PhysicalRestriction,
}


def _load_pack(path: Path) -> RuleDatasetImportRequest:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return RuleDatasetImportRequest(
        dataset=raw["dataset"],
        province_code=str(raw.get("province_code") or ""),
        year=int(raw.get("year") or 0),
        batch_code=str(raw.get("batch_code") or ""),
        exam_type=str(raw.get("exam_type") or "普通"),
        items=list(raw.get("items") or []),
    )


def _default_admin(db) -> AdminUser | None:
    return db.scalars(select(AdminUser).order_by(AdminUser.id)).first()


def _reset_dataset(db, dataset: str) -> int:
    model = _MODEL_BY_DATASET[dataset]
    removed = int(db.execute(delete(model)).rowcount or 0)
    db.commit()
    return removed


def _import_pack(db, payload: RuleDatasetImportRequest, admin: AdminUser) -> dict[str, Any]:
    """导入单包；"逻辑键已存在" 记为 skip（幂等），其余异常如实抛出。"""
    try:
        result = rule_admin.import_rule_dataset(db, payload, admin, client_ip="cli:rule_packs")
        return {"action": "import", "created": int(result.get("created") or 0)}
    except BizError as exc:  # noqa: PERF203
        if "逻辑键已存在" in str(exc.message):
            return {"action": "skip", "reason": str(exc.message)[:160]}
        raise


def _import_dir(db, directory: Path, admin: AdminUser, *, reset: bool) -> dict[str, Any]:
    files = sorted(directory.glob("part-*.json"))
    if not files:
        print(f"[rule_packs] 目录无 part-*.json：{directory}")
        raise SystemExit(2)
    dataset = _load_pack(files[0]).dataset
    report: dict[str, Any] = {"dir": str(directory), "dataset": dataset, "packs": []}
    if reset:
        removed = _reset_dataset(db, dataset)
        report["reset_removed"] = removed
        print(f"[rule_packs] {dataset}: 重置清空 {removed} 行")
    expected: dict[tuple[str, int], int] = defaultdict(int)
    for path in files:
        payload = _load_pack(path)
        if payload.dataset != dataset:
            print(f"[rule_packs] {path.name} 数据集不一致：{payload.dataset} != {dataset}")
            raise SystemExit(2)
        key = (payload.province_code, payload.year)
        expected[key] += len(payload.items)
        outcome = _import_pack(db, payload, admin)
        outcome.update({"file": path.name, "province_code": payload.province_code,
                        "year": payload.year, "items": len(payload.items)})
        report["packs"].append(outcome)
        print(f"[rule_packs] {path.name}: {outcome['action']} items={len(payload.items)}"
              f"{' created=' + str(outcome['created']) if outcome['action'] == 'import' else ' by=' + outcome['reason']}")
    report["expected_by_province_year"] = {f"{k[0]}-{k[1]}": v for k, v in sorted(expected.items())}
    return report


def _summarize(db, dataset: str, expected: dict[str, int]) -> dict[str, Any]:
    model = _MODEL_BY_DATASET[dataset]
    rows = db.execute(
        select(model.province_code, model.year, func.count()).group_by(
            model.province_code, model.year
        )
    ).all()
    actual = {f"{prov}-{year}": int(count) for prov, year, count in rows}
    mismatches = {
        key: {"expected": expect, "actual": actual.get(key, 0)}
        for key, expect in expected.items()
        if actual.get(key, 0) != expect
    }
    extras = {key: value for key, value in actual.items() if key not in expected}
    statuses = [
        {
            "dataset": row.dataset, "province_code": row.province_code, "year": row.year,
            "batch_code": row.batch_code, "exam_type": row.exam_type, "status": row.status,
        }
        for row in db.scalars(
            select(RuleDatasetStatus).where(RuleDatasetStatus.dataset == dataset).order_by(
                RuleDatasetStatus.province_code, RuleDatasetStatus.year
            )
        ).all()
    ]
    return {"actual_by_province_year": actual, "mismatches": mismatches,
            "extra_in_db": extras, "status": statuses}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="规则导入包落库（契约 8.8 通道）")
    parser.add_argument("--subject-dir", type=Path, default=DEFAULT_SUBJECT_DIR)
    parser.add_argument("--physical-dir", type=Path, default=DEFAULT_PHYSICAL_DIR)
    parser.add_argument("--only", choices=["subject", "physical"], default=None,
                        help="只落一个数据集（默认两个都跑）")
    parser.add_argument("--reset-subject", action="store_true",
                        help="先清空 subject_requirement 全部行（导入包重新生成后必须）")
    parser.add_argument("--reset-physical", action="store_true",
                        help="先清空 physical_restriction 全部行（导入包重新生成后必须）")
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        admin = _default_admin(db)
        if admin is None:
            print("[rule_packs] 库内无管理端用户，导入通道需要审计主体；请先创建管理员。")
            return 2
        reports = []
        if args.only != "physical":
            reports.append(_import_dir(db, args.subject_dir, admin, reset=args.reset_subject))
        if args.only != "subject":
            reports.append(_import_dir(db, args.physical_dir, admin, reset=args.reset_physical))

        summary: dict[str, Any] = {"reports": reports, "verify": {}}
        ok = True
        for report in reports:
            dataset = report["dataset"]
            verify = _summarize(db, dataset, report["expected_by_province_year"])
            summary["verify"][dataset] = verify
            print(f"[rule_packs] {dataset} 库内行数：{verify['actual_by_province_year']}")
            for row in verify["status"]:
                print(f"[rule_packs] status {row['province_code']}-{row['year']} "
                      f"{row['batch_code']} {row['exam_type']} -> {row['status']}")
            if verify["mismatches"]:
                ok = False
                print(f"[rule_packs] {dataset} 行数与包不符：{verify['mismatches']}")
            if verify["extra_in_db"]:
                print(f"[rule_packs] {dataset} 库内另有包外数据（未参与核对）：{verify['extra_in_db']}")
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
