# -*- coding: utf-8 -*-
"""
选科要求解析器（subject_req parser）
====================================
任务来源：《数据源与数据获取方案》§4.1（明确交给数据工程）
契约目标（《开发产品书》7 章 subject_requirement / 响应体）：
    {"first": None|"物理"|"历史", "secondary": ["化学", ...], "logic": "all"|"any"}

输入：GaokaoCompass 数据集的 `subject_req` 自由文本字段（实测 4 大格式家族）
      + 招生计划 `category` 列（历史类/物理类）—— 河南的 subject_req 仅含再选要求，
      首选科目由科类列承载（2026-10 修复：此前漏读科类列，导致河南首选闸门失效）。
输出：契约结构 + 解析状态（ok / missing / unparsed）

★ 铁律（项目红线）
  1. **不猜**：解析失败一律标 `unparsed` 进 `missing_rule_sets`，绝不猜一个值出来。
  2. **区分"不限"与"数据缺失"**：
       - "不限"      → {"first":None,"secondary":[],"logic":"all"}  + status=ok
       - "" / None   → status=missing（该省该年制度性缺失，如老高考无选科概念）
     两者语义完全不同，必须可区分。
  3. 禁止把老高考年份（河南≤2024、江西≤2023）的缺失当作解析失败。

实测输入分布（河南+江西 2022–2025, 非空 52 种取值）：
  A. 全称带"首选/再选"  : '首选物理，再选化学、生物(2科必选)'
  B. 缩写加号           : '物+化+生'
  C. 全称逗号           : '物理,化学,生物'
  D. 单字/带"且"        : '化' / '化且生' / '政且地'
  E. 不限               : '不限'

用法：
    python parse_subject_req.py --selftest          # 跑内置用例（22/22）
    python parse_subject_req.py --scan              # 扫描 data/raw 全量：打印统计 + 落盘
    python parse_subject_req.py --scan --no-write   # 只打印统计，不落盘

落盘（T4 选科要求落盘，闸门②弹药）：
  data/dictionaries/subject-requirement.json   仓库内交付（>5MB 时只放 20 条样本）
  data/raw/subject-requirement.full.json       完整版（data/raw 不入库）

产物口径（对齐契约 §8.7 subject_requirement + 录取分表身份键）：
  - 只保留 status ∈ {ok, unparsed} 的行；missing（老高考制度性缺失 /
    上游整列缺失）不产生规则行，只在 meta.per_file 里计数 —— 「不限」与
    「数据缺失」语义必须可区分，missing 不是规则。
  - 组级无损聚合：同 (批次, 科类, 院校, 专业组) 内全部 ok 且取值一致的，
    合并为一行 target_type=group；取值不一致的保留专业级行（target_type=major）。
    —— 聚合是数学无损的，不存在猜测。
  - target_id = {school_key}#{batch}#{group_code}[#{major_code}]，
    school_key = school_id（挂载成功）或 name:{校名}（未挂载，如实留名）。
  - school_id 挂载沿用 import_major_score.py 的项目惯例：
    河南代号 → 校名 → 别名表兜底；挂不上的 school_id=null，绝不猜。
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent      # data/
RAW_DIR = BASE_DIR / "raw"

# ---------------------------------------------------------------
# 科目归一化表
# ---------------------------------------------------------------
# 首选科目只有两个；再选科目有 4 个（化/生/政/地）
# 注意：「物理」「历史」既可作首选也可在文本里出现为科目名
SUBJECT_ALIAS = {
    # 全称
    "物理": "物理", "历史": "历史",
    "化学": "化学", "生物": "生物",
    "思想政治": "思想政治", "政治": "思想政治",
    "地理": "地理",
    # 单字（招生计划表用的简写）
    "物": "物理", "史": "历史",
    "化": "化学", "生": "生物",
    "政": "思想政治", "地": "地理",
}

# 首选科目集合（用于判定 first 字段）
FIRST_SUBJECTS = {"物理", "历史"}
# 再选科目集合
SECONDARY_SUBJECTS = {"化学", "生物", "思想政治", "地理"}

# 招生计划「科类」列 → 首选科目（河南/江西 2025/2024 计划表口径）：
# 河南计划表的 subject_req 列只承载"再选"要求（不限/化/政/化且生…），首选科目
# 由 category 列（历史类/物理类）承载；江西两列兼有且口径一致（已全量核验，
# 0 条冲突）。两者冲突时不猜，标 unparsed。
CATEGORY_FIRST = {"历史类": "历史", "物理类": "物理"}


class ParseResult:
    __slots__ = ("status", "first", "secondary", "logic", "raw", "reason")

    def __init__(self, status, first=None, secondary=None, logic="all", raw="", reason=""):
        self.status = status                    # ok | missing | unparsed
        self.first = first                      # None | "物理" | "历史"
        self.secondary = secondary or []        # list[str]
        self.logic = logic                      # all | any
        self.raw = raw
        self.reason = reason

    def to_contract(self) -> dict:
        return {"first": self.first, "secondary": self.secondary, "logic": self.logic}

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "subject_req": self.to_contract() if self.status == "ok" else None,
            "raw": self.raw,
            "reason": self.reason,
        }

    def __repr__(self):
        if self.status == "ok":
            return f"<ok {self.to_contract()}>"
        return f"<{self.status} raw={self.raw!r} {self.reason}>"


def _norm_tokens(tokens: list[str]) -> tuple[list[str], list[str]]:
    """把 token 列表归一化为 (first候选, secondary候选)。未知 token 会抛 ValueError。"""
    firsts, secon = [], []
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        # 去掉常见噪声
        t = re.sub(r"\(\d+科必选\)|（\d+科必选）|必选|选考|科目", "", t).strip()
        if not t:
            continue
        m = SUBJECT_ALIAS.get(t)
        if m is None:
            raise ValueError(f"未知科目 token: {t!r}")
        if m in FIRST_SUBJECTS:
            firsts.append(m)
        elif m in SECONDARY_SUBJECTS:
            secon.append(m)
        else:  # pragma: no cover
            raise ValueError(f"无法归类: {t!r}")
    return firsts, secon


def parse(raw: str | None) -> ParseResult:
    """解析一条 subject_req。

    返回 ParseResult；status ∈ {ok, missing, unparsed}。
    """
    s = (raw or "").strip().replace("　", " ").replace("，", ",")
    s = re.sub(r"\s+", "", s)

    # --- 缺失（老高考年份 / 数据未采集）---
    if not s:
        return ParseResult("missing", raw=raw or "", reason="empty_field")

    # --- 不限（必须与 missing 区分）---
    if s in ("不限", "无", "均可", "不限制"):
        return ParseResult("ok", first=None, secondary=[], logic="all", raw=raw)

    try:
        # ============ 格式 A：全称「首选X，再选Y」 ============
        if "首选" in s:
            m = re.match(r"^首选([^,]+?)(?:,再选(.+))?$", s)
            if not m:
                raise ValueError(f"首选格式无法解析: {s!r}")
            first_tok, second_part = m.group(1), (m.group(2) or "")
            firsts, secon = _norm_tokens([first_tok])
            # 再选部分：可能是「不限」或「化学、生物」「化学或生物」
            logic = "all"
            if second_part:
                if second_part in ("不限", "无", "均可"):
                    pass  # secondary 留空
                else:
                    # 逻辑词判定
                    if "或" in second_part:
                        logic = "any"
                        parts = second_part.split("或")
                    else:
                        parts = re.split(r"[、,]|且", second_part)
                    f2, s2 = _norm_tokens(parts)
                    # 「再选」部分出现的首选科目视为再选科目（一般不会）
                    secon += s2
                    # 若出现物理/历史在再选，归入 first 判定
                    firsts += f2
            first = firsts[0] if firsts else None
            if len(firsts) > 1:
                # 「首选物理，再选化学」里出现两个首选科目名 → 异常
                raise ValueError(f"首选字段异常（多个首选科目）: {s!r}")
            return ParseResult("ok", first=first, secondary=_dedup(secon),
                               logic=logic, raw=raw)

        # ============ 格式 B：缩写加号 '物+化+生' ============
        if "+" in s:
            logic = "all"          # '+' 语义为「均需」
            parts = s.split("+")
            # '史+不限' / '物+不限'：'不限' 不是科目，先剥离（语义＝再选不限）
            has_unlimited = any(p.strip() in ("不限", "无", "均可") for p in parts)
            parts = [p for p in parts if p.strip() not in ("不限", "无", "均可")]
            firsts, secon = _norm_tokens(parts)
            first = firsts[0] if firsts else None
            if len(firsts) > 1:
                # 例如 '物+化+生' 只有一个首选；两个首选视为异常
                raise ValueError(f"多个首选科目: {s!r}")
            if has_unlimited:
                return ParseResult("ok", first=first, secondary=[], logic="all", raw=raw)
            return ParseResult("ok", first=first, secondary=_dedup(secon),
                               logic=logic, raw=raw)

        # ============ 格式 D：'且' 连接的简写 '化且生' ============
        if "且" in s:
            parts = s.split("且")
            firsts, secon = _norm_tokens(parts)
            first = firsts[0] if firsts else None
            if len(firsts) > 1:
                raise ValueError(f"多个首选科目: {s!r}")
            return ParseResult("ok", first=first, secondary=_dedup(secon),
                               logic="all", raw=raw)

        # ============ 格式 C/E：纯科目（可含逗号）'物理,化学' '化' '物理' ============
        # 注意：无任何连接符，可能是单个科目，也可能是逗号分隔
        parts = [p for p in re.split(r"[、,]", s) if p]
        firsts, secon = _norm_tokens(parts)
        if not firsts and not secon:
            raise ValueError(f"无有效科目: {s!r}")
        first = firsts[0] if firsts else None
        if len(firsts) > 1:
            raise ValueError(f"多个首选科目: {s!r}")
        # 语义判定：
        #  - 只有 first 无 secondary（如 '物理'）→ 只限首选
        #  - 只有 secondary（如 '化'）→ 只限再选
        #  - 两者都有（如 '物理,化学'）→ first + secondary
        return ParseResult("ok", first=first, secondary=_dedup(secon),
                           logic="all", raw=raw)

    except ValueError as e:
        return ParseResult("unparsed", raw=raw or "", reason=str(e))


def _dedup(seq: list[str]) -> list[str]:
    out = []
    for x in seq:
        if x not in out:
            out.append(x)
    return out


# ---------------------------------------------------------------
# 自测
# ---------------------------------------------------------------
SELFTEST_CASES = [
    # (输入, 期望 first, 期望 secondary, 期望 logic, 期望 status)
    ("不限",            None,   [],                 "all", "ok"),
    ("物理",            "物理", [],                 "all", "ok"),
    ("历史",            "历史", [],                 "all", "ok"),
    ("化",              None,   ["化学"],           "all", "ok"),
    ("政",              None,   ["思想政治"],       "all", "ok"),
    ("物理,化学",       "物理", ["化学"],           "all", "ok"),
    ("历史,思想政治",   "历史", ["思想政治"],       "all", "ok"),
    ("物理,化学,生物",  "物理", ["化学", "生物"],   "all", "ok"),
    ("化且生",          None,   ["化学", "生物"],   "all", "ok"),
    ("政且地",          None,   ["思想政治", "地理"], "all", "ok"),
    ("物+化",           "物理", ["化学"],           "all", "ok"),
    ("史+不限",         "历史", [],                 "all", "ok"),
    ("物+化+生",        "物理", ["化学", "生物"],   "all", "ok"),
    ("首选物理，再选化学", "物理", ["化学"],        "all", "ok"),
    ("首选历史，再选不限", "历史", [],              "all", "ok"),
    ("首选物理，再选思想政治", "物理", ["思想政治"], "all", "ok"),
    ("首选物理，再选化学、生物(2科必选)", "物理", ["化学", "生物"], "all", "ok"),
    ("首选历史，再选地理", "历史", ["地理"],        "all", "ok"),
    # 缺失
    ("",   None, None, None, "missing"),
    (None, None, None, None, "missing"),
    # 无法解析（不应猜）
    ("物理或历史", None, None, None, "unparsed"),
    ("随便什么", None, None, None, "unparsed"),
]


def selftest() -> int:
    import logging
    ok = 0
    fail = []
    for raw, ef, es, el, est in SELFTEST_CASES:
        r = parse(raw)
        if est == "ok":
            cond = (r.status == "ok" and r.first == ef
                    and r.secondary == es and r.logic == el)
        else:
            cond = (r.status == est)
        if cond:
            ok += 1
        else:
            fail.append((raw, r, (ef, es, el, est)))
    print(f"自测：{ok}/{len(SELFTEST_CASES)} 通过")
    for raw, r, exp in fail:
        print(f"  ✗ {raw!r}\n      得到 {r}\n      期望 {exp}")
    return 0 if not fail else 1


# ---------------------------------------------------------------
# 全量扫描 + 落盘（T4 选科要求落盘）
# ---------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent          # data/
SCHOOL_INDEX_PATH = BASE_DIR / "schools" / "schools.json"
ALIAS_PATH = BASE_DIR / "schools" / "school_aliases.json"
PROVINCE_MAP_PATH = BASE_DIR / "mappings" / "province-code-map.json"
DICT_DIR = BASE_DIR / "dictionaries"
OUT_PATH = DICT_DIR / "subject-requirement.json"          # 仓库内交付
FULL_OUT_PATH = RAW_DIR / "subject-requirement.full.json"  # 完整版（不入库）
REPO_SIZE_LIMIT = 5 * 1024 * 1024
SAMPLE_ROWS = 20

# 来源三要素（与 data/sources/source-table.json 的 SRC-GAOKAO-COMPASS 一致）
SOURCE_ID = "SRC-GAOKAO-COMPASS"
SOURCE_NAME = "Gaokao-Compass-11M 高考数据集（MIT，DOI 10.57967/hf/9882）"
SOURCE_URL = "https://hf-mirror.com/datasets/choucsan/Gaokao-Compass-11M"

PROV_CN = {"henan": "河南", "jiangxi": "江西"}


def _load_school_indexes():
    """复用 import_major_score.py 的院校索引与别名表（项目统一匹配惯例）。

    返回 (SchoolIndex | None, AliasIndex | None, enabled: bool)。
    加载失败不致命：school_id 全部留空并在 meta 里如实注明。
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from import_major_score import AliasIndex, SchoolIndex  # noqa: PLC0415
        idx = SchoolIndex(SCHOOL_INDEX_PATH)
        alias = AliasIndex(ALIAS_PATH)
        return idx, alias, True
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 院校索引加载失败，school_id 将全部留空：{e}")
        return None, None, False


def _load_province_codes() -> dict[str, str]:
    """省名 → 两位码（data/mappings/province-code-map.json）。"""
    try:
        d = json.loads(PROVINCE_MAP_PATH.read_text(encoding="utf-8"))
        return {name: v[0] for name, v in d.get("by_name", {}).items()}
    except Exception:  # noqa: BLE001
        return {}


def _clean(v: str | None) -> str:
    v = (v or "").strip()
    return "" if v.upper() == "<NA>" else v


def _school_resolver(idx, alias, enabled):
    """返回 resolve(university_code, university_name) -> (school_id, school_name, via)。

    匹配链与 import_major_score.py 一致：河南代号 → 校名 → 别名兜底。
    挂不上时 school_id=None、保留原始校名 —— 宁可缺、不可猜。
    """
    cache: dict[tuple[str, str], tuple] = {}
    if not enabled:
        def resolve(code, name):
            return None, _clean(name) or _clean(code), None
        return resolve

    def resolve(code, name):
        key = (code, name)
        if key in cache:
            return cache[key]
        sid, via = None, None
        c, nm = _clean(code), _clean(name)
        if c:
            sid = idx.resolve_henan(c)
            via = "henan_code" if sid else None
        if sid is None and nm:
            sid = idx.resolve_name(nm)
            via = "name" if sid else None
        if sid is None and nm and alias is not None:
            canon = alias.resolve(nm)
            if canon:
                sid = idx.resolve_name(canon)
                via = "alias" if sid else None
        out = (sid, nm or c, via)
        cache[key] = out
        return out

    return resolve


def _row_target_id(school_key: str, batch: str, group_code: str, major_code: str = "") -> str:
    tid = f"{school_key}#{batch}#{group_code}"
    if major_code:
        tid += f"#{major_code}"
    return tid


def scan(write: bool = True) -> int:
    files = sorted(glob.glob(str(RAW_DIR / "*_enrollment-plan.csv"))) + \
            sorted(glob.glob(str(RAW_DIR / "*_school-admission.csv"))) + \
            sorted(glob.glob(str(RAW_DIR / "*_major-admission.csv")))
    if not files:
        print(f"[err] 未找到数据文件，请在 {RAW_DIR} 下放 CSV")
        print("      取数：python data/scripts/fetch_gaokao_compass.py")
        return 2

    idx, alias, match_enabled = _load_school_indexes()
    resolve_school = _school_resolver(idx, alias, match_enabled)
    prov_codes = _load_province_codes()

    stat = Counter()
    unparsed_samples = Counter()
    total = 0
    by_file = {}
    per_file_meta = []
    rule_rows: list[dict] = []
    match_stat = Counter()

    for f in files:
        name = os.path.basename(f)
        m = re.match(r"(henan|jiangxi)_(\d{4})_", name)
        if m:
            prov_en, year = m.group(1), int(m.group(2))
        else:
            prov_en, year = "", 0
        province = PROV_CN.get(prov_en, "")
        province_code = prov_codes.get(province, "")

        c = Counter()
        tot = 0
        groups: dict[tuple, list[dict]] = {}
        gcount = 0

        with open(f, encoding="utf-8-sig") as fo:
            for row in csv.DictReader(fo):
                tot += 1
                total += 1
                raw_req = row.get("subject_req")
                r = parse(raw_req)
                batch = _clean(row.get("batch"))
                category = _clean(row.get("category"))
                # 科类列（历史类/物理类）即首选科目要求：与 subject_req 解析结果合并。
                # subject_req 已含首选且与科类一致 → 原样；缺失 → 由科类补出（不猜，
                # 科类本身是招生计划的明确字段）；不一致 → 标 unparsed 留人工复核。
                if r.status == "ok":
                    derived = CATEGORY_FIRST.get(category)
                    if derived:
                        if not r.first:
                            r.first = derived
                            c["first_from_category"] += 1
                            stat["first_from_category"] += 1
                        elif r.first != derived:
                            r.status = "unparsed"
                            r.reason = f"首选科目与科类列不一致（解析={r.first}，科类={category}）"
                c[r.status] += 1
                stat[r.status] += 1
                if r.status == "unparsed":
                    unparsed_samples[(raw_req or "").strip()] += 1

                if r.status == "missing":
                    continue  # missing 不是规则，只计数

                ucode, uname = _clean(row.get("university_code")), _clean(row.get("university_name"))
                sid, sname, via = resolve_school(ucode, uname)
                if sid is not None:
                    match_stat[via] += 1
                else:
                    match_stat["unmatched"] += 1
                school_key = str(sid) if sid is not None else (f"name:{sname}" if sname else "unknown")
                gcode = _clean(row.get("major_group"))
                key = (batch, category, school_key, gcode)
                groups.setdefault(key, []).append({
                    "status": r.status,
                    "subject": r.to_contract(),
                    "raw": r.raw,
                    "reason": r.reason,
                    "major_code": _clean(row.get("major_code")),
                    "major_name": _clean(row.get("major_name")),
                    "school_id": sid, "school_name": sname, "match_via": via,
                    "batch": batch, "category": category, "group_code": gcode,
                })

        # 组级无损聚合：取值全一致 → 1 行 group；否则逐专业行 major
        for (batch, category, school_key, gcode), members in groups.items():
            sig = {(mm["status"], mm["subject"]["first"], tuple(mm["subject"]["secondary"]),
                    mm["subject"]["logic"]) for mm in members}
            sid = members[0]["school_id"]
            sname = members[0]["school_name"]
            via = members[0]["match_via"]
            base = {
                "province": province, "province_code": province_code,
                "year": year, "batch": batch, "category": category,
                "school_id": sid, "school_name": sname, "match_via": via,
                "group_code": gcode, "source_id": SOURCE_ID,
            }
            if len(sig) == 1 and next(iter(sig))[0] == "ok":
                first, secon, logic = next(iter(sig))[1:]
                rule_rows.append({
                    **base,
                    "target_type": "group",
                    "target_id": _row_target_id(school_key, batch, gcode),
                    "major_code": None, "major_name": None,
                    "first_subject": first, "secondary_subjects": list(secon),
                    "logic": logic,
                    "status": "ok", "raw": members[0]["raw"], "reason": None,
                })
                gcount += 1
            else:
                for mm in members:
                    rule_rows.append({
                        **base,
                        "target_type": "major",
                        "target_id": _row_target_id(school_key, batch, gcode, mm["major_code"]),
                        "major_code": mm["major_code"] or None,
                        "major_name": mm["major_name"] or None,
                        "first_subject": mm["subject"]["first"],
                        "secondary_subjects": mm["subject"]["secondary"],
                        "logic": mm["subject"]["logic"],
                        "status": mm["status"],
                        "raw": mm["raw"], "reason": mm["reason"] or None,
                    })

        by_file[name] = (tot, dict(c))
        per_file_meta.append({
            "file": name, "province": province, "province_code": province_code,
            "year": year, "rows": tot, "ok": c.get("ok", 0),
            "missing": c.get("missing", 0), "unparsed": c.get("unparsed", 0),
            "first_from_category": c.get("first_from_category", 0),
            "group_rows": gcount,
            "major_rows": sum(
                1 for rr in rule_rows
                if rr["province"] == province and rr["year"] == year
                and rr["target_type"] == "major"),
        })

    # ---- 落盘 ----
    matched_total = sum(v for k, v in match_stat.items() if k != "unmatched")
    unmatched_total = match_stat.get("unmatched", 0)
    # 上游已知缺口（如实登记，不修饰）
    upstream_gaps = []
    for fm in per_file_meta:
        if fm["rows"] and fm["ok"] == 0 and fm["missing"] == fm["rows"]:
            upstream_gaps.append(
                f"{fm['province']} {fm['year']}：subject_req 整列缺失（老高考制度性缺失或上游未采集），"
                f"{fm['rows']} 行全部计 missing，不产生规则行")
        if fm["year"] == 2024 and fm["province"] == "江西":
            upstream_gaps.append(
                "江西 2024：上游 university_code 整列为空，school_id 仅能按校名/别名匹配")
    full_doc = {
        "meta": {
            "title": "选科要求数据集（subject_requirement，闸门②弹药）",
            "contract_ref": "docs/api-contract.md §8.7 subject_requirement；解析器 data/scripts/parse_subject_req.py",
            "generated_at": time.strftime("%Y-%m-%d"),
            "source": {
                "id": SOURCE_ID, "name": SOURCE_NAME, "url": SOURCE_URL, "license": "MIT",
                "note": "渠道来源非官方；作品内事实结论的 source_url 须指向省考试院/阳光高考。",
            },
            "口径说明": {
                "行粒度": "组级（组内取值全一致，无损聚合）或专业级（组内不一致）；"
                          "聚合键含科类（batch, category, school, group）—— 同一院校"
                          "同组号在不同科类/批次下是不同专业组，不得跨科类合并",
                "首选科目": "subject_req 含首选时以解析为准；不含时由招生计划 category 列"
                            "（历史类→历史 / 物理类→物理）补出；两者冲突不猜，标 unparsed",
                "target_id": "{school_key}#{batch}#{group_code}[#{major_code}]；"
                             "school_key=school_id 或 name:{校名}",
                "school_id": "沿用 import_major_score.py 匹配链：河南代号→校名→别名；"
                             "挂不上留 null，绝不猜（红线：宁可缺、不可猜）",
                "missing": "subject_req 为空 → 制度性/上游缺失，不产生规则行，仅在 per_file 计数",
                "major_id": "首期恒 null（与 school_major_score 同口径，专业库挂载后回填）",
            },
            "stats": {
                "total_rows": total,
                "ok": stat["ok"], "missing": stat["missing"], "unparsed": stat["unparsed"],
                "parse_rate_nonempty": round(stat["ok"] / (stat["ok"] + stat["unparsed"]), 4)
                if (stat["ok"] + stat["unparsed"]) else None,
                "rule_rows": len(rule_rows),
                "school_match": {"matched": matched_total, "unmatched": unmatched_total,
                                 "via": dict(match_stat)},
            },
            "per_file": per_file_meta,
            "upstream_gaps": upstream_gaps,
        },
        "rows": rule_rows,
    }
    sample_doc = None
    if len(rule_rows) > SAMPLE_ROWS:
        g = [r for r in rule_rows if r["target_type"] == "group"][:SAMPLE_ROWS // 2]
        mj = [r for r in rule_rows if r["target_type"] == "major"][:SAMPLE_ROWS // 2]
        sample_doc = {
            "meta": {**full_doc["meta"],
                     "sample_of": str(FULL_OUT_PATH),
                     "sample_note": f"完整版 {len(rule_rows)} 行超出仓库 5MB 上限，本文件仅含 "
                                    f"{len(g) + len(mj)} 条样本；完整版留在 data/raw/（不入库），"
                                    "重建见 data/DOWNLOAD.md 与 data/scripts/parse_subject_req.py --scan"},
            "rows": g + mj,
        }

    if write:
        FULL_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        full_doc_out = full_doc
        full_doc_out["meta"]["full_row_count"] = len(rule_rows)
        FULL_OUT_PATH.write_text(
            json.dumps(full_doc_out, ensure_ascii=False, indent=1), encoding="utf-8")
        DICT_DIR.mkdir(parents=True, exist_ok=True)
        full_size = os.path.getsize(FULL_OUT_PATH)
        if full_size <= REPO_SIZE_LIMIT:
            OUT_PATH.write_text(
                json.dumps(full_doc, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"\n[out] {OUT_PATH}（完整 {len(rule_rows)} 行，{full_size/1e6:.1f} MB ≤ 5MB）")
        else:
            OUT_PATH.write_text(
                json.dumps(sample_doc, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"\n[out] {FULL_OUT_PATH}（完整 {len(rule_rows)} 行，{full_size/1e6:.1f} MB > 5MB，不入库）")
            print(f"[out] {OUT_PATH}（样本 {len(sample_doc['rows'])} 行，仓库内交付）")

    # ---- 统计打印 ----
    print("=" * 76)
    print(f"选科要求解析 · 全量扫描（{len(files)} 个文件，{total} 行）")
    print("=" * 76)
    for name, (tot, c) in by_file.items():
        okn = c.get("ok", 0); msn = c.get("missing", 0); unn = c.get("unparsed", 0)
        fd = c.get("first_from_category", 0)
        valid = okn + unn
        rate = f"{okn/valid*100:.1f}%" if valid else "—"
        print(f"  {name:<36} 总{tot:>7}  ok{okn:>7}  missing{msn:>7}  unparsed{unn:>4}  解析率{rate}  科类补首选{fd}")
    print("-" * 76)
    print(f"合计：ok={stat['ok']}  missing={stat['missing']}  unparsed={stat['unparsed']}")
    valid = stat['ok'] + stat['unparsed']
    if valid:
        print(f"非空字段解析成功率：{stat['ok']/valid*100:.2f}%")
    print(f"规则行（落盘）：{len(rule_rows)}"
          f"（组级 {sum(1 for r in rule_rows if r['target_type']=='group')}"
          f" / 专业级 {sum(1 for r in rule_rows if r['target_type']=='major')}）")
    if match_enabled:
        print(f"院校挂载：成功 {matched_total} / 未挂 {unmatched_total}"
              f"（via: {dict(match_stat)}）")
    for gap in upstream_gaps:
        print(f"⚠️ 上游缺口：{gap}")
    if unparsed_samples:
        print("\n⚠️ 未解析样本（不得猜测，须人工补规则）：")
        for k, v in unparsed_samples.most_common(20):
            print(f"  {v:>6}  {k!r}")
    else:
        print("\n✅ 无非空字段解析失败。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--no-write", dest="no_write", action="store_true",
                    help="scan 只打印统计，不落盘")
    ap.add_argument("--one", type=str, help="解析单条并打印")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.scan:
        return scan(write=not args.no_write)
    if args.one is not None:
        r = parse(args.one)
        print(json.dumps(r.to_dict(), ensure_ascii=False, indent=2))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
