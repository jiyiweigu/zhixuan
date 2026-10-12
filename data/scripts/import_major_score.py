#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""院校专业录取分导入脚本（school_major_score 表）

数据来源：Gaokao-Compass-11M 数据集的 major-admission.csv（专业级）
          + school-admission.csv（院校专业组级，用于补齐组级 min_score）
目标表：`school_major_score`（产品书第 7 章）
        字段：id, school_id, major_id, province, year, batch, pathway_id,
              subject_type, min_score, min_rank, avg_score, plan_count, source_id
        索引：(province, year, batch, pathway_id)

★ 本脚本遵循队长《数据源与数据获取方案》与产品书口径：
  - **首期只做本科批**（专科批院校不在 1367 所本科院校库内，无法挂 school_id）
  - **按可用性分级标注**，不静默丢弃、不编造

字段映射
    数据集字段            目标字段        说明
    province              province        直取
    year                  year            转 int
    category              subject_type    ★ 口径断裂：老高考「文科/理科」vs 新高考「物理类/历史类」
    batch                 batch           直取（★ 必须保留，见下）
    major_group           -               归一化去括号后随质量字段留存
    major_code            major_code      用于未来挂 major_id
    major_name            major_name      用于未来挂 major_id
    min_score             min_score       直取
    min_rank              min_rank        位次
    avg_score             avg_score       直取（大量缺失）
    admit_count           admit_count     录取人数（非 plan_count！plan_count 取 enrollment-plan）
    (university_code)     school_id       经院校库「河南代号/校名」映射；映射不上标空 + flag

关键口径（红线）
  1. **不得跨考试制度比较**：老高考「理科」与新高考「物理类」不是同一群体。
  2. **不得合并批次**：本科一批/二批是同一投档序列的两段，批次线不同。
  3. `max_score` **不落库**（第 7 章无此字段，且原始数据近乎全空）。
  4. `admit_count` ≠ `plan_count`：前者是实际录取数，后者是招生计划数，
     计划数在 enrollment-plan.csv 中，不在此表混填。

★ 已识别的脏数据（按可用性分级，见 §quality）
  - 2023 河南 major-admission：`university_code` 与 `university_name` 整列全空 → **unusable**，跳过
  - 2023 江西 major-admission：`min_score` / `min_rank` 整列全空（31997/31997）→ **unusable**，跳过
  - 2024 河南 / 2024 江西 major-admission：`category` 整列空（=<NA>），但分数/位次/校名均完整
    → **正常导入**，`subject_type` 置空并打 `subject_type_missing` flag（科类留待②确认）
  - 2024 江西：`university_name` 整列空，但 `university_code` 完整 → 用代号映射院校，可修复
  - `max_score`：几乎全表空；`avg_score`：8 个文件中 5 个全空 → 不落库 / 落库即为 null

用法：
  python data/scripts/import_major_score.py --scan
  python data/scripts/import_major_score.py
  python data/scripts/import_major_score.py --province 河南 --year 2024
  python data/scripts/import_major_score.py --keep-prep --keep-art   # 额外保留提前批/艺术类
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "school_major_score"
SCHOOLS = ROOT / "data" / "schools" / "schools_merged.json"

FIRST_NEW_GAOKAO = {"河南": 2025, "江西": 2024}

CHANNEL = {
    "source_name": "河南省教育考试院 / 江西省教育考试院（上游）",
    "dataset": "Gaokao-Compass-11M",
    "dataset_doi": "10.57967/hf/9882",
    "source_id": "SRC-GAOKAO-COMPASS",
}

# 整表不可用的 (province, year) —— 见模块 docstring
UNUSABLE_FILES = {
    ("河南", 2023): "university_code 与 university_name 整列全空，无法定位院校",
    ("江西", 2023): "min_score 与 min_rank 整列全空（31997/31997），无分数无位次",
}

# 院校代号所在列：河南为省代号（4 位，需 zfill(4)），江西为省代号（4 位，靠校名反查）
PROVINCE_EN = {"henan": "河南", "jiangxi": "江西"}


# ─────────────────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────────────────

def to_int(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def to_float(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def has_number(v) -> bool:
    """区分「真空」与「<NA> / 空白」——<NA> 也算缺失。"""
    s = str(v or "").strip()
    if not s or s.upper() in {"<NA>", "NA", "N/A", "NULL", "NONE"}:
        return False
    try:
        float(s)
        return True
    except ValueError:
        return False


def exam_system_of(province: str, year: int) -> str:
    first = FIRST_NEW_GAOKAO.get(province)
    if first is None:
        return "unknown"
    return "3+1+2" if year >= first else "文理科"


def normalize_group_code(v) -> str:
    """'（101）' / '(101)' / '101' → '101'"""
    return re.sub(r"^[（(]|[）)]$", "", (v or "").strip()).strip()


def is_benke(batch: str) -> bool:
    """是否本科批（含本科一批/二批/本科批/本科提前批…）"""
    b = (batch or "").strip()
    if "专" in b:            # 专科批 / 专科提前批
        return False
    return "本" in b


def category_is_art_sports(cat: str) -> bool:
    return any(k in (cat or "") for k in ("艺术", "体育", "艺"))


def normalize_school_name(name: str) -> str:
    """院校名归一化：仅处理**确定无歧义**的书写差异，不做任何猜测性改名。

    1. 全角括号 → 半角
    2. 去掉所有空格
    3. 去掉结尾的「学院/大学」不带——不改语义后缀

    ⚠️ 明确**不做**的事：不把「XX学院」猜成「XX大学」，不拆分/合并院校。
    那些属于院校改名，必须逐条核实（见 rename 表），不得自动推断。
    """
    s = (name or "").strip()
    s = s.replace("（", "(").replace("）", ")")
    s = re.sub(r"\s+", "", s)
    return s


# ─────────────────────────────────────────────────────────
# 院校索引
# ─────────────────────────────────────────────────────────

class SchoolIndex:
    """把院校库构造成两套可映射索引：河南省代号 / 校名。"""

    def __init__(self, path: Path):
        data = json.loads(path.read_text(encoding="utf-8"))
        self.records = data.get("records", [])
        self.unmatched = data.get("unmatched", [])
        # 河南省代号（_henan_code，唯一）
        self.by_henan_code: dict[str, int] = {}
        # 校名 → id（取首个；重名极少）
        self.by_name: dict[str, int] = {}
        # 归一化校名 → id（用于吸收括号/空格差异）
        self.by_norm_name: dict[str, int] = {}
        for r in self.records:
            hc = str(r.get("_henan_code") or "").strip()
            if hc:
                self.by_henan_code[hc] = r["id"]
            nm = (r.get("name") or "").strip()
            if nm and nm not in self.by_name:
                self.by_name[nm] = r["id"]
            nn = normalize_school_name(nm)
            if nn and nn not in self.by_norm_name:
                self.by_norm_name[nn] = r["id"]
        # 在籍院校 id 集合（用于校验映射结果确实在库内）
        self.valid_ids = {r["id"] for r in self.records}

    def resolve_henan(self, code: str) -> int | None:
        c = (code or "").strip()
        if not c:
            return None
        return self.by_henan_code.get(c.zfill(4))

    def resolve_name(self, name: str) -> int | None:
        nm = (name or "").strip()
        if not nm:
            return None
        if nm in self.by_name:
            return self.by_name[nm]
        # 退化到归一化匹配（仅吸收括号全半角/空格差异）
        return self.by_norm_name.get(normalize_school_name(nm))


# ─────────────────────────────────────────────────────────
# 每省每年代号 → 校名 反查表（用于江西这类无国标码的场景）
# 依据：同一省内招生代号稳定；用有校名的年份反推无校名年份
# ─────────────────────────────────────────────────────────

def build_code_name_map(province: str) -> dict[str, str]:
    """跨该省所有年份，收集 招生代号 → 校名。"""
    m: dict[str, str] = {}
    for p in sorted(RAW.glob(f"*_{'henan' if province == '河南' else 'jiangxi'}_major-admission.csv")):
        with p.open(encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                c = (r.get("university_code") or "").strip()
                nm = (r.get("university_name") or "").strip()
                if c and nm and nm.upper() != "<NA>":
                    m.setdefault(c, nm)
    return m


# ─────────────────────────────────────────────────────────
# 发现文件
# ─────────────────────────────────────────────────────────

def discover() -> list[tuple[str, int, Path]]:
    out = []
    for p in sorted(RAW.glob("*_major-admission.csv")):
        parts = p.stem.split("_", 2)
        if len(parts) != 3:
            continue
        year_s, prov_en, _ = parts
        if not year_s.isdigit():
            continue
        province = PROVINCE_EN.get(prov_en)
        if province is None:
            continue
        out.append((province, int(year_s), p))
    return out


# ─────────────────────────────────────────────────────────
# 单文件导入
# ─────────────────────────────────────────────────────────

def import_one(province: str, year: int, path: Path, idx: SchoolIndex,
               keep_prep: bool, keep_art: bool) -> tuple[list[dict], dict]:
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    es = exam_system_of(province, year)
    code2name = build_code_name_map(province)

    out: list[dict] = []
    flags = Counter()
    skipped = Counter()
    unresolved_codes: set[str] = set()
    subject_type_missing = 0
    score_missing = 0

    for r in rows:
        batch = (r.get("batch") or "").strip()
        cat = (r.get("category") or "").strip()

        # ── 批次过滤：首期只做本科批 ──
        if not is_benke(batch):
            skipped["non_benke"] += 1
            continue
        if "提前" in batch and not keep_prep:
            skipped["prep_batch"] += 1
            continue
        if category_is_art_sports(cat) and not keep_art:
            skipped["art_sports"] += 1
            continue

        # ── 院校映射 ──
        raw_code = (r.get("university_code") or "").strip()
        raw_name = (r.get("university_name") or "").strip()
        if raw_name.upper() == "<NA>":
            raw_name = ""

        school_id = None
        match_via = None
        if province == "河南":
            school_id = idx.resolve_henan(raw_code)
            match_via = "henan_code"
        # 江西：招生代号非国标码，靠「代号→校名」反查再对院校库校名
        if school_id is None:
            nm = raw_name or code2name.get(raw_code, "")
            if nm:
                school_id = idx.resolve_name(nm)
                match_via = "name"
        if school_id is None and raw_code:
            unresolved_codes.add(raw_code)

        # ── 分数 / 位次 ──
        min_score = to_float(r.get("min_score")) if has_number(r.get("min_score")) else None
        min_rank = to_int(r.get("min_rank")) if has_number(r.get("min_rank")) else None
        avg_score = to_float(r.get("avg_score")) if has_number(r.get("avg_score")) else None
        admit_count = to_int(r.get("admit_count")) if has_number(r.get("admit_count")) else None

        if min_score is None:
            score_missing += 1

        # ── subject_type：2024 两省整列为空 ──
        subject_type = cat if cat and cat.upper() != "<NA>" else ""
        if not subject_type:
            subject_type_missing += 1

        out.append({
            # ── 目标表字段 ──
            "school_id": school_id,
            "major_id": None,                 # 专业库未建（2.1），暂空
            "province": province,
            "year": year,
            "batch": batch,
            "pathway_id": None,               # 普通本科批 → 无途径；专项批随 batch 待到
            "subject_type": subject_type,
            "min_score": min_score,
            "min_rank": min_rank,
            "avg_score": avg_score,
            "source_id": CHANNEL["source_id"],
            # ── 轻量留存（未入第7章正式列，供 ② 挂 major_id 用） ──
            "major_code": (r.get("major_code") or "").strip() or None,
            "major_name": (r.get("major_name") or "").strip() or None,
            "major_note": (r.get("major_note") or "").strip() or None,
            "group_code": normalize_group_code(r.get("major_group")) or None,
            "admit_count": admit_count,       # 实际录取数，≠ plan_count
            # ── 质量/溯源 ──
            "match_via": match_via,
            "exam_system": es,
            "confidence": "channel",
            "data_status": "pending",
            "source_name": CHANNEL["source_name"],
            "source_url": "",
        })

    # ── 文件级质量判定 ──
    n = len(out)
    matched = sum(1 for x in out if x["school_id"])
    quality_flags: list[str] = []
    if n and matched / n < 0.5:
        quality_flags.append("low_school_id_match")
    if n and score_missing / n > 0.5:
        quality_flags.append("score_mostly_missing")
        quality_flags.append("unusable")
    if n and subject_type_missing == n:
        quality_flags.append("subject_type_missing")

    stats = {
        "province": province,
        "year": year,
        "exam_system": es,
        "source_file": path.name,
        "source_rows": len(rows),
        "imported_rows": n,
        "skipped": dict(skipped),
        "school_id_matched": matched,
        "school_id_match_rate": round(matched / n, 4) if n else 0.0,
        "unresolved_school_codes": len(unresolved_codes),
        "subject_type_missing": subject_type_missing,
        "min_score_missing": score_missing,
        "batch_dist": dict(Counter(x["batch"] for x in out)),
        "quality_flags": quality_flags,
        "data_status": "pending",
    }
    return out, stats


# ─────────────────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--province")
    ap.add_argument("--year", type=int)
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--keep-prep", action="store_true", help="额外保留提前批")
    ap.add_argument("--keep-art", action="store_true", help="额外保留艺术/体育类")
    args = ap.parse_args()

    items = discover()
    if args.province:
        items = [i for i in items if i[0] == args.province]
    if args.year:
        items = [i for i in items if i[1] == args.year]

    if args.scan:
        print(f"发现 {len(items)} 个专业录取分文件：")
        for prov, yr, p in items:
            bad = UNUSABLE_FILES.get((prov, yr))
            tag = f"  ⚠ 不可用：{bad}" if bad else ""
            print(f"  {prov} {yr} ({exam_system_of(prov, yr)})  {p.name}{tag}")
        return 0

    if not SCHOOLS.exists():
        print(f"✗ 院校库不存在：{SCHOOLS}", file=sys.stderr)
        return 2
    idx = SchoolIndex(SCHOOLS)
    print(f"院校库：{len(idx.records)} 所（河南代号 {len(idx.by_henan_code)}，"
          f"校名 {len(idx.by_name)}）\n")

    all_stats = []
    OUT.mkdir(parents=True, exist_ok=True)

    for prov, yr, p in items:
        bad = UNUSABLE_FILES.get((prov, yr))
        if bad:
            print(f"  ⊘ {prov} {yr} 跳过（整表不可用）：{bad}")
            all_stats.append({
                "province": prov, "year": yr, "exam_system": exam_system_of(prov, yr),
                "source_file": p.name, "imported_rows": 0,
                "skipped": {"unusable_whole_file": 1},
                "quality_flags": ["unusable"], "unusable_reason": bad,
                "data_status": "pending",
            })
            continue

        segs, st = import_one(prov, yr, p, idx, args.keep_prep, args.keep_art)
        fn = OUT / f"school_major_score_{yr}_{prov}.json"
        fn.write_text(json.dumps({
            "meta": {
                "title": f"{prov}省 {yr} 年院校专业录取分（{'新高考' if st['exam_system'] == '3+1+2' else '老高考'}）",
                "target_table": "school_major_score",
                "province": prov, "year": yr,
                "exam_system": st["exam_system"],
                "source_id": CHANNEL["source_id"],
                "source_name": CHANNEL["source_name"],
                "dataset": CHANNEL["dataset"],
                "dataset_doi": CHANNEL["dataset_doi"],
                "scope_note": "首期仅本科批（专科批院校不在院校库内，无法挂 school_id）。",
                "batch_note": "★ 不得合并批次：本科一批/二批的批次线与投档序列不同。",
                "subject_type_note": "老高考为文科/理科，新高考为物理类/历史类，不可跨制度比较。",
                "admit_count_note": "admit_count 为实际录取数，≠ plan_count（招生计划数）。",
                "data_status": "pending",
                "verified_note": "渠道来源，未逐条对官方核实。核实通过后才可升 available。",
                "quality_flags": st.get("quality_flags", []),
            },
            "scores": segs,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        st["file"] = str(fn.relative_to(ROOT))
        all_stats.append(st)
        print(f"  ✓ {prov} {yr} ({st['exam_system']}) 导入 {st['imported_rows']:>6} 行 "
              f"| 院校命中 {st['school_id_match_rate']*100:5.1f}% "
              f"| 跳过 {st['skipped']} "
              f"| flags={st['quality_flags']}")

    rep = {
        "meta": {
            "generated_at": "2026-10-12",
            "owner": "徐（③ 数据工程）",
            "target_table": "school_major_score",
            "purpose": "院校专业录取分：供 ② 的冲稳保推荐与位次换算使用。",
            "scope": "首期仅本科批（队长《数据源与数据获取方案》+ 产品书口径）",
            "dataset": CHANNEL["dataset"],
            "dataset_doi": CHANNEL["dataset_doi"],
        },
        "summary": {
            "files": len(all_stats),
            "total_imported_rows": sum(s.get("imported_rows", 0) for s in all_stats),
            "unusable_files": [f"{s['province']}{s['year']}" for s in all_stats
                               if "unusable" in s.get("quality_flags", [])],
            "total_unresolved_school_codes_hint": "见各文件 unresolved_school_codes",
        },
        "files": all_stats,
    }
    (OUT / "_major_score_import_report.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n合计导入 {rep['summary']['total_imported_rows']} 行；"
          f"不可用文件：{rep['summary']['unusable_files'] or '无'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
