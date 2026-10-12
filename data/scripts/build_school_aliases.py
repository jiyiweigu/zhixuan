#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""院校别名表生成脚本（`school_aliases.json`）

解决的问题
    院校库（`schools_merged.json` / `schools_raw.json`）取自**河南 2026 招生计划**，
    而录取分数据是 **2022–2025**。期间院校改名，导致旧名挂不上 `school_id`。

★★ 核心发现（本脚本据此设计）
    院校库**自己就把别名内联在名字里**，形如：
        江西水利电力大学(原南昌工程学院)
        吉林化工大学(原吉林化工学院)
        苏州工学院(原常熟理工学院)
        绍兴理工学院(原绍兴文理学院元培学院)
    ⇒ 别名映射**可直接从院校库自身提取**，比外部推断更权威、零猜测。

三类映射来源（按权威度排序）
    ① `from_library`  ：从库内 `新名(原旧名)` 字样提取（**首选，官方口径**）
    ② `verified_moe`  ：教育部名单核实的改名（补充库内未内联标注的）
    ③ `strip_suffix`  ：校区/专业类后缀（如 `(农林类)` / `(较高收费)`），同校剥离

仍无法匹配者 → 写入 `no_match_reason`，**绝不造假映射**。

用法
    python data/scripts/build_school_aliases.py          # 生成
    python data/scripts/build_school_aliases.py --scan   # 只报告
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
SCHOOLS = DATA / "schools" / "schools_merged.json"
SCHOOLS_RAW = DATA / "schools" / "schools_raw.json"
MOE = DATA / "schools" / "moe_schools.json"
OUT = DATA / "schools" / "school_aliases.json"

PROVINCE_EN = {"henan": "河南", "jiangxi": "江西"}

# 库内别名内联格式：`新名(原旧名)`，可带后续后缀
RE_LIB_ALIAS = re.compile(r"^(?P<new>.+?)\(原(?P<old>.+?)\)")

# 校区/专业类后缀：属同一所院校，剥离后可命中（须先确认剥离结果在库内）
STRIP_SUFFIX_PATTERNS: list[str] = [
    r"\(农林类\)", r"\(医学类\)", r"\(师范类\)", r"\(中外合作办学\)",
    r"\(中外课程合作\)", r"\(免费医学定向\)", r"\(较高收费\)",
    r"\(单列专业\)", r"\(软件类\)", r"\(艺术类专业\)", r"\(异地校区\)",
    r"\(宏福校区\)", r"\(威海\)", r"\(会峰校区\)", r"\(凤阳校区\)",
]

# 教育部名单核实的改名（**仅补充库内未内联标注者**；现名须在教育部名单中存在）
VERIFIED_MOE_RENAMES: dict[str, str] = {
    # 说明：以下条目均已用 moe_schools.json 校验「现名存在」。
    # 若现名不在教育部名单，脚本会自动剔除并告警。
    # （库内已内联的条目无需在此重复，脚本会合并两源）
    "滨州医学院": "山东第二医科大学",
    "潍坊医学院": "山东第二医科大学",
    "皖南医学院": "皖南医科大学",
    "赣南医学院": "赣南医科大学",
    "海南医学院": "海南医科大学",
    "牡丹江医学院": "牡丹江医科大学",
    "蚌埠医学院": "蚌埠医科大学",
    "河北中医学院": "河北中医药大学",
    "湖州师范学院": "湖州师范大学",
    "绍兴文理学院": "绍兴大学",
    "榆林学院": "榆林大学",
    "嘉兴学院": "嘉兴大学",
    "赤峰学院": "赤峰大学",
    "合肥学院": "合肥大学",
    "信阳师范学院": "信阳师范大学",
    "湖南理工学院": "湖南理工大学",
    "闽江学院": "闽江大学",
    "佛山科学技术学院": "佛山大学",
    "上海体育学院": "上海体育大学",
    "西藏农牧学院": "西藏农牧大学",
    "重庆科技学院": "重庆科技大学",
    "重庆三峡学院": "重庆三峡科技大学",
    "淮阴工学院": "淮安大学",
    "防灾科技学院": "应急管理大学",
    "华北科技学院": "应急管理大学",
    "滨州学院": "山东航空学院",
    "福建工程学院": "福建理工大学",
    "浙江科技学院": "浙江科技大学",
    "安徽科技学院": "安徽科技学院",   # 占位：见下方校验，若现名不在名单会被剔除
}


def normalize_school_name(name: str) -> str:
    """与 import_major_score.py 一致：全角括号→半角、去空格。"""
    s = (name or "").strip()
    s = s.replace("（", "(").replace("）", ")")
    return re.sub(r"\s+", "", s)


RE_ANY_PAREN = re.compile(r"\([^()]*\)")


def core_name(name: str) -> str:
    """去括号核心名：`江西水利电力大学(原南昌工程学院)` → `江西水利电力大学`。

    用于地址库内 `新名(原旧名)` 形态 —— 录取分数据里的旧名要能对上核心名。
    """
    base = normalize_school_name(name)
    # 反复剥离尾部括号（可能叠多层，如 `X(原Y)(中外课程合作)`）
    prev = None
    while prev != base:
        prev = base
        base = re.sub(r"\([^()]*\)$", "", base)
    return base


def build_lib_index(records: list[dict]) -> tuple[dict, dict, dict]:
    """返回 (by_henan_code, lib_norm 全名索引, lib_core 核心名索引)。"""
    by_henan_code: dict[str, int] = {}
    lib_norm: dict[str, str] = {}
    lib_core: dict[str, str] = {}
    for r in records:
        hc = str(r.get("_henan_code") or "").strip()
        if hc:
            by_henan_code[hc] = r["id"]
        nm = r["name"]
        lib_norm.setdefault(normalize_school_name(nm), nm)
        c = core_name(nm)
        if c:
            lib_core.setdefault(c, nm)
    return by_henan_code, lib_norm, lib_core


def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────
# ① 从院校库提取内联别名
# ─────────────────────────────────────────────────────────

def extract_from_library() -> dict[str, list[str]]:
    """扫描 schools_raw.json 的 `新名(原旧名)` 字样。

    返回 {旧名: [候选现名, ...]}（可能多条，因同一旧名在不同批次有变体）。
    """
    raw = load_json(SCHOOLS_RAW)
    recs = raw if isinstance(raw, list) else raw.get("records", [])
    out: dict[str, set] = {}
    for r in recs:
        nm = str(r.get("YXMC") or r.get("name") or "")
        m = RE_LIB_ALIAS.match(nm)
        if m:
            old = m.group("old").strip()
            new = m.group("new").strip()
            if old and new and old != new:
                out.setdefault(old, set()).add(new)
    return {k: sorted(v) for k, v in out.items()}


# ─────────────────────────────────────────────────────────
# ② 核实教育部改名（现名须在教育部名单）
# ─────────────────────────────────────────────────────────

def verify_moe_renames(moe_names: set[str]) -> tuple[dict, list]:
    good, bad = {}, []
    for old, new in VERIFIED_MOE_RENAMES.items():
        if old == new:
            continue
        if new in moe_names:
            good[old] = new
        else:
            bad.append((old, new))
    return good, bad


# ─────────────────────────────────────────────────────────
# 收集未匹配校名 + 后缀剥离
# ─────────────────────────────────────────────────────────

def collect_unmatched(by_henan_code: dict, lib_norm: dict) -> Counter:
    miss: Counter = Counter()
    for p in sorted(RAW.glob("*_major-admission.csv")):
        parts = p.stem.split("_", 2)
        if len(parts) != 3 or not parts[0].isdigit():
            continue
        province = PROVINCE_EN.get(parts[1])
        if province is None:
            continue
        for r in csv.DictReader(p.open(encoding="utf-8-sig")):
            b = (r.get("batch") or "").strip()
            if "专" in b or "本" not in b or "提前" in b:
                continue
            if any(k in (r.get("category") or "") for k in ("艺术", "体育")):
                continue
            code = (r.get("university_code") or "").strip()
            name = (r.get("university_name") or "").strip()
            if not name:
                continue
            if province == "河南" and code and code.zfill(4) in by_henan_code:
                continue
            if normalize_school_name(name) in lib_norm:
                continue
            miss[name] += 1
    return miss


def strip_suffix_match(name: str, lib_norm: dict) -> str | None:
    base = normalize_school_name(name)
    for pat in STRIP_SUFFIX_PATTERNS:
        b2 = re.sub(pat + r"$", "", base)
        if b2 != base and b2 in lib_norm:
            return lib_norm[b2]
    # 通用兜底：剥离结尾任意 (...) 与「(原…)」
    b2 = re.sub(r"\(原[^()]*\)$", "", base)
    b2 = re.sub(r"\([^()]*\)$", "", b2)
    if b2 != base and b2 in lib_norm:
        return lib_norm[b2]
    return None


def classify_reason(name: str) -> str:
    if re.search(r"大学.*学院$", name):
        return "独立学院"
    if re.search(r"\(.*(校区|类)\)$", name):
        return "分校区/类"
    if any(k in name for k in ("军", "部队", "士官", "武警")):
        return "军事院校"
    if name.startswith("了") or name.startswith("和"):
        return "疑似数据脏值（首字异常）"
    return "院校库外（需人工确认）"


# ─────────────────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    args = ap.parse_args()

    lib = load_json(SCHOOLS)
    moe_names = {r["name"] for r in load_json(MOE)["records"]}

    by_henan_code, lib_norm, lib_core = build_lib_index(lib["records"])

    def in_lib(name: str) -> bool:
        """名字能否映射到库内（全名或核心名任一命中）。"""
        return normalize_school_name(name) in lib_norm or core_name(name) in lib_core

    # ── ① 库内提取 ──
    lib_aliases_raw = extract_from_library()
    lib_aliases: dict[str, str] = {}
    ambiguous: list[dict] = []
    for old, cands in lib_aliases_raw.items():
        ok = [c for c in cands if in_lib(c)]
        if len(ok) == 1:
            lib_aliases[old] = ok[0]
        elif len(cands) == 1:
            lib_aliases[old] = cands[0]
        else:
            ambiguous.append({"old": old, "candidates": cands})
    print(f"① 库内内联别名：提取 {len(lib_aliases_raw)} 个旧名，"
          f"确定 {len(lib_aliases)} 条，歧义 {len(ambiguous)} 条")

    # ── ② 教育部核实补充 ──
    moe_aliases, rejected = verify_moe_renames(moe_names)
    print(f"② 教育部核实补充：{len(moe_aliases)} 条通过，{len(rejected)} 条被拒")
    for old, new in rejected:
        print(f"   ✗ 拒绝：{old} → {new}（现名不在教育部名单，疑似臆测）")

    # 合并（库内优先）
    aliases: dict[str, str] = {}
    aliases.update(moe_aliases)
    aliases.update(lib_aliases)

    # 过滤：别名现名必须真能映射到库内（全名或核心名）
    usable = {o: n for o, n in aliases.items() if in_lib(n)}
    not_in_lib = {o: n for o, n in aliases.items() if o not in usable}
    print(f"   合并后 {len(aliases)} 条；可映射到库内 {len(usable)} 条，"
          f"现名仍不在库内 {len(not_in_lib)} 条")

    # ── ③ 统计未匹配与救回量 ──
    miss = collect_unmatched(by_henan_code, lib_norm)
    print(f"\n③ 本科批未匹配：{len(miss)} 个 / {sum(miss.values())} 行")

    rescued_alias = rescued_suffix = rescued_core = 0
    still: Counter = Counter()
    for name, cnt in miss.items():
        canon = usable.get(name)
        if canon and in_lib(canon):
            rescued_alias += cnt
            continue
        # 名称本身可能已带 `(原旧名)` 或将后缀，剥离后命中核心名
        if strip_suffix_match(name, lib_norm) or core_name(name) in lib_core:
            rescued_core += cnt
            continue
        still[name] += cnt
    print(f"④ 别名可救回：{rescued_alias} 行")
    print(f"   核心名/后缀剥离可救回：{rescued_core + rescued_suffix} 行")
    print(f"   仍无法匹配：{len(still)} 个 / {sum(still.values())} 行")

    no_match = {}
    reason_counter: Counter = Counter()
    for name, cnt in still.most_common():
        reason = classify_reason(name)
        reason_counter[reason] += 1
        no_match[name] = {"rows": cnt, "reason": reason}
    print("\n⑤ 原因分布：")
    for k, v in reason_counter.most_common():
        print(f"   {k}: {v} 个")

    out = {
        "meta": {
            "target": "school_aliases（辅助表，助 school_id 挂载）",
            "owner": "徐（③ 数据工程）",
            "generated_at": "2026-10-12",
            "purpose": "院校库取自河南2026招生计划，录取分为2022-2025，期间院校改名；"
                       "本表提供 旧名→现名 映射，供 import_major_score.py 兜底匹配。",
            "primary_source": "院校库自身内联的 `新名(原旧名)` 字样（schools_raw.json）",
            "secondary_source": "教育部《全国普通高等学校名单》核实的补充改名",
            "verification": {
                "library_extracted": len(lib_aliases),
                "moe_verified": len(moe_aliases),
                "moe_rejected": [{"old": o, "new": n, "why": "现名不在教育部名单"} for o, n in rejected],
                "aliases_mappable_to_library": len(usable),
                "alias_target_not_in_library": not_in_lib,
                "ambiguous": ambiguous,
            },
            "red_line": "严禁机械改名推断（反例：安徽科技学院 → 教育部名单无『安徽科技大学』）；"
                        "未核实者一律登记 no_match_reason，不造假映射。",
        },
        "aliases": dict(sorted(usable.items())),
        "strip_suffix_patterns": STRIP_SUFFIX_PATTERNS,
        "apply_order": ["henan_code", "name", "code2name", "strip_suffix", "alias"],
        "no_match_reason": no_match,
        "stats": {
            "unmatched_names": len(miss),
            "unmatched_rows": sum(miss.values()),
            "rescued_by_alias_rows": rescued_alias,
            "rescued_by_suffix_rows": rescued_suffix,
            "still_unmatched_names": len(still),
            "still_unmatched_rows": sum(still.values()),
        },
    }

    if args.scan:
        print("\n--scan：未写文件。")
        return 0

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 已写入 {OUT.relative_to(ROOT)}（别名 {len(usable)} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
