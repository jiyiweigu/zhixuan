#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
major 表就绪数据：`data/majors/majors.json` → 与 ORM 模型逐列对齐的 938 行

目标表  : backend/app/models/base_data.py :: Major
来源    : data/majors/majors.json（教育部《普通高等学校本科专业目录（2025年）》解析产物）
          data/raw/*_enrollment-plan.csv（学制 / 学费样本，仅取**本科批次**）

★ 为什么是 938 行 = 845 专业 + 93 专业类
  录取分库里 10,817 行是「按大类招生」，其专业标识是 **4 位专业类代码**（如 0809）。
  major 表若只放 845 个专业行，这 10,817 行的 major_id 将**无处可指**。
  补入 93 个专业类行（is_category=True，code=类码 4 位）后，全量 116,036 行可 100% 解析。

★ 字段口径（每条均有实测依据，见输出 meta.rationale）
  category        ← ★ **口径有争议，见下**。默认取 menlei（学科门类），可用
                    `--category-source class` 一键切为 class_name（专业类）。
                    依据 A（前端契约 frontend/src/mocks/index.ts）：
                      majors.items[0] = {name:'计算机类', code:'0809', category:'工学'}
                      → category = 学科门类
                    依据 B（**可运行代码** backend/app/services/constraints.py:125）：
                      `PhysicalRestriction.major_category == major.category`
                      而体检规则 physical_restriction.major_category 的取值是
                      「医学类 / 化工与制药类 / 美术学类 / 戏剧与影视学类 / 交通运输类 /
                        公安学类 / 教育学类」——**全是专业类**
                      → category = 专业类
                    ⚠️ 二者只能选一：若取门类，`physical_restriction` 的
                      `major_category` 分支**全部失配**（仅剩 `major_code` 分支可救）。
                      本脚本两种都产出（`category` 可切、`class_name`/`menlei` 常带），
                      等 ②/队长裁定后改一个参数即可，**不需要重写**。
                    注意 constraint_seed.py 的演示种子把 category 写成了专业类，
                    与前端契约不一致 —— 那是②的演示口径。
  degree          ← 仅取目录中**显式加注**的 96 条（如 020306T「可授经济学或管理学学士学位」）。
                    官方目录是扁平列表，**没有**独立的「学位授予门类」列；
                    未加注的 749 条一律留空，**不按门类推断**（宁可缺，不可猜）。
  duration        ← 招生计划本科批次样本的**众数**，统一归一为中文（四年 / 五年 …）。
                    依据：constraint_seed.py 演示种子写 `duration="四年"`。
  tuition         ← ★ **不填单值**。实测同一专业学费跨 0～190,000 元、605/640 个专业存在波动
                    （公办 5000 与中外合作 95000 同专业并存），单值必然误导。
                    改为输出 major_tuition_stats.json 分布；`tuition` 置 NULL。
  ownership / campus / single_subject_req / language_req / gender_req / interview_required
                  ← 均为**校×专业**属性（藏在招生章程里），不属于全国专业字典，
                    一律留空 / False，由 enrollment_rule（D3）承载。
  first_class     ← 模型注释为「是否一流本科专业建设点」，③ 无此来源 → 留空。
                    （validate.py 曾把它别名到 class_name，属笔误，已订正。）

用法
  python data/scripts/build_major_table.py
  python data/scripts/build_major_table.py --check     # 只校验不写出
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import re
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAJORS_JSON = ROOT / "data" / "majors" / "majors.json"
SOURCE_TABLE = ROOT / "data" / "sources" / "source-table.json"
RAW_GLOB = "data/raw/*_enrollment-plan.csv"
OUT_ROWS = ROOT / "data" / "majors" / "major_table_rows.json"
OUT_TUITION = ROOT / "data" / "majors" / "major_tuition_stats.json"

# 招生计划 CSV 的获取渠道（三要素落进 meta，供 validate.py 做文件级来源回退）
RAW_SOURCE_ID = "SRC-GAOKAO-COMPASS"


def raw_source_triplet() -> dict:
    """从 source-table.json 取招生计划渠道来源的三要素（不硬编码，保持单一事实源）"""
    with SOURCE_TABLE.open(encoding="utf-8") as f:
        for s in json.load(f)["sources"]:
            if s["id"] == RAW_SOURCE_ID:
                return {
                    "source_id": s["id"],
                    "source_name": s["source_name"],
                    "source_url": s["source_url"],
                    "year": s["year"],
                }
    raise SystemExit(f"✗ source-table.json 中找不到 {RAW_SOURCE_ID}")

# ── 学制归一表 ────────────────────────────────────────────────
# 招生计划里同一语义有多种写法：'4' / '4年' / '四年'；'-' 表示缺失。
DUR_MAP = {
    "2": "两年", "2年": "两年", "两年": "两年",
    "3": "三年", "3年": "三年", "三年": "三年",
    "4": "四年", "4年": "四年", "四年": "四年",
    "5": "五年", "5年": "五年", "五年": "五年",
    "6": "六年", "6年": "六年", "六年": "六年",
    "7": "七年", "7年": "七年", "七年": "七年",
    "8": "八年", "8年": "八年", "八年": "八年", "八年医": "八年",
    "9": "九年", "9年": "九年", "九年": "九年",
}
# 中文写法优先（归一化后为同一值，这里只是 tie-break 的偏好集）
DUR_PREFER = {"两年", "三年", "四年", "五年", "六年", "七年", "八年", "九年"}

RE_PAREN = re.compile(r"[（(].*?[)）]")

# 本科批次判定：批名字符串含「本科」即算本科；专科/高职一律排除
def is_undergrad_batch(batch: str) -> bool:
    b = str(batch or "")
    if not b:
        return False
    if "专科" in b or "高职" in b:
        return False
    return "本科" in b


def norm_name(s: str) -> str:
    """去括号注释 + 全角转半角 + 去空白（仅用于匹配，不改写专业名本体）"""
    s = RE_PAREN.sub("", str(s or ""))
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"\s+", "", s).strip()


def load_majors() -> dict:
    with MAJORS_JSON.open(encoding="utf-8") as f:
        return json.load(f)


def collect_samples(major_names: set[str], class_names: set[str]) -> tuple[dict, dict, dict]:
    """从招生计划（仅本科批次）聚合学制/学费样本。

    返回 (duration_counter, tuition_samples, file_stats)
    """
    dur: dict[str, Counter] = defaultdict(Counter)
    tui: dict[str, list[float]] = defaultdict(list)
    file_stats: dict[str, dict] = {}

    for p in sorted(glob.glob(str(ROOT / RAW_GLOB))):
        with open(p, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        n_all = len(rows)
        n_ug = 0
        matched = 0
        unnamed = 0
        for r in rows:
            if not is_undergrad_batch(r.get("batch", "")):
                continue
            n_ug += 1
            raw_name = str(r.get("major_name") or "").strip()
            if not raw_name:
                unnamed += 1
                continue
            nm = norm_name(raw_name)
            if nm not in major_names and nm not in class_names:
                continue
            matched += 1
            dv = DUR_MAP.get(str(r.get("duration") or "").strip())
            if dv:
                dur[nm][dv] += 1
            tv = str(r.get("tuition") or "").strip()
            if tv:
                try:
                    tui[nm].append(float(tv))
                except ValueError:
                    pass
        file_stats[Path(p).name] = {
            "rows_total": n_all,
            "rows_undergrad": n_ug,
            "rows_matched_major_or_class": matched,
            "rows_missing_major_name": unnamed,
        }
    return dur, tui, file_stats


def pick_duration(counter: Counter) -> str | None:
    if not counter:
        return None
    top = max(counter.values())
    cands = [k for k, v in counter.items() if v == top]
    if len(cands) == 1:
        return cands[0]
    # 平票：优先纯中文写法，其次字数多的
    zh = [c for c in cands if c in DUR_PREFER]
    return sorted(zh or cands, key=lambda s: (-len(s), s))[0]


def build_rows(data: dict, dur: dict, tui: dict, category_source: str) -> tuple[list[dict], dict]:
    majors = data["majors"]
    classes = data["classes"]

    def cat_of(menlei: str, class_name: str) -> str:
        return (class_name if category_source == "class" else menlei) or ""

    # ── 845 专业行 ──
    rows: list[dict] = []
    dur_filled = 0
    for m in majors:
        name = m["name"]
        d = pick_duration(dur.get(norm_name(name), Counter()))
        if d:
            dur_filled += 1
        rows.append({
            "name": name,
            "code": m["code"],
            "category": cat_of(m.get("menlei") or "", m.get("class_name") or ""),
            "first_class": "",
            "degree": (m.get("degree_note") or "").strip(),
            "tuition": None,
            "ownership": "",
            "duration": d or "",
            "campus": "",
            "is_category": False,
            "single_subject_req": "",
            "language_req": "",
            "gender_req": "",
            "interview_required": False,
            # ↓ 模型无此两列，但保留供口径切换/追溯（② 灌数时忽略即可）
            "menlei": m.get("menlei") or "",
            "class_name": m.get("class_name") or "",
        })

    # ── 93 专业类行（is_category=True，供「按大类招生」映射）──
    cls_rows = []
    cls_dur_filled = 0
    for c in classes:
        cname = c["class_name"]
        d = pick_duration(dur.get(norm_name(cname), Counter()))
        if d:
            cls_dur_filled += 1
        cls_rows.append({
            "name": cname,
            "code": c["class_code"],
            "category": cat_of(c.get("menlei") or "", cname),
            "first_class": "",
            "degree": "",
            "tuition": None,
            "ownership": "",
            "duration": d or "",
            "campus": "",
            "is_category": True,
            "single_subject_req": "",
            "language_req": "",
            "gender_req": "",
            "interview_required": False,
            "menlei": c.get("menlei") or "",
            "class_name": cname,
        })
    rows.extend(cls_rows)

    stats = {
        "major_rows": len(majors),
        "class_rows": len(cls_rows),
        "total_rows": len(rows),
        "category_source": category_source,
        "duration_filled_major": dur_filled,
        "duration_filled_class": cls_dur_filled,
        "degree_filled": sum(1 for r in rows if r["degree"]),
        "category_filled": sum(1 for r in rows if r["category"]),
    }
    return rows, stats


def build_flags(dur: dict, tui: dict) -> dict:
    """构建校验：行数、主键唯一性、别名语义自洽"""
    flags: list[str] = []
    return {"flags": flags}


def write_tuition_stats(tui: dict, majors: list[dict], src: dict) -> dict:
    """学费分布（不填单值，只做留痕）

    记录自带 code / name / category，使文件本身能被 validate.py --kind major 校验
    （major 是基础字典，校验器从代码/名称/门类三处识别记录身份）。
    """
    out = []
    for m in sorted(majors, key=lambda x: x["code"]):
        v = tui.get(norm_name(m["name"]))
        if not v or len(v) < 3:
            continue
        vs = sorted(v)
        out.append({
            "code": m["code"],
            "name": m["name"],
            "category": m.get("menlei") or "",
            "n": len(vs),
            "min": int(round(vs[0])),
            "p25": int(round(statistics.quantiles(vs, n=4)[0])) if len(vs) >= 4 else int(round(vs[0])),
            "median": int(round(statistics.median(vs))),
            "p75": int(round(statistics.quantiles(vs, n=4)[2])) if len(vs) >= 4 else int(round(vs[-1])),
            "max": int(round(vs[-1])),
        })
    return {
        "meta": {
            "generated_at": str(date.today()),
            "owner": "徐（③ 数据工程）",
            "purpose": "学费分布参考：用于说明「major.tuition 为何不填单值」",
            "not_for_ingest": True,
            "not_for_ingest_note": (
                "本文件**不是**入库产物，无对应物理表 —— 只在③侧留痕、支撑口径裁决。"
                "待 ② 明确 `major_tuition` 逻辑表结构后，再由原始 CSV 重新导出。"
            ),
            "scope": "招生计划本科批次，按专业名（去括号注释）聚合；样本数 <3 的专业不列出",
            "caveat": (
                "学费是**校×专业**属性：同一专业在不同院校/办学性质下差异极大"
                "（公办约 5000，中外合作可达 190,000）。本表 median 仅作粗粒度参考，"
                "**不得**当作学费承诺；逐校学费应由 `major_tuition` / `school_major_score` 承载。"
            ),
            "source_files": [Path(p).name for p in sorted(glob.glob(str(ROOT / RAW_GLOB)))],
            "excluded_note": "2024 河南：本科批次 major_name 整列为空（54,738 行），无法归到专业，未参与聚合。",
            **src,
        },
        "stats": out,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验，不写出文件")
    ap.add_argument(
        "--category-source", choices=("menlei", "class"), default="menlei",
        help="category 取学科门类（默认，合前端契约）还是专业类（合体检规则匹配）",
    )
    args = ap.parse_args()

    if not MAJORS_JSON.exists():
        print(f"✗ 未找到 {MAJORS_JSON}", file=sys.stderr)
        return 2

    data = load_majors()
    src = raw_source_triplet()
    major_names = {m["name"] for m in data["majors"]}
    class_names = {c["class_name"] for c in data["classes"]}

    dur, tui, file_stats = collect_samples(major_names, class_names)
    rows, stats = build_rows(data, dur, tui, args.category_source)

    print("=" * 70)
    print("major 表就绪数据构建")
    print("=" * 70)
    print(f"category 取值来源  : {args.category_source}"
          f"（{'学科门类，合前端契约' if args.category_source == 'menlei' else '专业类，合体检规则匹配'}）")
    print(f"专业行            : {stats['major_rows']}")
    print(f"专业类行          : {stats['class_rows']}")
    print(f"合计              : {stats['total_rows']}   （签约需要 938）")
    print(f"category 已填     : {stats['category_filled']}/{stats['total_rows']}")
    print(f"duration 已填     : 专业 {stats['duration_filled_major']}/{stats['major_rows']}"
          f"  专业类 {stats['duration_filled_class']}/{stats['class_rows']}")
    print(f"degree 已填       : {stats['degree_filled']}（仅目录显式加注者）")
    print(f"tuition           : 0（按口径不填单值，见 major_tuition_stats.json）")
    print()
    print("各招生计划文件（仅本科批次）:")
    for k, v in file_stats.items():
        print(f"  {k:<42} 本科 {v['rows_undergrad']:>6} / 总 {v['rows_total']:>6}"
              f"  命中 {v['rows_matched_major_or_class']:>6}  无专业名 {v['rows_missing_major_name']:>6}")
    print()

    # ── 校验 ──
    errs = []
    codes = [r["code"] for r in rows]
    dup = [c for c, n in Counter(codes).items() if n > 1]
    if dup:
        errs.append(f"code 重复 {len(dup)} 个: {dup[:10]}")
    if len(rows) != 938:
        errs.append(f"行数 {len(rows)} ≠ 938")
    for f in ("name", "code", "category"):
        bad = [r["name"] for r in rows if not str(r.get(f) or "").strip()]
        if bad:
            errs.append(f"`{f}` 为空 {len(bad)} 行: {bad[:5]}")
    flds = set(rows[0].keys())
    model_fields = {"name", "code", "category", "first_class", "degree", "tuition",
                    "ownership", "duration", "campus", "is_category", "single_subject_req",
                    "language_req", "gender_req", "interview_required"}
    extra = {"menlei", "class_name"}          # 模型无此两列，供口径切换/追溯
    if not model_fields <= flds:
        errs.append(f"缺少模型字段: {sorted(model_fields - flds)}")
    if flds - model_fields != extra:
        errs.append(f"额外字段不符（应恰为 {sorted(extra)}）: {sorted(flds - model_fields)}")

    if errs:
        print("⚠️ 校验告警:")
        for e in errs:
            print("   -", e)
    else:
        print("✅ 校验通过：938 行 / code 唯一 / 14 个模型字段齐备"
              f"（另带 {len(extra)} 个追溯字段，② 可忽略）")

    if args.check:
        print("(--check，未写出文件)")
        return 0

    payload = {
        "meta": {
            "generated_at": str(date.today()),
            "owner": "徐（③ 数据工程）",
            "target_table": "major",
            "target_model": "backend/app/models/base_data.py :: Major",
            "purpose": "让 ② 的 loader 可直接按字段名灌入，无需再做字段映射",
            "row_rule": "845 专业行（is_category=False）+ 93 专业类行（is_category=True）= 938 行",
            "why_938": (
                "录取分 116,036 行中 10,817 行为「按大类招生」，专业标识是 4 位类码；"
                "补入 93 个类行后 major_id 可 100% 解析（实测落空 0）。"
            ),
            "rationale": {
                "category": (
                    f"本次取值来源 = {args.category_source}。★ 口径有争议："
                    "前端契约 mocks/index.ts 示例 category='工学'（学科门类），"
                    "但 constraints.py:125 用 `PhysicalRestriction.major_category == major.category` "
                    "做体检匹配，而体检规则的 major_category 取值全是专业类（医学类/美术学类…）。"
                    "二选一必有一处失配，已登记待裁；切换只需 --category-source。"
                ),
                "degree": "← 目录中显式加注的 96 条；未加注留空，不按门类推断。",
                "duration": "← 招生计划本科批次众数，归一为中文（四年/五年…），依据演示种子 duration=\"四年\"。",
                "tuition": "不填单值：同专业学费跨 0～190,000，见 major_tuition_stats.json。",
                "ownership/campus/single_subject_req/language_req/gender_req/interview_required":
                    "校×专业属性，属 enrollment_rule（D3），不在专业字典内。",
                "first_class": "模型注释为「是否一流本科专业建设点」，③ 无来源 → 留空。",
            },
            "extra_fields_note": (
                "`menlei` / `class_name` 两列模型没有，仅为口径切换与追溯保留；"
                "② 灌数时按模型字段白名单取值即可，忽略它们。"
            ),
            "counts": stats,
            "source_major_catalog": data["meta"].get("source_url"),
            "source_catalog_id": data["meta"].get("source_id"),
            "tuition_stats_file": "data/majors/major_tuition_stats.json",
            # ★ 文件级来源三要素：供 validate.py 做「整表级来源」回退
            #   （major 属基础字典，模型无 source_id 列；三要素只在校验层生效）
            "source_name": src["source_name"],
            "source_url": src["source_url"],
            "year": src["year"],
            "source_scope_note": (
                "本表由两份来源合成：专业代码/名称/门类/学位注 ← 教育部本科专业目录（2025，"
                f"{data['meta'].get('source_id')}）；学制 ← 招生计划 CSV（{src['source_id']}）。"
                "major 属基础字典，模型无 source_id 列，故来源登记在 meta 层。"
            ),
            "excluded": {
                "2024_henan_enrollment_plan": "本科批次 major_name / major_code / university_code 整列为空，无法归到专业。",
                "专科批次": "所有文件的专科/高职批均已排除（本科专业字典不含专科专业）。",
            },
            "generator": "data/scripts/build_major_table.py",
        },
        "rows": rows,
    }
    OUT_ROWS.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    tstats = write_tuition_stats(tui, data["majors"], src)
    OUT_TUITION.write_text(json.dumps(tstats, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"✅ 已写出 {OUT_ROWS.relative_to(ROOT)}（{len(rows)} 行）")
    print(f"✅ 已写出 {OUT_TUITION.relative_to(ROOT)}（{len(tstats['stats'])} 个专业的学费分布）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
