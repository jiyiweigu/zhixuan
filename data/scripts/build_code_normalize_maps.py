#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""口径归一映射构建（G6 省份码 / G7 批次码 / 科类码）

为什么需要这个脚本
==================
契约 ``docs/api-contract.md`` 与 ③ 采集产物之间存在**四处口径分裂**，
每一处都会让数据灌进去之后「查不到」或「同一批次被当成两个批次」：

1. **省份码**（契约 8.3 / 8.6 / 8.7）
   契约接口与导入使用**两位**省级行政区划代码（河南 ``41``、江西 ``36``）；
   而 ③ 产物使用**六位** GB/T 2260 码（``410000`` / ``360000``），
   且省名同时存在「河南」与「河南省」两种写法
   （``pathway-regions.province_raw`` 即保留了原始写法）。

2. **批次码**（契约 8.3 / 8.7；参见文档 504-505 行）
   ``batch_code`` 是**机器键**、规则表唯一键，``batch`` 仅作展示。
   契约正文明确「各省叫法差异经 ``batch_code`` 归一后不得再区分」。
   而实测数据里同一语义批次有多达 **22 种**中文写法：
   河南「本科一批」/「本科第一批」/ 录取分简称「本一」；
   江西自 2024 年起并入「本科」；专科则有「专科批」/「高职专科批」/
   「高职(专科)」三种叫法。

3. **科类**（模型 ``backend/app/models/base_data.py``
   ``ScoreSegment.subject_type`` 注释为「科类：物理类 / 历史类」）
   老高考数据写「理科 / 文科」，新高考写「物理类 / 历史类」，
   另有艺术类（「艺术文」/「艺术(不分科目类)」）与真脏值
   （2023 河南招生计划出现「科」6 条、「文」3 条）。

4. **考试类型**（契约 8.7：「数据源列名 ``category_group`` 对应契约字段
   ``exam_type``，导入时**必须改名**」，但未给取值归一规则）
   河南写「普通类」，江西写「历史、物理科目组」——按契约唯一键
   ``(province_code, year, batch_code, exam_type)`` 会被当成两种考试类型；
   另有江西「艺术类 / 体育类」一条规则同时覆盖两类考生，与三值枚举冲突。

设计原则（★ 铁律：宁可缺，不可猜）
==================================
- 只做**机械归一**：同一语义的不同写法归到一个码；不做语义推断。
- 无法百分之百确证的归并标 ``confidence="medium"`` / ``"review"`` 并写明 ``caveat``，
  交 ② / 队长复核；``high`` 表示有明确出处或属同一批次的同义写法。
- **映射表不凭空生成**：脚本先扫描全部数据文件收集实际取值，
  再与内置映射表比对，**未覆盖的取值显式报错**，绝不静默通过。
- 扫描源按**语义**精确限定（``SCAN_SPECS``），避免同名列的不同语义数据混入
  （如 ``pathway-regions.category`` 是「专项计划区域类别」，不是科类）。

输出（均含 .json + .csv，csv 用 utf-8-sig 便于 Excel 直接打开）
================================================================
  data/mappings/province-code-map.{json,csv}    省份：中文名 ↔ 2 位 ↔ 6 位
  data/mappings/batch-code-map.{json,csv}       批次：中文原值 → batch_code
  data/mappings/subject-type-map.{json,csv}     科类：理科/文科 → 物理类/历史类
  data/mappings/exam-type-map.{json,csv}        考试类型：category_group → exam_type

用法
====
  python data/scripts/build_code_normalize_maps.py            # 生成 + 校验
  python data/scripts/build_code_normalize_maps.py --check    # 只校验不写文件
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "mappings"

# 各数据文件里「记录数组」可能的顶层键名
ARRAY_KEYS = (
    "rows", "scores", "records", "items", "segments",
    "rules", "regions", "pathways", "data",
)

# ★ 每类口径的扫描源：(glob 模式, 候选键名)。
#   必须按**语义**精确限定来源，否则同名列的不同语义数据会串进来：
#   例如 `pathway-regions.json` 的 `category` 是「专项计划区域类别」
#   （国家级扶贫开发重点县 / 集中连片特困县…），并非高考科类。
SCAN_SPECS: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "province": [
        ("data/raw/*_enrollment-plan.csv", ("province",)),
        ("data/school_major_score/*.json", ("province",)),
        ("data/score_segment/*.json", ("province",)),
        ("data/dictionaries/province-exam-rule.json", ("province",)),
        ("data/dictionaries/pathway-eligibility.json", ("province",)),
        ("data/dictionaries/pathway-regions.json", ("province", "province_raw")),
    ],
    "batch": [
        ("data/raw/*_enrollment-plan.csv", ("batch",)),
        ("data/school_major_score/*.json", ("batch",)),
        ("data/score_segment/*.json", ("batch",)),
        ("data/dictionaries/province-exam-rule.json", ("batch",)),
    ],
    "subject": [
        ("data/raw/*_enrollment-plan.csv", ("category",)),          # 招生计划列名
        ("data/school_major_score/*.json", ("subject_type",)),
        ("data/score_segment/*.json", ("subject_type",)),
    ],
    "exam_type": [
        # 契约 8.7：「数据源列名 category_group 对应契约字段 exam_type，导入时必须改名」
        ("data/dictionaries/province-exam-rule.json", ("category_group",)),
    ],
}

# ══════════════════════════════════════════════════════════════════════
# 1. 省级行政区划（GB/T 2260，31 个高考招生省级行政区）
#    —— 2 位码 = 契约接口口径；6 位码 = ③ 现有产物口径
# ══════════════════════════════════════════════════════════════════════
PROVINCES: list[tuple[str, str, str, list[str]]] = [
    #  2位    6位      全称              别名（含全称 / 简称 / 常见缩写）
    ("11", "110000", "北京市",     ["北京", "北京市"]),
    ("12", "120000", "天津市",     ["天津", "天津市"]),
    ("13", "130000", "河北省",     ["河北", "河北省"]),
    ("14", "140000", "山西省",     ["山西", "山西省"]),
    ("15", "150000", "内蒙古自治区", ["内蒙古", "内蒙古自治区", "內蒙古"]),
    ("21", "210000", "辽宁省",     ["辽宁", "辽宁省"]),
    ("22", "220000", "吉林省",     ["吉林", "吉林省"]),
    ("23", "230000", "黑龙江省",   ["黑龙江", "黑龙江省"]),
    ("31", "310000", "上海市",     ["上海", "上海市"]),
    ("32", "320000", "江苏省",     ["江苏", "江苏省"]),
    ("33", "330000", "浙江省",     ["浙江", "浙江省"]),
    ("34", "340000", "安徽省",     ["安徽", "安徽省"]),
    ("35", "350000", "福建省",     ["福建", "福建省"]),
    ("36", "360000", "江西省",     ["江西", "江西省"]),
    ("37", "370000", "山东省",     ["山东", "山东省"]),
    ("41", "410000", "河南省",     ["河南", "河南省"]),
    ("42", "420000", "湖北省",     ["湖北", "湖北省"]),
    ("43", "430000", "湖南省",     ["湖南", "湖南省"]),
    ("44", "440000", "广东省",     ["广东", "广东省"]),
    ("45", "450000", "广西壮族自治区", ["广西", "广西壮族自治区", "广西省"]),
    ("46", "460000", "海南省",     ["海南", "海南省"]),
    ("50", "500000", "重庆市",     ["重庆", "重庆市"]),
    ("51", "510000", "四川省",     ["四川", "四川省"]),
    ("52", "520000", "贵州省",     ["贵州", "贵州省"]),
    ("53", "530000", "云南省",     ["云南", "云南省"]),
    ("54", "540000", "西藏自治区", ["西藏", "西藏自治区"]),
    ("61", "610000", "陕西省",     ["陕西", "陕西省"]),
    ("62", "620000", "甘肃省",     ["甘肃", "甘肃省"]),
    ("63", "630000", "青海省",     ["青海", "青海省"]),
    ("64", "640000", "宁夏回族自治区", ["宁夏", "宁夏回族自治区", "宁夏省"]),
    ("65", "650000", "新疆维吾尔自治区", ["新疆", "新疆维吾尔自治区", "新疆省"]),
]

# ══════════════════════════════════════════════════════════════════════
# 2. 批次码归一表
#    推荐口径：**跨省语义码**（契约 504-505 行「归一后不得再区分」为强制要求）
#    confidence: high  = 同批次的同义写法 / 有明确出处
#                medium = 归并合理但需 ②/队长复核
# ══════════════════════════════════════════════════════════════════════
BATCH_MAP: dict[str, tuple[str, str, str, str, str]] = {
    # 原值（中文/官方写法）: (batch_code, level, 统一展示名, confidence, 说明)
    # ── 本科 · 普通批（新高考合并批）──
    "本科":              ("undergraduate_regular", "本科", "普通本科批", "high",
                          "江西 2024 起新高考本科批次合并后的官方批次名"),
    "本科批":            ("undergraduate_regular", "本科", "普通本科批", "high",
                          "河南 2025 新高考本科批（一分一段 / 招生计划 / 录取分同用）"),
    "本科批次":          ("undergraduate_regular", "本科", "普通本科批", "high",
                          "江西省教育考试院官方叫法；与河南「普通本科批」同批"),
    "普通本科批":        ("undergraduate_regular", "本科", "普通本科批", "high",
                          "河南省教育考试院 2025 官方叫法"),
    # ── 本科 · 老高考一批 ──
    "本科一批":          ("undergraduate_first", "本科", "本科一批", "high", ""),
    "本科第一批":        ("undergraduate_first", "本科", "本科一批", "high",
                          "河南 2023 招生计划写法，与「本科一批」同批"),
    "本一":              ("undergraduate_first", "本科", "本科一批", "medium",
                          "2024 河南录取分文件的简称写法；需 ② 确认无其他含义"),
    # ── 本科 · 老高考二批 ──
    "本科二批":          ("undergraduate_second", "本科", "本科二批", "high", ""),
    "本科第二批":        ("undergraduate_second", "本科", "本科二批", "high",
                          "河南 2023 招生计划写法，与「本科二批」同批"),
    "本二":              ("undergraduate_second", "本科", "本科二批", "medium",
                          "2024 河南录取分文件的简称写法；需 ② 确认无其他含义"),
    # ── 本科 · 提前批 ──
    "本科提前批":        ("undergraduate_early", "本科", "普通本科提前批", "high",
                          "河南 2024 招生计划写法"),
    "提前本科":          ("undergraduate_early", "本科", "普通本科提前批", "medium",
                          "江西 2024/2025 招生计划写法；疑为「提前批本科」的倒装，需 ② 确认"),
    "普通本科提前批":    ("undergraduate_early", "本科", "普通本科提前批", "high",
                          "河南省教育考试院 2025 官方叫法"),
    # ── 本科 · 特殊类型选拔 ──
    "高校特殊选拔本科":  ("undergraduate_special", "本科", "特殊类型选拔本科", "medium",
                          "江西 2024/2025 招生计划写法（高校专项 / 高水平艺术团等），需 ② 确认归并口径"),
    # ── 本科 · 艺术体育 ──
    "艺术类/体育类本科批次": ("undergraduate_art_sport", "本科", "艺术类/体育类本科批", "high",
                          "江西省教育考试院 2026 规则文件叫法"),
    # ── 专科 · 普通批 ──
    "专科批":            ("vocational_regular", "专科", "高职（专科）批", "high", ""),
    "高职专科批":        ("vocational_regular", "专科", "高职（专科）批", "high",
                          "河南 2023 招生计划写法"),
    "高职(专科)":        ("vocational_regular", "专科", "高职（专科）批", "high",
                          "江西 2024/2025 招生计划写法（半角括号）"),
    "高职（专科）批":    ("vocational_regular", "专科", "高职（专科）批", "high",
                          "江西省教育考试院官方叫法（全角括号）"),
    "高职（专科）批次":  ("vocational_regular", "专科", "高职（专科）批", "high",
                          "江西省教育考试院官方叫法（全角括号 + 批次）"),
    "普通高职（专科）批": ("vocational_regular", "专科", "高职（专科）批", "high",
                          "河南省教育考试院 2025 官方叫法"),
    # ── 专科 · 提前批 ──
    "提前高职(专科)":    ("vocational_early", "专科", "高职（专科）提前批", "medium",
                          "江西 2024/2025 招生计划写法；需 ② 确认与本科提前批的分立口径"),
}

# 空批次：非映射问题，属数据缺失，单列说明（不猜）
BATCH_MISSING_NOTE = (
    "空值不是映射问题而是**数据缺失**，按铁律「宁可缺，不可猜」保持原样，"
    "不得反推批次。实测出现在："
    "① score_segment_2026_物理类/历史类（共 916 行，全部无批次，且整表缺来源三要素）；"
    "② score_segment_2022_江西（1,500 行）。"
)

# ══════════════════════════════════════════════════════════════════════
# 3. 科类归一表
#    推荐口径：模型注释口径「物理类 / 历史类」；艺术类单列
# ══════════════════════════════════════════════════════════════════════
SUBJECT_MAP: dict[str, tuple[str, str, bool, str]] = {
    # 原值: (归一值, 展示名, 是否严格等价, 说明)
    "物理类": ("物理类", "物理类", True, "新高考首选物理，原样保留"),
    "历史类": ("历史类", "历史类", True, "新高考首选历史，原样保留"),
    "理科":   ("物理类", "物理类", False,
               "★ 非严格等价：老高考「理科」= 理化生固定组合，新高考「物理类」= 首选物理 + 2 门任选。"
               "仅可用于「同一序列的历年趋势对比」，**不得**当作同一科类做位次直接换算或投档规则复用。"),
    "文科":   ("历史类", "历史类", False,
               "★ 非严格等价：老高考「文科」= 政史地固定组合，新高考「历史类」= 首选历史 + 2 门任选。"
               "同上，仅可用于趋势对比。"),
    "艺术文": ("艺术类", "艺术类", True,
               "2024 河南招生计划出现 4 条；艺术类单列，不并入普通文理"),
    "艺术(不分科目类)": ("艺术类", "艺术类", True,
               "2025 江西招生计划出现 647 条；官方已声明「不分科目类」，艺术类单列"),
    # ── 真脏值：无法判断，不归一 ──
    "科": ("__INVALID__", "__INVALID__", False,
           "2023 河南招生计划 6 条，疑为「理科」被截断。**不猜**，标为脏值待重采"),
    "文": ("__INVALID__", "__INVALID__", False,
           "2023 河南招生计划 3 条，疑为「文科」被截断。**不猜**，标为脏值待重采"),
}

SUBJECT_MISSING_NOTE = (
    "空科类同样属**数据缺失**，不得由分数反推（已在《录取分导入说明》§4 记录）。实测出现在："
    "school_major_score_2024_河南（31,214 行）与 school_major_score_2024_江西（22,781 行）"
    "两表 subject_type **整列为空**。"
)

# ══════════════════════════════════════════════════════════════════════
# 4. 考试类型（exam_type）归一表
#    契约 8.7：「数据源列名 `category_group` 对应契约字段 `exam_type`，导入时必须改名」
#    契约 8.3 示例 exam_type = "普通"；模型 profile.py 注释「普通 / 艺术 / 体育」
# ══════════════════════════════════════════════════════════════════════
EXAM_TYPE_MAP: dict[str, tuple[str | None, str, str]] = {
    # 原值(category_group): (推荐 exam_type, confidence, 说明)
    "普通类": ("普通", "high",
               "河南省教育考试院官方叫法；与契约 8.3 示例 `exam_type=\"普通\"` 一致"),
    "历史、物理科目组": ("普通", "medium",
                         "江西普通类按首选科目划分为历史/物理科目组，其考试类型仍为**普通**；"
                         "与河南「普通类」同义，需 ② 确认「科目组」信息是否另有承载字段"
                         "（若并入 exam_type 会与契约枚举冲突）"),
    "艺术类 / 体育类": (None, "review",
                        "★ 该规则同时覆盖艺术与体育两类考生，而契约/模型枚举为**三值**"
                        "（普通 / 艺术 / 体育），无「艺术体育」合并值。"
                        "建议 ② 把该规则**拆为两条**（exam_type=艺术 / 体育），"
                        "或由队长放宽枚举。**不擅自归并**，列入待裁项。"),
}


# ══════════════════════════════════════════════════════════════════════
# 扫描：收集数据里实际出现的取值
# ══════════════════════════════════════════════════════════════════════
def _load_rows(path: Path) -> tuple[list[dict], dict]:
    """返回 (记录数组, 文件级 meta)。兼容 CSV 与多种 JSON 包装键。"""
    if path.suffix.lower() == ".csv":
        with open(path, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f)), {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data, {}
    for key in ARRAY_KEYS:
        if isinstance(data.get(key), list):
            meta = {k: v for k, v in data.items() if k != key}
            return data[key], meta
    return [], data if isinstance(data, dict) else {}


def _pick(row: dict, *keys: str) -> str:
    for k in keys:
        if k in row and row[k] is not None:
            return str(row[k]).strip()
    return ""


def scan_source_data() -> dict:
    """按 SCAN_SPECS 逐类扫描，统计各口径的实际取值与出现文件。"""
    all_files: set[str] = set()
    result: dict = {}

    for kind, specs in SCAN_SPECS.items():
        hits: dict[str, set[str]] = collections.defaultdict(set)
        counts: collections.Counter = collections.Counter()
        for pattern, keys in specs:
            for path in sorted(ROOT.glob(pattern)):
                if path.name.startswith("."):
                    continue          # 跳过 .ocrcache_* 等隐藏缓存，它们不是事实数据
                rel = path.relative_to(ROOT).as_posix()
                all_files.add(rel)
                rows, meta = _load_rows(path)
                if not rows:
                    continue
                per_file: collections.Counter = collections.Counter()
                primary = keys[0]
                for row in rows:
                    per_file[_pick(row, primary)] += 1
                    # 次要键（如 province_raw 保留的原始写法）只贡献「出现文件」，
                    # 用于覆盖率核对，不与主键重复计数
                    for k in keys[1:]:
                        v = str(row.get(k) or "").strip()
                        if v:
                            hits[v].add(rel)
                for value, n in per_file.items():
                    hits[value].add(rel)
                    counts[value] += n
                # 文件级 meta（如 pathway-regions 记录的原始省名）只贡献「出现文件」
                for k in keys:
                    mv = str(meta.get(k) or "").strip()
                    if mv:
                        hits[mv].add(rel)
        result[kind] = {"hits": hits, "counts": counts}

    result["files"] = sorted(all_files)
    return result


# ══════════════════════════════════════════════════════════════════════
# 构建三张映射表
# ══════════════════════════════════════════════════════════════════════
def build_province_map(scan: dict, today: str) -> tuple[dict, list[str]]:
    errors: list[str] = []
    alias_index: dict[str, tuple[str, str, str]] = {}
    for code2, code6, full, aliases in PROVINCES:
        for a in aliases:
            alias_index[a] = (code2, code6, full)

    rows = []
    for code2, code6, full, aliases in PROVINCES:
        forms = sorted(a for a in aliases if a in scan["province"]["hits"])
        rows.append({
            "province_code": code2,          # 契约接口口径（2 位）
            "province_code6": code6,         # ③ 产物口径（GB/T 2260 6 位）
            "province_name": full,
            "short_name": aliases[0],
            "aliases": aliases,
            "in_current_data": bool(forms),
            "data_forms": forms,
        })

    # 反向核对：数据里出现的省名是否都能映射
    unmapped = sorted(v for v in scan["province"]["hits"] if v not in alias_index)
    for v in unmapped:
        errors.append(
            f"省份 `{v}` 在数据中出现（{sorted(scan['province']['hits'][v])}），"
            "但不在 GB/T 2260 映射表内 → 需补别名或修正数据"
        )

    covered_prov = sorted({alias_index[v][0] for v in scan["province"]["hits"] if v in alias_index})
    payload = {
        "meta": {
            "title": "省级行政区划三向映射（中文省名 ↔ 2 位码 ↔ 6 位码）",
            "purpose": ("让 ② 在契约接口（2 位码）与 ③ 产物（6 位码 + 中文省名）之间无损转换，"
                        "并识别「河南省 / 河南」这类同省异写"),
            "owner": "徐（③ 数据工程）",
            "generated_at": today,
            "standard": "GB/T 2260《中华人民共和国行政区划代码》",
            "issue": "契约 G6",
            "contract_refs": [
                "docs/api-contract.md 8.3 GET /api/provinces/{code}/rules —— code 为两位码（河南 41、江西 36）",
                "docs/api-contract.md 8.6 GET /api/majors/{id}/requirements —— province 用省级行政区划代码",
                "docs/api-contract.md 8.7 规则表唯一键 —— province_code 同上",
            ],
            "usage": ("① 请求参数：接口要 2 位码 → 取 province_code；"
                      "② 落库：规则类表按契约存 2 位码，事实表（score_segment / school_major_score）"
                      "模型字段是 province 字符串 → 建议统一存**中文简称**（河南 / 江西）；"
                      "③ 名称清洗：用 aliases 把「河南省」归一为「河南」。"),
            "coverage": {
                "provinces_total": len(PROVINCES),
                "provinces_in_current_data": covered_prov,
                "unmapped_names": unmapped,
            },
        },
        "provinces": rows,
        "by_code2": {r["province_code"]: r["province_code6"] for r in rows},
        "by_code6": {r["province_code6"]: r["province_code"] for r in rows},
        "by_name": {a: [c2, c6, full]
                    for c2, c6, full, aliases in PROVINCES for a in aliases},
    }
    return payload, errors


def build_batch_map(scan: dict, rule_codes: dict, today: str) -> tuple[dict, list[str]]:
    errors: list[str] = []
    hits = scan["batch"]["hits"]
    counts = scan["batch"]["counts"]

    rows = []
    for raw in sorted(hits, key=lambda x: (x == "", x)):
        if raw == "":
            rows.append({
                "raw_batch": "", "batch_code": None, "level": None,
                "display_name": None, "confidence": None,
                "in_current_data": True,
                "occurrences": counts.get(raw, 0),
                "evidence_files": sorted(hits[raw]),
                "note": BATCH_MISSING_NOTE,
            })
            continue
        if raw not in BATCH_MAP:
            errors.append(
                f"批次 `{raw}` 在数据中出现（{sorted(hits[raw])}，共 {counts.get(raw, 0)} 行），"
                "但未登记到 BATCH_MAP → 必须显式归并后才可灌数"
            )
            continue
        code, level, disp, conf, note = BATCH_MAP[raw]
        rows.append({
            "raw_batch": raw,
            "batch_code": code,
            "level": level,
            "display_name": disp,
            "confidence": conf,
            "in_current_data": True,
            "occurrences": counts.get(raw, 0),
            "evidence_files": sorted(hits[raw]),
            "note": note,
        })

    # 已登记但当前数据未出现的批次码（保留，供后续年份）
    registered = {v[0] for v in BATCH_MAP.values()}
    appearing = {r["batch_code"] for r in rows if r["batch_code"]}

    # ★ 交叉校验：与 province-exam-rule.json 已登记的 batch_code 必须一致
    for rule_id, (rcode, rbatch) in rule_codes.items():
        if rcode not in registered:
            errors.append(
                f"规则表 {rule_id} 的 batch_code=`{rcode}` 不在归一表登记集合内 → 口径不一致"
            )
        elif rcode not in appearing:
            errors.append(
                f"规则表 {rule_id} 的 batch_code=`{rcode}`（batch=`{rbatch}`）"
                "未被本次扫描覆盖 → 检查映射"
            )

    payload = {
        "meta": {
            "title": "批次码归一映射（中文批次原值 → batch_code）",
            "purpose": ("把各省各年的中文批次叫法归一到跨省语义 batch_code，"
                        "使契约 8.3 / 8.7 的「唯一键」在跨省合并后不产生重复批次"),
            "owner": "徐（③ 数据工程）",
            "generated_at": today,
            "issue": "契约 G7",
            "contract_refs": [
                "docs/api-contract.md 第 38 行：batch_code 是机器键（示例 HE-UG），batch 仅作展示",
                "docs/api-contract.md 8.3：规则表与导入以 batch_code 作唯一键，同一批次的历史别名不得当作不同批次",
                "docs/api-contract.md 504-505 行：各省叫法差异经 batch_code 归一后不得再区分",
            ],
            "decision": ("★ 采用**跨省语义码**（undergraduate_regular 等），不采用带省前缀的 HE-UG 风格。"
                         "理由：504-505 行是强制要求（跨省归一后不得再区分），"
                         "而带省前缀会在同一批次上产生 HE-UG / JX-UG 两个码，正好违反该条。"
                         "契约第 38 行的 `HE-UG` 示例与 504-505 行**自相矛盾**，已列入待裁项 N7。"),
            "naming": {
                "pattern": "{level}_{batch}（下划线小写）",
                "level": {"undergraduate": "本科", "vocational": "高职（专科）"},
                "batch": ["early（提前批）", "first（一批，仅老高考）", "second（二批，仅老高考）",
                          "regular（普通批 / 合并批）", "art_sport（艺术体育）", "special（特殊类型选拔）"],
            },
            "legacy_contract_example": {
                "HE-UG": {"maps_to": "undergraduate_regular", "province": "河南",
                          "note": "契约第 38 行示例；仅在队长选择「省前缀方案」时启用，届时江西为 JX-UG"},
                "note": "其余批次契约未给示例，不臆造省前缀码",
            },
            "coverage": {
                "raw_values_in_data": len([r for r in rows if r["batch_code"]]),
                "batch_codes_registered": len(registered),
                "batch_codes_appearing": sorted(appearing),
                "batch_codes_registered_only": sorted(registered - appearing),
                "unmapped_raw_values": [r["raw_batch"] for r in rows if r["batch_code"] is None and r["raw_batch"]],
            },
        },
        "map": {r["raw_batch"]: r["batch_code"] for r in rows if r["batch_code"]},
        "rows": rows,
        "registered_batch_codes": sorted(registered),
        "display_names": {code: next(v[2] for v in BATCH_MAP.values() if v[0] == code)
                          for code in sorted(registered)},
    }

    # 一致性：同一 batch_code 只允许一个统一展示名
    disp_by_code: dict[str, set] = collections.defaultdict(set)
    for code, _level, disp, _c, _n in BATCH_MAP.values():
        disp_by_code[code].add(disp)
    for code, disps in disp_by_code.items():
        if len(disps) > 1:
            errors.append(f"batch_code `{code}` 出现多个统一展示名 {sorted(disps)} → 需统一")

    return payload, errors


def build_subject_map(scan: dict, today: str) -> tuple[dict, list[str]]:
    errors: list[str] = []
    hits = scan["subject"]["hits"]
    counts = scan["subject"]["counts"]

    rows = []
    for raw in sorted(hits, key=lambda x: (x == "", x)):
        if raw == "":
            rows.append({
                "raw_subject": "", "normalized": None, "display_name": None,
                "equivalent": None, "confidence": None, "occurrences": counts.get(raw, 0),
                "evidence_files": sorted(hits[raw]), "note": SUBJECT_MISSING_NOTE,
            })
            continue
        if raw not in SUBJECT_MAP:
            errors.append(
                f"科类 `{raw}` 在数据中出现（{sorted(hits[raw])}，共 {counts.get(raw, 0)} 行），"
                "但未登记到 SUBJECT_MAP → 必须显式归并后才可灌数"
            )
            continue
        norm, disp, equiv, note = SUBJECT_MAP[raw]
        invalid = norm == "__INVALID__"
        rows.append({
            "raw_subject": raw,
            "normalized": None if invalid else norm,
            "display_name": None if invalid else disp,
            "equivalent": equiv,
            "confidence": "invalid" if invalid else ("high" if equiv else "medium"),
            "occurrences": counts.get(raw, 0),
            "evidence_files": sorted(hits[raw]),
            "note": note,
        })

    invalid_rows = [r for r in rows if r["confidence"] == "invalid"]
    payload = {
        "meta": {
            "title": "科类归一映射（老高考 / 新高考 / 艺术类）",
            "purpose": ("把老高考「理科 / 文科」与新高考「物理类 / 历史类」纳入统一口径，"
                        "使跨年查询与趋势对比可用；同时显式隔离不可归一的脏值"),
            "owner": "徐（③ 数据工程）",
            "generated_at": today,
            "issue": "新发现（非契约原文，模型口径）",
            "evidence": ("backend/app/models/base_data.py："
                         "ScoreSegment.subject_type 注释「科类：物理类 / 历史类」；"
                         "索引 ix_score_segment_lookup = (province, year, subject_type, score)"),
            "decision": ("★ 归并口径为「同一序列的历年趋势对比」，**不是**等价替换："
                         "老高考「理科」为理化生固定组合，新高考「物理类」为首选物理 + 2 门任选，"
                         "二者考生结构不同 ⇒ 位次不可直接换算、投档规则不可复用。"
                         "凡是涉及录取概率预测的接口，必须先按「同年同科类」取数，不得跨口径混用。"),
            "coverage": {
                "raw_values_in_data": len([r for r in rows if r["raw_subject"]]),
                "normalized_values": sorted({r["normalized"] for r in rows if r["normalized"]}),
                "invalid_values": [{"raw": r["raw_subject"], "rows": r["occurrences"]}
                                   for r in invalid_rows],
            },
        },
        "map": {r["raw_subject"]: r["normalized"] for r in rows if r["raw_subject"]},
        "equivalent_flag": {r["raw_subject"]: r["equivalent"] for r in rows if r["raw_subject"]},
        "rows": rows,
    }
    return payload, errors


def build_exam_type_map(scan: dict, today: str) -> tuple[dict, list[str]]:
    errors: list[str] = []
    hits = scan["exam_type"]["hits"]
    counts = scan["exam_type"]["counts"]

    rows = []
    for raw in sorted(r for r in hits if r):
        if raw not in EXAM_TYPE_MAP:
            errors.append(
                f"考试类型 `{raw}` 在 category_group 中出现（{sorted(hits[raw])}），"
                "但未登记到 EXAM_TYPE_MAP → 必须显式归并后才可灌数"
            )
            continue
        normalized, conf, note = EXAM_TYPE_MAP[raw]
        rows.append({
            "raw_exam_type": raw,
            "normalized": normalized,
            "confidence": conf,
            "occurrences": counts.get(raw, 0),
            "evidence_files": sorted(hits[raw]),
            "note": note,
        })

    review_rows = [r for r in rows if r["confidence"] == "review"]
    payload = {
        "meta": {
            "title": "考试类型（exam_type）归一映射",
            "purpose": ("把数据源的 `category_group` 列按契约 8.7 归一到 `exam_type`，"
                        "使河南「普通类」与江西「历史、物理科目组」在唯一键层面不被当成两种考试类型"),
            "owner": "徐（③ 数据工程）",
            "generated_at": today,
            "issue": "新发现（契约 8.7 要求「必须改名」，但未给出取值归一规则）",
            "contract_refs": [
                "docs/api-contract.md 8.7：「数据源列名 category_group 对应契约字段 exam_type，导入时必须改名」",
                "docs/api-contract.md 8.3：示例 exam_type = \"普通\"",
                "backend/app/models/profile.py：exam_type 注释「普通 / 艺术 / 体育」，default=\"普通\"",
            ],
            "coverage": {
                "raw_values_in_data": len(rows),
                "normalized_values": sorted({r["normalized"] for r in rows if r["normalized"]}),
                "needs_ruling": [r["raw_exam_type"] for r in review_rows],
            },
        },
        "map": {r["raw_exam_type"]: r["normalized"] for r in rows},
        "source_field": "category_group",
        "target_field": "exam_type",
        "rows": rows,
    }
    return payload, errors


def write_json_csv(json_path: Path, csv_path: Path, payload: dict, rows: list[dict],
                   fieldnames: list[str]) -> None:
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            flat = {k: ("; ".join(v) if isinstance(v, list) else v) for k, v in r.items()}
            w.writerow(flat)


# ══════════════════════════════════════════════════════════════════════
def main() -> int:
    ap = argparse.ArgumentParser(description="构建口径归一映射（省份码 / 批次码 / 科类码 / 考试类型）")
    ap.add_argument("--check", action="store_true", help="只校验，不写出文件")
    args = ap.parse_args()

    import datetime
    today = str(datetime.date.today())

    print("=" * 74)
    print("口径归一映射构建（G6 省份码 / G7 批次码 / 科类码 / exam_type）")
    print("=" * 74)

    scan = scan_source_data()
    print(f"\n[1/5] 扫描数据文件 {len(scan['files'])} 个（按语义分口径）")
    print(f"   省份原值 {len(scan['province']['hits'])} 种 | "
          f"批次原值 {len(scan['batch']['hits'])} 种 | "
          f"科类原值 {len(scan['subject']['hits'])} 种 | "
          f"考试类型原值 {len(scan['exam_type']['hits'])} 种")

    # 规则表已登记的 batch_code（用于交叉校验）
    rule_codes: dict[str, tuple[str, str]] = {}
    rule_path = ROOT / "data" / "dictionaries" / "province-exam-rule.json"
    if rule_path.exists():
        for r in json.loads(rule_path.read_text(encoding="utf-8")).get("rules", []):
            rule_codes[r["id"]] = (str(r.get("batch_code") or ""), str(r.get("batch") or ""))

    prov, err1 = build_province_map(scan, today)
    batch, err2 = build_batch_map(scan, rule_codes, today)
    subject, err3 = build_subject_map(scan, today)
    exam_type, err4 = build_exam_type_map(scan, today)
    errors = err1 + err2 + err3 + err4

    print(f"\n[2/5] 省份码映射：{len(prov['provinces'])} 省登记，"
          f"当前数据覆盖 {prov['meta']['coverage']['provinces_in_current_data']}")

    bc = batch["meta"]["coverage"]
    print(f"[3/5] 批次码映射：{bc['raw_values_in_data']} 个原值 → "
          f"{len(bc['batch_codes_appearing'])} 个 batch_code")
    for code in bc["batch_codes_appearing"]:
        n = sum(r["occurrences"] for r in batch["rows"] if r["batch_code"] == code)
        raws = [r["raw_batch"] for r in batch["rows"] if r["batch_code"] == code]
        print(f"      {code:<24} {n:>7} 行  ← {' / '.join(raws)}")
    if bc["batch_codes_registered_only"]:
        print(f"      已登记但本年数据未出现：{bc['batch_codes_registered_only']}")

    sc = subject["meta"]["coverage"]
    print(f"[4/5] 科类映射：{sc['raw_values_in_data']} 个原值 → "
          f"{sc['normalized_values']}，脏值 {len(sc['invalid_values'])} 种")
    for r in subject["rows"]:
        if r["raw_subject"]:
            mark = "⚠️" if r["confidence"] == "invalid" else (" " if r["confidence"] == "high" else "*")
            print(f"      {mark} {r['raw_subject']:<18} → {r['normalized']!s:<8} "
                  f"{r['occurrences']:>7} 行  ({r['confidence']})")

    ec = exam_type["meta"]["coverage"]
    print(f"[5/5] 考试类型映射（category_group → exam_type）：{ec['raw_values_in_data']} 个原值 → "
          f"{ec['normalized_values']}，待裁 {len(ec['needs_ruling'])} 项")
    for r in exam_type["rows"]:
        mark = "⚠️" if r["confidence"] == "review" else (" " if r["confidence"] == "high" else "*")
        print(f"      {mark} {r['raw_exam_type']:<18} → {r['normalized']!s:<8} "
              f"{r['occurrences']:>7} 行  ({r['confidence']})")

    print()
    if errors:
        print(f"❌ 发现 {len(errors)} 个未覆盖 / 不一致项：")
        for e in errors:
            print("   -", e)
    else:
        print("✅ 全部取值均已覆盖，且与规则表 batch_code 交叉校验一致")

    if not args.check:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        write_json_csv(OUT_DIR / "province-code-map.json", OUT_DIR / "province-code-map.csv",
                       prov, prov["provinces"],
                       ["province_code", "province_code6", "province_name", "short_name",
                        "aliases", "in_current_data", "data_forms"])
        write_json_csv(OUT_DIR / "batch-code-map.json", OUT_DIR / "batch-code-map.csv",
                       batch, batch["rows"],
                       ["raw_batch", "batch_code", "level", "display_name", "confidence",
                        "occurrences", "in_current_data", "evidence_files", "note"])
        write_json_csv(OUT_DIR / "subject-type-map.json", OUT_DIR / "subject-type-map.csv",
                       subject, subject["rows"],
                       ["raw_subject", "normalized", "display_name", "equivalent", "confidence",
                        "occurrences", "evidence_files", "note"])
        write_json_csv(OUT_DIR / "exam-type-map.json", OUT_DIR / "exam-type-map.csv",
                       exam_type, exam_type["rows"],
                       ["raw_exam_type", "normalized", "confidence",
                        "occurrences", "evidence_files", "note"])
        print(f"\n已写出 4 组映射（json + csv）→ {OUT_DIR.relative_to(ROOT).as_posix()}/")
    else:
        print("\n（--check 模式，未写出文件）")

    print("=" * 74)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
