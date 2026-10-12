# -*- coding: utf-8 -*-
"""
选科要求解析器（subject_req parser）
====================================
任务来源：《数据源与数据获取方案》§4.1（明确交给数据工程）
契约目标（《开发产品书》7 章 subject_requirement / 响应体）：
    {"first": None|"物理"|"历史", "secondary": ["化学", ...], "logic": "all"|"any"}

输入：GaokaoCompass 数据集的 `subject_req` 自由文本字段（实测 4 大格式家族）
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
    python parse_subject_req.py --selftest          # 跑内置用例
    python parse_subject_req.py --scan              # 扫描 data/raw 全量并输出统计
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import sys
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
# 全量扫描
# ---------------------------------------------------------------
def scan() -> int:
    files = sorted(glob.glob(str(RAW_DIR / "*_enrollment-plan.csv"))) + \
            sorted(glob.glob(str(RAW_DIR / "*_school-admission.csv"))) + \
            sorted(glob.glob(str(RAW_DIR / "*_major-admission.csv")))
    if not files:
        print(f"[err] 未找到数据文件，请在 {RAW_DIR} 下放 CSV")
        return 2

    stat = Counter()
    unparsed_samples = Counter()
    total = 0
    by_file = {}

    for f in files:
        name = os.path.basename(f)
        c = Counter()
        tot = 0
        with open(f, encoding="utf-8-sig") as fo:
            for row in csv.DictReader(fo):
                tot += 1
                total += 1
                r = parse(row.get("subject_req"))
                c[r.status] += 1
                stat[r.status] += 1
                if r.status == "unparsed":
                    unparsed_samples[(row.get("subject_req") or "").strip()] += 1
        by_file[name] = (tot, dict(c))

    print("=" * 76)
    print(f"选科要求解析 · 全量扫描（{len(files)} 个文件，{total} 行）")
    print("=" * 76)
    for name, (tot, c) in by_file.items():
        okn = c.get("ok", 0); msn = c.get("missing", 0); unn = c.get("unparsed", 0)
        valid = okn + unn
        rate = f"{okn/valid*100:.1f}%" if valid else "—"
        print(f"  {name:<36} 总{tot:>7}  ok{okn:>7}  missing{msn:>7}  unparsed{unn:>4}  解析率{rate}")
    print("-" * 76)
    print(f"合计：ok={stat['ok']}  missing={stat['missing']}  unparsed={stat['unparsed']}")
    valid = stat['ok'] + stat['unparsed']
    if valid:
        print(f"非空字段解析成功率：{stat['ok']/valid*100:.2f}%")
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
    ap.add_argument("--one", type=str, help="解析单条并打印")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.scan:
        return scan()
    if args.one is not None:
        r = parse(args.one)
        print(json.dumps(r.to_dict(), ensure_ascii=False, indent=2))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
