#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
专业目录解析：教育部《普通高等学校本科专业目录（2025年）》 → major 表数据

数据源（官方）
  source_name : 中华人民共和国教育部《普通高等学校本科专业目录（2025年）》
  source_url  : https://edu.hainan.gov.cn/edu/zpxx/202508/ea191714a5ad4b5db87afb5c48ccc5ae/files/6e98f3b892f245d7a9430572db818b28.pdf
                （教育部官网原文 PDF 的省级官方镜像；官网 WAF 拦截，见 data/sources/source-registry.md）
  year        : 2025
  文号        : 教高函〔2025〕3 号（2025 年 4 月 1 日）

设计红线（③ 数据工程）
  1. 只解析 PDF 中**实际存在**的内容，**不补全、不推断**。
  2. 专业代码原样保留（含 T=特设 / K=国家控制布点），不擅自剥离。
  3. 数量对不上就以实测为准并**如实登记差异**，不去凑 845 这个数。

用法
  python data/scripts/parse_major_catalog.py            # 解析 + 写出
  python data/scripts/parse_major_catalog.py --dry-run  # 只统计不写文件
"""

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, OrderedDict
from datetime import date
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
PDF = ROOT / "data" / "raw" / "zhuanye_2025_moe.pdf"
OUT_DIR = ROOT / "data" / "majors"
OUT_JSON = OUT_DIR / "majors.json"
OUT_CSV = OUT_DIR / "majors.csv"

SOURCE = {
    "source_id": "SRC-MOE-ZHUANYE-2025",
    "source_name": "中华人民共和国教育部《普通高等学校本科专业目录（2025年）》",
    # 教育部官网原文（已验证可直接下载，825,783 字节，
    # 与海南省教育厅镜像 附件7 为同一文件，MD5 一致）
    "source_url": (
        "https://www.moe.gov.cn/srcsite/A08/moe_1034/s4930/202504/"
        "W020250422312780837078.pdf"
    ),
    "mirror_urls": [
        "https://edu.hainan.gov.cn/edu/zpxx/202508/ea191714a5ad4b5db87afb5c48ccc5ae/files/6e98f3b892f245d7a9430572db818b28.pdf",
    ],
    "year": 2025,
    "source_type": "官方",
    "doc_no": "教高函〔2025〕3 号",
    "issued": "2025-04-01",
    "published": "2025-04-22",
}

# 学科门类两位码（教育部固定编码，来自目录自身的门类编号）
MENLEI_BY_CODE = {
    "01": "哲学", "02": "经济学", "03": "法学", "04": "教育学",
    "05": "文学", "06": "历史学", "07": "理学", "08": "工学",
    "09": "农学", "10": "医学", "12": "管理学", "13": "艺术学",
}

# 目录中门类行标题的规范名（含 2025 年新门类调整）
MENLEI_NAMES = [
    "哲学", "经济学", "法学", "教育学", "文学", "历史学",
    "理学", "工学", "农学", "医学", "管理学", "艺术学",
]

RE_MENLEI = re.compile(r"^\s*(\d{2})?\s*学科门类[:：]\s*(\S+)\s*$")
RE_CLASS = re.compile(r"^(\d{4})\s+(\S+)$")
# ★ 专业代码位数不固定：常见 6 位，但外国语言文学类下的新增专业为 7 位
#   （如 0502104TK 区域国别学、0502100T 语言学、0502101T 塔玛齐格特语 等）。
#   曾因写死 `\d{6}` 漏掉 5 条（840 vs 官方 845），此处放宽为 6~7 位。
RE_MAJOR = re.compile(r"^(\d{6,7}[TK]{0,2})\s+(\S+)$")
RE_NOTE = re.compile(r"[（(]注[:：](.+?)[）)]")
RE_PAGENO = re.compile(r"^—\s*\d+\s*—$")


def norm(s: str) -> str:
    """全角→半角（仅用于比较/清洗，不改专业名本身之外的字符）"""
    return unicodedata.normalize("NFKC", s).strip()


def extract_lines() -> list[str]:
    reader = PdfReader(str(PDF))
    lines: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        for raw in text.splitlines():
            ln = raw.replace("\u3000", " ").strip()
            if not ln:
                continue
            if RE_PAGENO.match(ln):          # 页码 — 47 —
                continue
            lines.append(ln)
    return lines


def parse(lines: list[str]) -> tuple[list[dict], list[dict], list[str]]:
    """返回 (majors, classes, warnings)"""
    majors: list[dict] = []
    classes: list[dict] = []
    warnings: list[str] = []

    cur_menlei: str | None = None
    cur_class: dict | None = None
    pending_menlei_code: str | None = None

    for idx, ln in enumerate(lines):
        # --- 门类行：`01  学科门类：哲学` 或 折行 `学科门类：经济学` ---
        m = RE_MENLEI.match(ln)
        if m:
            code, name = m.group(1), m.group(2)
            name = name.strip()
            if name not in MENLEI_NAMES:
                # 说明文字里的「学科门类」不是行标题，跳过
                continue
            cur_menlei = name
            cur_class = None
            if not code:
                # 折行情况：上一行是纯数字的两位门类码
                for back in range(idx - 1, max(idx - 4, -1), -1):
                    b = lines[back].strip()
                    if re.fullmatch(r"\d{2}", b):
                        code = b
                        break
            if code and MENLEI_BY_CODE.get(code) != name:
                warnings.append(
                    f"门类码与名称不一致: code={code} name={name} "
                    f"（按目录名称为准）"
                )
            pending_menlei_code = code or pending_menlei_code
            continue

        # --- 专业类行：`0101 哲学类` ---
        m = RE_CLASS.match(ln)
        if m and cur_menlei:
            cur_class = {
                "class_code": m.group(1),
                "class_name": m.group(2).strip(),
                "menlei_code": m.group(1)[:2],
                "menlei": cur_menlei,
            }
            classes.append(cur_class)
            continue

        # --- 专业行：`010101  哲学` ---
        m = RE_MAJOR.match(ln)
        if m:
            code_raw = m.group(1)
            rest = m.group(2).strip()

            note = None
            nm = RE_NOTE.search(rest)
            if nm:
                note = nm.group(1).strip()
                rest = RE_NOTE.sub("", rest).strip()

            if cur_class is None:
                warnings.append(f"专业 {code_raw} {rest} 无归属专业类，已跳过")
                continue

            # ★ 剥离 T/K 后缀后再看位数（6 位=常规，7 位=外国语言文学类新增长码）
            core = code_raw.rstrip("TK")
            class_code = core[:4]
            has_t = "T" in code_raw
            has_k = "K" in code_raw

            if not code_raw.startswith(cur_class["class_code"]):
                warnings.append(
                    f"专业 {code_raw} 与当前专业类 {cur_class['class_code']} "
                    f"不一致（按专业码自身前 4 位归属）"
                )

            if has_t and has_k:
                ctype = "特设专业+国家控制布点"
            elif has_t:
                ctype = "特设专业"
            elif has_k:
                ctype = "国家控制布点专业"
            else:
                ctype = "基本专业"

            majors.append({
                "code": code_raw,
                "code_len": len(core),
                "name": rest,
                "code_type": ctype,
                "is_special": has_t,
                "is_state_controlled": has_k,
                "class_code": class_code,
                "class_name": cur_class["class_name"],
                "menlei_code": class_code[:2],
                "menlei": MENLEI_BY_CODE.get(class_code[:2], cur_class["menlei"]),
                "degree_note": note,
            })
            continue

    return majors, classes, warnings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not PDF.exists():
        print(f"✗ 未找到 PDF：{PDF}", file=sys.stderr)
        return 2

    lines = extract_lines()
    majors, classes, warnings = parse(lines)

    # ---- 统计 ----
    menlei_counter = Counter(m["menlei"] for m in majors)
    class_set = {(m["class_code"], m["class_name"]) for m in majors}

    print("=" * 62)
    print("教育部《普通高等学校本科专业目录（2025年）》解析结果")
    print("=" * 62)
    print(f"PDF 页数            : {len(PdfReader(str(PDF)).pages)}")
    print(f"专业条数            : {len(majors)}")
    print(f"专业类数            : {len(class_set)}")
    print(f"学科门类数          : {len(menlei_counter)}")
    print(f"代码重复            : {len(majors) - len({m['code'] for m in majors})}")
    print(f"基本/特设/国控      : "
          f"{sum(1 for m in majors if m['code_type'] == '基本专业')} / "
          f"{sum(1 for m in majors if '特设' in m['code_type'])} / "
          f"{sum(1 for m in majors if m['is_state_controlled'])}")
    print()
    print("各门类专业数：")
    order = {n: i for i, n in enumerate(MENLEI_NAMES)}
    for name, cnt in sorted(menlei_counter.items(), key=lambda kv: order.get(kv[0], 99)):
        print(f"  {name:<6} {cnt:>4}")
    print()

    # ---- 与官方口径核对（845 种 / 93 个专业类）----
    official_majors, official_classes = 845, 93
    print("★ 与官方口径核对：")
    d1 = len(majors) - official_majors
    d2 = len(class_set) - official_classes
    print(f"  专业：解析 {len(majors)} vs 官方 {official_majors}  差 {d1:+d}")
    print(f"  类  ：解析 {len(class_set)} vs 官方 {official_classes}  差 {d2:+d}")
    if d1 != 0:
        print("  ⚠️ 专业数有差异 —— 以解析实测为准，差异原因需人工核对，**不补齐**")
    print()

    if warnings:
        print(f"⚠️ 解析告警 {len(warnings)} 条：")
        for w in warnings[:15]:
            print(f"   - {w}")
        if len(warnings) > 15:
            print(f"   … 另有 {len(warnings)-15} 条")
        print()

    if args.dry_run:
        print("(--dry-run，未写出文件)")
        return 0

    # ---- 写出 ----
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    majors_sorted = sorted(majors, key=lambda m: m["code"])

    payload = {
        "meta": {
            "generated_at": str(date.today()),
            "owner": "徐（③ 数据工程）",
            "target_table": "major",
            "purpose": "专业基础库：专业代码 / 名称 / 学科门类 / 专业类 / 学位授予 / 层次",
            "scope_note": "仅本科专业（教育部本科专业目录）。高职专科专业不在本表。",
            "code_rule": "代码后缀 T=特设专业，K=国家控制布点专业，TK=兼具；本脚本不剥离后缀。",
            "counts": {
                "majors": len(majors_sorted),
                "classes": len(class_set),
                "menlei": len(menlei_counter),
            },
            "official_claim": {
                "majors": official_majors,
                "classes": official_classes,
                "note": "官方口径 93 专业类 / 845 种专业（含 2025 年增设 29 种）。"
                        "本目录仅含学科门类 01–13 的本科专业。",
            },
            **SOURCE,
            "data_status": "verified",
            "data_status_note": (
                "该文件为教育部正式发布文本的 PDF 原件解析，非渠道流转数据；"
                "代码/名称逐条来自 PDF 正文，可回源核对。"
            ),
            "parser": "data/scripts/parse_major_catalog.py",
            "warnings": warnings,
        },
        "menlei": [
            {"menlei_code": c, "menlei": n}
            for c, n in sorted({m["menlei_code"]: m["menlei"] for m in majors}.items())
        ],
        "classes": sorted(
            {c["class_code"]: c for c in classes}.values(),
            key=lambda c: c["class_code"],
        ),
        "majors": majors_sorted,
    }

    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # CSV（便于人工抽查）
    import csv
    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["专业代码", "专业名称", "学科门类", "专业类代码", "专业类",
                    "代码类型", "学位授予注", "层次"])
        for m in majors_sorted:
            w.writerow([m["code"], m["name"], m["menlei"], m["class_code"],
                        m["class_name"], m["code_type"], m["degree_note"] or "",
                        "本科"])

    print(f"✅ 已写出 {OUT_JSON.relative_to(ROOT)}（{len(majors_sorted)} 条）")
    print(f"✅ 已写出 {OUT_CSV.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
