#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""province_exam_rule 数据校验（任务 2.6 的规则数据延伸校验）

校验对象：data/dictionaries/province-exam-rule.json
校验维度：
  1. 三要素（source_name / source_url / year）完整性 —— data_status != schema_only 时强制
  2. 枚举合法性：mode ∈ {group, major_school, school_major}
  3. 数值合法性：volunteer_count / majors_per_group 为非负整数或 null
  4. 逻辑一致性：has_adjust=False → mode 应为 major_school（"专业+院校"不设调剂）
  5. 唯一性：(province, year, batch) 不得重复
  6. source_id 必须在 source-table.json 中存在（★ 契约要求）
  7. year 区间 [2000, 2030]
  8. data_status 枚举
  9. 口径断裂：first_new_gaokao_year != null 且 year < first_new_gaokao_year 时应标 exam_system 老口径

用法：
  python data/scripts/validate_exam_rule.py            # 校验并输出报告
  python data/scripts/validate_exam_rule.py --json     # 输出 JSON 结果
退出码：0 全通过 / 1 有错误
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RULE_FILE = ROOT / "data" / "dictionaries" / "province-exam-rule.json"
SOURCE_FILE = ROOT / "data" / "sources" / "source-table.json"

MODE_ENUM = {"group", "major_school", "school_major"}
STATUS_ENUM = {"verified", "schema_only", "missing", "partial"}
YEAR_MIN, YEAR_MAX = 2000, 2030


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.checked = 0

    def err(self, rid: str, msg: str) -> None:
        self.errors.append(f"[{rid}] {msg}")

    def warn(self, rid: str, msg: str) -> None:
        self.warnings.append(f"[{rid}] {msg}")


def _is_nonneg_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def validate(rules_doc: dict, source_ids: set[str]) -> Report:
    rep = Report()
    rules = rules_doc.get("rules", [])
    seen_keys: dict[tuple, str] = {}

    for r in rules:
        rid = r.get("id") or "<无id>"
        rep.checked += 1
        status = r.get("data_status")

        # 8. data_status 枚举
        if status not in STATUS_ENUM:
            rep.err(rid, f"data_status 非法：{status!r}（允许 {sorted(STATUS_ENUM)}）")

        # 1. 三要素（非 schema_only 强制）
        need_src = status != "schema_only"
        for f in ("source_name", "source_url", "year"):
            if need_src and not r.get(f):
                rep.err(rid, f"三要素缺失：{f}（data_status={status} 要求齐全）")
        if need_src and r.get("source_name") and "example.invalid" in str(r.get("source_url", "")):
            rep.err(rid, "source_url 为占位地址（example.invalid）")

        # 6. source_id 必须存在于 source 表
        sid = r.get("source_id")
        if need_src:
            if not sid:
                rep.err(rid, "缺 source_id")
            elif sid not in source_ids:
                rep.err(rid, f"source_id={sid} 不在 source-table.json 中（契约要求先登记）")

        # 7. year 区间
        y = r.get("year")
        if isinstance(y, int) and not (YEAR_MIN <= y <= YEAR_MAX):
            rep.err(rid, f"year={y} 超出 [{YEAR_MIN},{YEAR_MAX}]")

        # 2. mode 枚举
        mode = r.get("mode")
        if mode not in MODE_ENUM:
            rep.err(rid, f"mode 非法：{mode!r}（允许 {sorted(MODE_ENUM)}）")

        # 3. 数值合法性
        for f in ("volunteer_count", "majors_per_group", "collect_count"):
            v = r.get(f)
            if v is not None and not _is_nonneg_int(v):
                rep.err(rid, f"{f} 应为非负整数或 null，实际 {v!r}")
        if need_src and not _is_nonneg_int(r.get("volunteer_count")):
            rep.err(rid, "volunteer_count 缺失（verified 数据必须有志愿单位数）")

        # 4. 逻辑一致性：专业+院校不设调剂
        if mode == "major_school" and r.get("has_adjust") is True:
            rep.err(rid, "mode=major_school 却 has_adjust=True（「专业+院校」模式不设调剂）")

        # 9. 口径断裂提示
        fng = r.get("first_new_gaokao_year")
        es = r.get("exam_system")
        if isinstance(fng, int) and isinstance(y, int):
            if y < fng and es != "文理科":
                rep.warn(rid, f"year={y} < first_new_gaokao_year={fng} 但 exam_system={es!r}，应为'文理科'")
            if y >= fng and es == "文理科":
                rep.warn(rid, f"year={y} >= first_new_gaokao_year={fng} 但 exam_system='文理科'")

        # 5. 唯一性 (province, year, batch)
        key = (r.get("province"), r.get("year"), r.get("batch"))
        if key in seen_keys:
            rep.err(rid, f"(province,year,batch)={key} 与 {seen_keys[key]} 重复")
        else:
            seen_keys[key] = rid

        # schema_only 提示
        if status == "schema_only":
            rep.warn(rid, "data_status=schema_only：数值未经核实，不得当作真实规则使用")

    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    rules_doc = json.loads(RULE_FILE.read_text(encoding="utf-8"))
    source_doc = json.loads(SOURCE_FILE.read_text(encoding="utf-8"))
    source_ids = {s["id"] for s in source_doc.get("sources", [])}

    rep = validate(rules_doc, source_ids)

    if args.json:
        print(json.dumps(
            {"checked": rep.checked, "errors": rep.errors, "warnings": rep.warnings},
            ensure_ascii=False, indent=2))
    else:
        print(f"province_exam_rule 校验：共 {rep.checked} 条")
        print(f"source 表已登记 {len(source_ids)} 条")
        if rep.warnings:
            print(f"\n⚠️  警告 {len(rep.warnings)} 条：")
            for w in rep.warnings:
                print("   " + w)
        if rep.errors:
            print(f"\n❌ 错误 {len(rep.errors)} 条：")
            for e in rep.errors:
                print("   " + e)
        else:
            print("\n✅ 无错误，校验通过。")

    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
