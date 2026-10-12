#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
数据入库强制校验脚本（任务 2.6）

职责：校验所有事实数据的「来源三要素」完整性，缺失则拒绝。

依据：
  - 产品书第 7 章通用要求：所有事实表必须含 source_name、source_url、year
  - 产品书第 7 章第七节：当前不得提交密钥、隐私或未经审核的政策数据
  - tasks.md 2.6：所有事实表须含来源三要素，缺失则拒绝入库

用法：
  python validate.py <csv|json 文件或目录> [--kind 数据类型] [--strict]

  # 校验单个文件
  python validate.py ../samples/schools.csv --kind school

  # 校验整个目录
  python validate.py ../samples/ --kind school

  # 严格模式（把 schema_only/pending 也视为错误）
  python validate.py ../samples/ --strict

退出码：
  0  全部通过
  1  存在不合规记录（拒绝入库）
  2  用法错误 / 文件不存在
"""

import argparse
import csv
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List

# ─────────────────────────────────────────────────────────
# 常量定义（禁止魔法值）
# ─────────────────────────────────────────────────────────

# 来源三要素（★ 缺一不可）
REQUIRED_SOURCE_FIELDS = ("source_name", "source_url", "year")

# 允许出现三要素的替代形式：外键 source_id 可替代三要素
SOURCE_FK_FIELD = "source_id"

# 数据状态枚举
DATA_STATUS_VERIFIED = "verified"
DATA_STATUS_SCHEMA_ONLY = "schema_only"
DATA_STATUS_PENDING = "pending"
VALID_DATA_STATUS = {DATA_STATUS_VERIFIED, DATA_STATUS_SCHEMA_ONLY, DATA_STATUS_PENDING}

# 优先级枚举
VALID_PRIORITY = {"P0", "P1", "P2"}

# 允许的来源类型
VALID_SOURCE_TYPE = {"官方", "高校官网", "权威媒体", "其他"}

# 年份合理区间（防止抓错年份）
MIN_YEAR = 2000
MAX_YEAR = 2030

# URL 基本校验（拒绝占位地址）
URL_PATTERN = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)
PLACEHOLDER_HINTS = ("example.invalid", "example.com", "todo", "待填", "placeholder", "xxx")

# 按数据类型定义「必填字段」（除三要素外）
SCHEMA_BY_KIND: Dict[str, List[str]] = {
    "pathway": ["id", "name", "category", "priority", "data_status"],
    "pathway_region": ["pathway_id", "province", "county_name"],
    "pathway_eligibility": ["pathway_id", "province", "rule_type", "rule_desc"],
    "school": ["id", "name", "province"],
    "major": ["id", "name", "category"],
    "school_major_score": [
        "school_id", "province", "year", "batch", "min_score", "source_id",
    ],
    "score_segment": ["province", "year", "subject_type", "score", "cumulative_rank"],
    "school_profile": ["school_id"],
    "school_life": ["school_id", "category", "content", "source_type", "reliability"],
    "source": ["source_name", "source_url", "year", "source_type"],
    "province_exam_rule": ["province", "year", "batch", "mode"],
}

# 用 source_id 外键引用 `source` 表、而非内联三要素的"种类"
# 这类记录只要带非空 source_id 即视为满足来源要求
SOURCE_ID_KINDS = {"pathway_region", "pathway_eligibility", "pathway_score",
                   "school_major_score", "score_segment", "enrollment_rule",
                   "discipline_eval", "pathway", "major"}

# ★ 字段别名：③ 侧采集产物的字段名 → 第 7 章建表字段名
#   背景：③ 的产物忠实于**原始数据源**（如教育部专业目录给的是
#   `code / name / class_name / menlei`），而第 7 章 `major` 表用的是
#   `id / name / code / category / first_class`。二者语义相同、命名不同。
#   校验器按第 7 章口径检查，但允许通过别名找到实际字段，**避免为迎合
#   校验器而扭曲采集产物的原始字段名**。
FIELD_ALIASES: Dict[str, Dict[str, List[str]]] = {
    "major": {
        "category": ["menlei", "class_name"],     # 学科门类
        "first_class": ["class_name"],            # 专业类
        "id": ["code"],                           # 用国标专业代码作业务主键
    },
}


def _resolve_field(rec: Dict[str, Any], kind: str, field_name: str) -> Any:
    """按别名表解析字段值；找不到返回 None"""
    if field_name in rec:
        return rec[field_name]
    for alt in FIELD_ALIASES.get(kind, {}).get(field_name, []):
        if alt in rec:
            return rec[alt]
    return None


# 有年份语义的字段（需做区间校验）
YEAR_FIELDS = {"year"}


# ─────────────────────────────────────────────────────────
# 结果模型
# ─────────────────────────────────────────────────────────

@dataclass
class Issue:
    """一条不合规记录"""
    record_no: int          # 记录序号（从 1 开始）
    record_id: str          # 记录标识（尽量取 id / name）
    level: str              # ERROR / WARN
    message: str            # 问题描述


@dataclass
class Report:
    file: str
    kind: str
    total: int = 0
    passed: int = 0
    issues: List[Issue] = field(default_factory=list)

    @property
    def errors(self) -> List[Issue]:
        return [i for i in self.issues if i.level == "ERROR"]

    @property
    def warnings(self) -> List[Issue]:
        return [i for i in self.issues if i.level == "WARN"]

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0

    @property
    def rejected(self) -> int:
        """被拒绝入库的记录数（去重）"""
        return len({i.record_no for i in self.errors})


# ─────────────────────────────────────────────────────────
# 单项校验
# ─────────────────────────────────────────────────────────

def _is_blank(value: Any) -> bool:
    """判断是否为空值"""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def _looks_placeholder(value: str) -> bool:
    """判断是否为占位内容"""
    low = value.strip().lower()
    return any(hint in low for hint in PLACEHOLDER_HINTS)


def check_source_triplet(rec: Dict[str, Any], *, allow_fk: bool = True):
    """
    校验来源三要素。

    返回 (错误列表, 警告列表)
      - 若有 source_id 且 allow_fk，则视为满足（外键形式）
      - 否则三要素必须齐全且有效
    """
    errors, warnings = [], []

    # 外键形式：满足
    if allow_fk and not _is_blank(rec.get(SOURCE_FK_FIELD)):
        return errors, warnings

    for f in REQUIRED_SOURCE_FIELDS:
        if f not in rec:
            errors.append(f"缺少来源三要素字段 `{f}`")
            continue
        if _is_blank(rec[f]):
            errors.append(f"来源三要素 `{f}` 为空")
            continue

        # 逐字段深入校验
        if f == "year":
            errors.extend(_check_year(rec[f]))
        elif f == "source_url":
            errors.extend(_check_url(str(rec[f])))
        elif f == "source_name":
            if _looks_placeholder(str(rec[f])):
                errors.append(f"来源名称 `{rec[f]}` 疑似占位内容，不可入库")

    return errors, warnings


def _check_year(value: Any) -> List[str]:
    out = []
    try:
        y = int(value)
    except (TypeError, ValueError):
        return [f"`year` 不是合法整数：{value!r}"]
    if not (MIN_YEAR <= y <= MAX_YEAR):
        out.append(f"`year` = {y} 超出合理区间 [{MIN_YEAR}, {MAX_YEAR}]")
    return out


def _check_url(value: str) -> List[str]:
    out = []
    if not URL_PATTERN.match(value):
        out.append(f"`source_url` 不是合法 http(s) 链接：{value!r}")
    elif _looks_placeholder(value):
        out.append(f"`source_url` 疑似占位地址，不可入库：{value!r}")
    return out


def check_required(rec: Dict[str, Any], kind: str) -> List[str]:
    """校验该类型要求的必填字段（支持 FIELD_ALIASES 别名回退）"""
    errors = []
    for f in SCHEMA_BY_KIND.get(kind, []):
        val = _resolve_field(rec, kind, f)
        if val is None or _is_blank(val):
            errors.append(f"缺少必填字段 `{f}`")
    return errors


def check_enums(rec: Dict[str, Any]) -> List[str]:
    """校验枚举值合法性"""
    errors = []

    if "priority" in rec and not _is_blank(rec["priority"]):
        if rec["priority"] not in VALID_PRIORITY:
            errors.append(f"`priority` 取值非法：{rec['priority']!r}（应为 P0/P1/P2）")

    if "data_status" in rec and not _is_blank(rec["data_status"]):
        if rec["data_status"] not in VALID_DATA_STATUS:
            errors.append(
                f"`data_status` 取值非法：{rec['data_status']!r}"
                f"（应为 {'/'.join(sorted(VALID_DATA_STATUS))}）"
            )

    if "source_type" in rec and not _is_blank(rec["source_type"]):
        if rec["source_type"] not in VALID_SOURCE_TYPE:
            errors.append(f"`source_type` 取值非法：{rec['source_type']!r}")

    return errors


def validate_record(rec: Dict[str, Any], kind: str, *, strict: bool = False,
                    file_meta: Dict[str, Any] | None = None):
    """
    校验单条记录，返回 (错误列表, 警告列表)

    file_meta：文件级来源三要素（如 score_segment 的 meta）。
    当某条记录自身既无三要素也无 source_id 时，回退到 file_meta。
    """
    errors: List[str] = []
    warnings: List[str] = []

    # 1. 必填字段
    errors.extend(check_required(rec, kind))

    # 2. 来源三要素（★ 核心）
    #    支持三级回退：记录内三要素 → 记录内 source_id → 文件级 meta 三要素
    errs, warns = _check_provenance(rec, kind, file_meta)
    errors.extend(errs)
    warnings.extend(warns)

    # 3. 枚举合法性
    errors.extend(check_enums(rec))

    # 4. 数据状态语义提示
    status = rec.get("data_status")
    if status == DATA_STATUS_SCHEMA_ONLY:
        msg = "`data_status=schema_only`（仅架构，界面须标注「规划中」）"
        (errors if strict else warnings).append(msg)
    elif status == DATA_STATUS_PENDING:
        msg = "`data_status=pending`（数据待采集，界面须如实标注）"
        (errors if strict else warnings).append(msg)

    return errors, warnings


def _check_provenance(rec: Dict[str, Any], kind: str,
                      file_meta: Dict[str, Any] | None):
    """
    来源三要素校验（含文件级回退）。

    优先级：
      1) 记录自身含完整三要素 → 直接通过
      2) 记录含非空 source_id（且该 kind 允许外键） → 通过
      3) 文件级 meta 含完整三要素 → 视为整表来源，通过
      4) 文件级 meta 含 source_id → 通过
      否则报错。
    """
    # 1) 记录自身三要素齐全
    errs, warns = check_source_triplet(rec, allow_fk=False)
    if not errs:
        return errs, warns

    # 2) 记录含 source_id 且该 kind 允许外键
    if kind in SOURCE_ID_KINDS and not _is_blank(rec.get(SOURCE_FK_FIELD)):
        return [], []

    # 3/4) 文件级 meta 回退
    if file_meta:
        meta_errs, _ = check_source_triplet(file_meta, allow_fk=False)
        if not meta_errs:
            return [], warns
        if kind in SOURCE_ID_KINDS and not _is_blank(file_meta.get(SOURCE_FK_FIELD)):
            return [], warns

    # 都不满足：报记录自身的错误（信息量最大）
    return errs, warns


# ─────────────────────────────────────────────────────────
# 文件读取
# ─────────────────────────────────────────────────────────

def read_records(path: str) -> List[Dict[str, Any]]:
    """读取 CSV 或 JSON 记录，统一返回 list[dict]"""
    recs, _meta = read_records_with_meta(path)
    return recs


def read_records_with_meta(path: str) -> "tuple[List[Dict[str, Any]], Dict[str, Any]]":
    """
    读取 CSV 或 JSON，返回 (记录数组, 文件级 meta)。

    为什么需要返回 meta：
    ── 有些事实表（如 score_segment 一分一段）的来源三要素是**整表级**的，
       写在文件顶部的 meta 里，而不是每行重复。若只校验行内三要素，
       这类表会被误判为"364 行全部缺来源"。
       因此把 meta 一并返回，供校验器作为"文件级来源"回退依据。
    """
    ext = os.path.splitext(path)[1].lower()

    if ext == ".json":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
            # 优先按已知包装键取数组
            for key in ("records", "items", "data", "pathways", "regions",
                        "counties", "sources", "rules", "segments", "list",
                        "majors", "classes", "schools", "scores"):
                if key in data and isinstance(data[key], list):
                    return data[key], meta
            # 兜底：若 dict 中"唯一"的 list 值就有记录数组，则取之
            # （这样新增文件即使换键名也不必再改本脚本）
            list_values = [v for k, v in data.items()
                           if isinstance(v, list) and k != "meta"]
            if len(list_values) == 1 and list_values[0] and \
                    isinstance(list_values[0][0], dict):
                return list_values[0], meta
            return [data], meta
        if isinstance(data, list):
            return data, {}
        raise ValueError(f"无法识别的 JSON 结构：{type(data).__name__}")

    if ext == ".csv":
        with open(path, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f)), {}

    raise ValueError(f"不支持的文件类型：{ext}（仅支持 .csv / .json）")


# ─────────────────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────────────────

def collect_files(target: str) -> List[str]:
    """收集待校验文件"""
    if os.path.isfile(target):
        return [target]
    if os.path.isdir(target):
        out = []
        for root, _dirs, files in os.walk(target):
            for fn in sorted(files):
                if fn.lower().endswith((".csv", ".json")):
                    out.append(os.path.join(root, fn))
        return out
    raise FileNotFoundError(f"路径不存在：{target}")


def validate_file(path: str, kind: str, *, strict: bool = False) -> Report:
    """校验一个文件"""
    report = Report(file=path, kind=kind)
    try:
        records, file_meta = read_records_with_meta(path)
    except Exception as exc:  # noqa: BLE001
        report.issues.append(Issue(0, "-", "ERROR", f"读取失败：{exc}"))
        return report

    report.total = len(records)
    for idx, rec in enumerate(records, start=1):
        if not isinstance(rec, dict):
            report.issues.append(Issue(idx, "-", "ERROR", "记录不是对象结构"))
            continue
        rid = str(rec.get("id") or rec.get("name") or rec.get("school_id") or f"#{idx}")
        errs, warns = validate_record(rec, kind, strict=strict, file_meta=file_meta)
        for e in errs:
            report.issues.append(Issue(idx, rid, "ERROR", e))
        for w in warns:
            report.issues.append(Issue(idx, rid, "WARN", w))
        if not errs:
            report.passed += 1

    return report


def print_report(report: Report) -> None:
    """打印单个文件的校验结果"""
    name = os.path.relpath(report.file)
    if report.ok and not report.warnings:
        print(f"[PASS] {name}  ({report.passed}/{report.total} 条通过)")
        return

    tag = "PASS" if report.ok else "FAIL"
    print(f"[{tag}] {name}  ({report.passed}/{report.total} 条通过，"
          f"拒绝 {report.rejected} 条，警告 {len(report.warnings)} 条)")

    for issue in report.issues:
        mark = "  x" if issue.level == "ERROR" else "  !"
        print(f"{mark} 第{issue.record_no}条 [{issue.record_id}] {issue.message}")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="数据入库强制校验（来源三要素）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("target", help="待校验的文件或目录")
    parser.add_argument(
        "--kind", default="pathway",
        choices=sorted(SCHEMA_BY_KIND.keys()),
        help="数据类型（决定必填字段），默认 pathway",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="严格模式：schema_only / pending 也视为错误",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        files = collect_files(args.target)
    except FileNotFoundError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    if not files:
        print(f"未找到可校验的 .csv/.json 文件：{args.target}")
        return 0

    reports = [validate_file(p, args.kind, strict=args.strict) for p in files]

    print("=" * 62)
    print(f"数据三要素校验  |  类型={args.kind}  严格模式={'是' if args.strict else '否'}")
    print("=" * 62)
    for r in reports:
        print_report(r)

    total = sum(r.total for r in reports)
    passed = sum(r.passed for r in reports)
    errors = sum(len(r.errors) for r in reports)
    warns = sum(len(r.warnings) for r in reports)

    print("-" * 62)
    print(f"合计：{len(reports)} 个文件，{total} 条记录")
    print(f"      通过 {passed} 条 ｜ 错误 {errors} 处 ｜ 警告 {warns} 处")

    if errors:
        print("\n结论：存在不合规记录 —— 按第 7 章要求，缺失来源三要素的数据【拒绝入库】。")
        return 1

    print("\n结论：全部通过，可入库。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
