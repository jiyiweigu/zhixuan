#!/usr/bin/env python3
"""Generate a reproducible T6 coverage report from the checked-in rule dictionaries."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUBJECT = ROOT / "data/raw/subject-requirement.full.json"
PHYSICAL = ROOT / "data/dictionaries/physical-restriction.json"
OUTPUT = ROOT / "data/reports/admission-gate-coverage-2026.md"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    subject_doc = json.loads(SUBJECT.read_text(encoding="utf-8"))
    rows = subject_doc.get("rows", [])
    physical_doc = json.loads(PHYSICAL.read_text(encoding="utf-8"))
    rules = physical_doc.get("rules", [])
    provinces = (("41", "河南"), ("36", "江西"))
    lines = [
        "# T6 报考闸门规则覆盖审计（2026）",
        "",
        "本报告依据仓库内 T4/T5 字典生成；不使用数据库行数，也不以旧年份目标代替 2026 目标。",
        "",
        "## 选科要求",
        "",
        "| 省份 | 年份 | ok 组级行 | ok 专业级行 | missing | unparsed | 2026 目标分母 | 2026 已覆盖目标 | 预计 3001 比例 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for code, name in provinces:
        years = sorted({int(row["year"]) for row in rows if row.get("province_code") == code})
        for year in years + ([2026] if 2026 not in years else []):
            subset = [row for row in rows if row.get("province_code") == code and int(row.get("year") or 0) == year]
            count = Counter((row.get("status"), row.get("target_type")) for row in subset)
            group_ok = count[("ok", "group")]
            major_ok = count[("ok", "major")]
            missing = sum(v for (status, _), v in count.items() if status == "missing")
            unparsed = sum(v for (status, _), v in count.items() if status == "unparsed")
            denom = "不可计算（缺少 2026 招生目标清单）" if year == 2026 else "非首期验收年份"
            covered = "0" if year == 2026 else "不适用"
            share = "不可计算（分母缺失）" if year == 2026 else "不适用"
            lines.append(
                f"| {name} ({code}) | {year} | {group_ok} | {major_ok} | {missing} | {unparsed} | {denom} | {covered} | {share} |"
            )
    lines += [
        "",
        f"数据来源：`{SUBJECT.relative_to(ROOT).as_posix()}`（{len(rows):,} 行；SHA-256 `{digest(SUBJECT)}`）。",
        "",
        "河南、江西的 2026 选科源数据均为 0 行，因此不使用 2024/2025 行数估算 3001 目标数/比例。实际提交的 2026 目标若无明确目标级规则，服务应按 fail-closed 语义返回 3001。",
        "",
        "## 体检限制",
        "",
        f"T5 字典包含 {len(rules)} 条规则。`engine_integration` 列出 3 组剩余扩展事项（BMI、性别相关身高、矫正视力）；4.5 裸眼视力线已由 T6 支持。当前档案字段无法安全求值的项目必须保持 unknown。",
        "",
        f"数据来源：`{PHYSICAL.relative_to(ROOT).as_posix()}`（SHA-256 `{digest(PHYSICAL)}`）。",
        "",
        "## 统计口径",
        "",
        "- 选科行按 province_code/year/status/target_type 统计；不将规则行数当成 2026 招生目标数。",
        "- 计算 2026 分母需要独立来源的 2026 院校/专业组/专业目标清单；T4 完整字典中没有该清单。",
        "- 当前 T4 快照的 2026 已覆盖目标数为 0；取得目标分母前，目标覆盖率和预计 3001 比例不可计算。",
    ]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
