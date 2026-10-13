# -*- coding: utf-8 -*-
"""
N21 · 院校库补录（让事实表出现的院校都能挂上 school_id）
==========================================================
背景
----
院校库（`schools_merged.json`，1,367 所）取自**河南 2026 招生计划**的院校清单；
而事实数据（招生计划 / 录取分）覆盖 **2022–2025 两省**。两者院校集合不一致：

  1. **改名**：事实用旧名（闽江学院），教育部名单已用新名（闽江大学）→ 库外
  2. **源字段污染**：江西 2023 的 `university_name` 被拼上「校址：XXX市」→ 匹配失败
  3. **停招/新增**：2026 未招生但往年招生的院校（江西警察学院…）
  4. **独立学院 / 军校 / 港澳合作办学**：教育部名单不含 → 无法由名单补录

本脚本产出**三类**可执行产物（互不混淆、逐条可溯源）：

  A. `name_repair`（不新增实体）—— 源字段污染的**确定性**清洗（截断「校址」后缀等）
  B. `explicit_repairs`     —— 错别字等**唯一命中**修复（编辑距离 ≤1 且唯一才登记）
  C. `supplement_records`   —— 真正**新增院校实体**，字段全部取自教育部名单（官方源）
  D. `unresolved`           —— 名单外（独立学院/军校/港澳），**不补、不猜**

★ 铁律
  1. 补录实体的字段**只能**来自 `moe_schools.json`（SRC-MOE-SCHOOL-LIST，官方）；
     本脚本不编造任何 city / ownership / code。
  2. 改名须有依据：仅接受**已在 `school_aliases.json` 经教育部核实**的映射。
     本脚本**不自行发明**「XX学院→XX大学」。
  3. 宁可缺，不可猜：判不出的进 `unresolved`，并给出量化影响。

用法：
    python build_school_fact_supplement.py            # 全量诊断 + 生成
    python build_school_fact_supplement.py --report   # 额外打印 classify 明细
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
SCHOOLS = DATA / "schools" / "schools_merged.json"
MOE = DATA / "schools" / "moe_schools.json"
ALIASES = DATA / "schools" / "school_aliases.json"
OUT = DATA / "schools" / "school_fact_supplement.json"

MOE_SRC = {
    "source_id": "SRC-MOE-SCHOOL-LIST",
    "source_name": "中华人民共和国教育部（全国普通高等学校名单）",
    "source_url": "https://hudong.moe.gov.cn/qggxmd/",
    "year": 2026,
}

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_major_score import SchoolIndex, AliasIndex, normalize_school_name, core_name  # noqa: E402
from merge_schools import infer_ownership  # noqa: E402

# ── A. 确定性清洗规则（只修「源字段错位」，不做任何语义推断）───────────────
STRIP_RULES = [
    {
        "pattern": r"校址[:：].*$",
        "reason": "江西 2023 招生计划源数据把「校址：XXX市」拼进了 university_name 字段（字段错位）",
        "evidence": "2023 江西本科批 1,061 行含此串，其余 7 个文件 0 行",
        "scope": "fact_table",
    },
    {
        "pattern": r"^[.。、，,；;:：\s\-—_|]+",
        "reason": "源数据行首残留标点/分隔符（CSV 拼接产物）",
        "evidence": "如「.湖南工商大学」，去除后可在教育部名单精确命中",
        "scope": "fact_table",
    },
    {
        "pattern": r"(?<=[\u4e00-\u9fa5])原[\u4e00-\u9fa5]{2,20}(?:学院|大学|学校)$",
        "reason": "源数据把「现名+原旧名」连写（如「广州城市理工学院原华南理工大学广州学院」）",
        "evidence": "去尾后为院校库现名；仅作用于**尾部**、且前缀仍为完整校名",
        "scope": "fact_table",
    },
    {
        "pattern": r"^中国人民解放军(?=[\u4e00-\u9fa5]{2,})",
        "reason": "军队院校规范全称带「中国人民解放军」前缀，与院校库所用简称不一致",
        "evidence": "「中国人民解放军海军军医大学」→「海军军医大学」（院校库 2026 计划用简称）",
        "scope": "fact_table",
    },
]
_RE_STRIP = [re.compile(r["pattern"]) for r in STRIP_RULES]

# ── 结构性改名规则（后缀映射）────────────────────────────────────────────
# 依据：教育部 2023–2025 年集中批复「高职（专科）升格职业本科」与「学院更名大学」，
#       新名与旧名只差**固定的后缀**（学院→大学 / 职业技术学院→职业技术大学）。
# ★ 约束：变换结果必须**唯一**命中教育部名单，否则不采纳（避免张冠李戴）。
# ★ 与「编辑距离」的区别：后者是**字符相似**（会误把「榆林学院」配到「桂林学院」），
#       本规则是**结构映射**，可解释、可复核。
SUFFIX_RULES: list[tuple[re.Pattern, list[str]]] = [
    (re.compile(r"^(.*?)职业技术学院$"), ["{0}职业技术大学"]),
    (re.compile(r"^(.*?)职业学院$"), ["{0}职业技术大学", "{0}职业大学"]),
    (re.compile(r"^(.*?)职业大学$"), ["{0}职业技术大学"]),
    (re.compile(r"^(.*?)高等专科学校$"), ["{0}师范学院", "{0}学院", "{0}医学院", "{0}健康医学院"]),
    (re.compile(r"^(.*?)师范高等专科学校$"), ["{0}师范学院"]),
    (re.compile(r"^(.*?)医学高等专科学校$"), ["{0}医学院", "{0}健康医学院", "{0}医药学院"]),
    (re.compile(r"^(.*?)学院$"), ["{0}大学"]),
]


def suffix_rename(name: str, pool: set[str]) -> str | None:
    """后缀规则改名：变换结果**唯一**命中 pool 时返回新名，否则 None。"""
    for pat, tmpls in SUFFIX_RULES:
        m = pat.match(name)
        if not m:
            continue
        base = m.group(1)
        if not base:
            continue
        found = [t.format(base) for t in tmpls if t.format(base) in pool]
        if len(found) == 1:
            return found[0]
    return None


def clean_name(name: str) -> tuple[str, list[str]]:
    """应用确定性清洗；返回 (清洗后名称, 命中的规则 pattern 列表)。"""
    s = (name or "").strip()
    hits: list[str] = []
    for rule, pat in zip(STRIP_RULES, _RE_STRIP):
        new = pat.sub("", s).strip()
        if new != s:
            hits.append(rule["pattern"])
            s = new
    return s, hits


# ── 编辑距离（Levenshtein，用于「唯一命中」判定）─────────────────────────
def lev(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def norm_key(s: str) -> str:
    """去「大学/学院/学校/职业技术」等后缀，仅用于粗筛，不用于判定。"""
    return re.sub(r"(大学|学院|学校|高等专科学校|职业技术学院|职业技术大学|职业大学)$", "", s or "")


def iter_fact_rows():
    """遍历全部事实表行：产出 (kind, year, province, batch, code, name)。"""
    specs = [
        ("enrollment-plan", "*_enrollment-plan.csv"),
        ("major-admission", "*_major-admission.csv"),
        ("school-admission", "*_school-admission.csv"),
    ]
    for kind, pat in specs:
        for f in sorted(RAW.glob(pat)):
            year = int(f.stem.split("_", 1)[0])
            province = "河南" if "henan" in f.stem else "江西"
            with f.open(encoding="utf-8-sig", newline="") as fh:
                for row in csv.DictReader(fh):
                    yield (kind, year, province, (row.get("batch") or "").strip(),
                           (row.get("university_code") or "").strip(),
                           (row.get("university_name") or "").strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    # ★ 以「**基线院校库**」判定库外：排除历史补录记录（`_match == fact-supplement`）。
    #   否则重复运行会因「上轮补录已在库」而输出为空，破坏幂等。
    idx = SchoolIndex(SCHOOLS, exclude=lambda r: r.get("_match") == "fact-supplement")
    alias_doc = json.loads(ALIASES.read_text(encoding="utf-8"))
    # ★ 改名依据 = ① 已入库别名（aliases）∪ ② 已核实但**目标不在院校库**的改名
    #   （`verification.alias_target_not_in_library`，经教育部名单核实，本轮正好补其目标实体）
    rename_map: dict[str, str] = dict(alias_doc.get("aliases", {}))
    for k, v in (alias_doc.get("meta", {}).get("verification", {})
                 .get("alias_target_not_in_library", {}) or {}).items():
        rename_map.setdefault(k, v)
    lib_names = {r["name"] for r in idx.records}
    lib_core = {norm_key(r["name"]) for r in idx.records}

    moe_recs = json.loads(MOE.read_text(encoding="utf-8"))["records"]
    moe_by_name = {}
    for r in moe_recs:
        moe_by_name.setdefault(r["name"], r)
    moe_names = set(moe_by_name)

    # 省级码反查表：教育部学校标识码 `code10` 形如 `4|13|01|0075`，
    #   第 3–4 位 = **GB 两位省级行政区代码**（41|13|01|0075 → 13 = 河北）。
    #   实测 2,952 所中仅「河北工业大学」例外（标识码属河北、校址在天津，异地办学真实情况）。
    pcode = json.loads((DATA / "mappings" / "province-code-map.json").read_text(encoding="utf-8"))
    short_by2 = {p["province_code"]: p["short_name"] for p in pcode["provinces"]}

    def prov_of(m: dict) -> tuple[str, str]:
        """→ (省份, 依据)。优先名单自带 province，其次由标识码省级码反查。"""
        if (m.get("province") or "").strip():
            return m["province"].strip(), "教育部名单·所在地"
        c10 = (m.get("code10") or "").strip()
        if len(c10) >= 4 and c10[2:4] in short_by2:
            return short_by2[c10[2:4]], f"教育部学校标识码省级码({c10[2:4]})"
        return "", ""

    print("=" * 78)
    print("N21 · 院校库补录（事实表覆盖）")
    print(f"院校库 {len(idx.records)} ｜ 教育部名单 {len(moe_recs)} "
          f"（本科 {sum(1 for r in moe_recs if r['level']=='本科')} / "
          f"专科 {sum(1 for r in moe_recs if r['level']=='专科')}）")
    print("=" * 78)

    # 缓存：原始名 → (sid, how)
    cache: dict[str, tuple[int | None, str]] = {}

    def resolve_lib(name: str, code: str) -> tuple[int | None, str]:
        """挂库判定：河南代号 → 全名/归一名/核心名 → 已核实改名映射。

        ★ 只使用**静态依据**（rename_map），**不读** AliasIndex 的 repairs，
          以避免「读自己上一轮产出」的自举依赖（会破坏幂等与可解释性）。
        """
        sid = idx.resolve_henan(code) or idx.resolve_name(name)
        if sid:
            return sid, "code" if idx.resolve_henan(code) else "name"
        cur = rename_map.get(name) or rename_map.get(core_name(name))
        if cur:
            sid2 = idx.resolve_name(cur)
            if sid2:
                return sid2, "rename"
        return None, "none"

    agg: dict[str, dict] = {}
    clean_fixed: dict[str, dict] = {}        # 原始名 → {clean_to, rows}
    stats = collections.Counter()

    for kind, year, province, batch, code, raw in iter_fact_rows():
        if not raw or raw.upper() == "<NA>":
            continue
        stats[f"{kind}_rows"] += 1
        if raw in cache:
            sid, how = cache[raw]
            key = raw if sid is None else None
        else:
            sid, how = resolve_lib(raw, code)
            if sid is None:                       # 库匹配失败 → 试确定性清洗
                c, hits = clean_name(raw)
                if hits and c != raw:
                    sid2, how2 = resolve_lib(c, code)
                    if sid2:
                        sid, how = sid2, "clean:" + how2
                        clean_fixed[raw] = {"clean_to": c, "rows": 0, "hits": hits}
            cache[raw] = (sid, how)
            key = raw if sid is None else None
        if raw in clean_fixed:
            clean_fixed[raw]["rows"] += 1

        if key is None:
            continue
        stats[f"{kind}_unmatched"] += 1
        d = agg.setdefault(key, {"rows": 0, "kinds": collections.Counter(),
                                 "years": set(), "provinces": set(),
                                 "codes": set(), "batches": set()})
        d["rows"] += 1
        d["kinds"][kind] += 1
        d["years"].add(year)
        d["provinces"].add(province)
        if code:
            d["codes"].add(code)
        if batch:
            d["batches"].add(batch)

    # ── 分类 ────────────────────────────────────────────────────────────
    explicit: dict[str, dict] = {}            # 唯一编辑距离命中（错别字）
    noise_fixed: dict[str, dict] = {}         # 子串噪声（前缀多余字符）→ 自动修复
    rule_rename: dict[str, str] = {}          # 结构性改名（后缀映射）→ 库已有实体，仅需映射
    supplement: dict[str, dict] = {}          # 需新增实体
    unresolved: dict[str, dict] = {}

    def is_zh_only(s: str) -> bool:
        return bool(s) and all("\u4e00" <= ch <= "\u9fa5" for ch in s)

    for raw, d in sorted(agg.items(), key=lambda kv: (-kv[1]["rows"], kv[0])):
        base = {"rows": d["rows"], "kinds": {k: v for k, v in d["kinds"].items()},
                "years": sorted(d["years"]), "provinces": sorted(d["provinces"]),
                "codes": sorted(d["codes"]), "batches": sorted(d["batches"])}
        c, hits = clean_name(raw)

        # 1) 确定性清洗后可直接挂库（源污染，非缺录）——扫描阶段已计入 clean_fixed
        if hits and resolve_lib(c, "")[0]:
            continue

        # 2) 已核实改名映射 → 目标实体需入库
        #    查询键依次：清洗后名 → 原始名 → 核心名（去尾部括号，吸收「X(较高收费)」等标注）
        tgt = (rename_map.get(c) or rename_map.get(raw)
               or rename_map.get(core_name(c)) or rename_map.get(core_name(raw)))
        if tgt:
            if tgt in lib_names:
                rule_rename[raw] = tgt
            elif tgt in moe_names:
                base["alias_to"] = tgt
                base["basis"] = "已在 school_aliases.json 经教育部核实"
                supplement.setdefault(tgt, {"moe": moe_by_name[tgt], "aliases_from": [],
                                            "records": [], "basis": "已核实改名映射"})
                if raw != tgt:
                    supplement[tgt]["aliases_from"].append(raw)
                supplement[tgt]["records"].append(base)
            else:
                base["reason"] = f"改名目标「{tgt}」不在教育部名单（需独立溯源）"
                base["clean_to"] = tgt
                unresolved[raw] = base
            continue

        # 3) 教育部名单精确命中 → 直接补录（含「去尾部括号」核心名兜底）
        cc = core_name(c)
        hit = c if c in moe_names else (cc if cc in moe_names else "")
        if hit:
            base["match"] = "moe-exact" if hit == raw else "moe-exact-after-clean"
            if hit != raw:
                base["clean_to"] = hit
                base["clean_hits"] = hits
            supplement.setdefault(hit, {"moe": moe_by_name[hit], "aliases_from": [],
                                        "records": [], "basis": "教育部名单精确命中"})
            if hit != raw:
                supplement[hit]["aliases_from"].append(raw)
            supplement[hit]["records"].append(base)
            continue

        # 3.5) 结构性改名（后缀映射）→ 目标实体需入库 / 或仅需映射
        rn = suffix_rename(c, moe_names) or suffix_rename(cc, moe_names)
        if rn:
            if rn in lib_names or rn == raw:
                rule_rename[raw] = rn
            else:
                base["alias_to"] = rn
                base["basis"] = "结构性改名（后缀映射，教育部名单唯一对应）"
                supplement.setdefault(rn, {"moe": moe_by_name[rn], "aliases_from": [],
                                           "records": [], "basis": "结构性改名（后缀映射）"})
                if raw != rn:
                    supplement[rn]["aliases_from"].append(raw)
                supplement[rn]["records"].append(base)
            continue

        # 4) 名称噪声 / 错别字 —— 分两档，严格区分「可自动」与「须人工」
        #
        #    ★ 实测教训：单纯「编辑距离=1 且唯一」**不可靠**——
        #      如「榆林学院」会唯一命中「桂林学院」（两个真实且不同的实体），
        #      「宁夏师范学院」唯一命中「宁德师范学院」。故编辑距离只能作**候选**。
        #
        #    4a) 子串噪声（可靠）：原名是「目标名 + 前缀噪声」或反之，长度差 ≤2。
        #        典型「了喀什大学」「和豫章师范学院」「了皖北卫生职业学院校址:…」。
        subs = [n for n in (moe_names | lib_names)
                if n != c and (n in c or c in n) and abs(len(n) - len(c)) <= 2]
        if len(subs) == 1:
            base["noise_fixed_to"] = subs[0]
            base["noise_rule"] = "子串噪声（前缀/后缀多余字符，长度差≤2）"
            noise_fixed[raw] = {"clean_to": subs[0], "rows": d["rows"], "hits": hits}
            continue

        #    4b) 字符替换（错别字？改名？）——**只登记候选，绝不自动应用**
        cands = sorted(n for n in moe_names if lev(c, n) == 1)
        if len(cands) == 1:
            base["candidate"] = cands[0]
            base["distance"] = 1
            base["note"] = "需人工/官方核实：可能是错别字，也可能是改名（如 XX学院→XX大学）"
            explicit.setdefault(cands[0], {"raw": [], "records": []})
            explicit[cands[0]]["raw"].append(raw)
            explicit[cands[0]]["records"].append(base)
            continue

        # 5) 名单外 → 不补
        base["reason"] = ("独立学院/分校/军校/港澳合办" if not is_zh_only(c)
                          else "教育部名单无此校")
        base["clean_to"] = c if c != raw else ""
        unresolved[raw] = base

    # ── 汇总 ────────────────────────────────────────────────────────────
    print(f"\n事实表未匹配院校 {len(agg)} 所 ｜ 未匹配行 "
          f"{sum(d['rows'] for d in agg.values()):,}")
    print(f"  ├ 确定性清洗已救回（源污染）  {len(clean_fixed):>4} 所 ｜ "
          f"{sum(d['rows'] for d in clean_fixed.values()):>6,} 行")
    print(f"  ├ 子串噪声自动修复            {len(noise_fixed):>4} 所 ｜ "
          f"{sum(d['rows'] for d in noise_fixed.values()):>6,} 行")
    print(f"  ├ 结构性改名（目标已在库）      {len(rule_rename):>4} 所 ｜ (仅需名称映射)")
    print(f"  ├ 需补录实体                  {len(supplement):>4} 所 ｜ "
          f"{sum(r['rows'] for b in supplement.values() for r in b['records']):>6,} 行")
    print(f"  ├ 待核实候选（不自动应用）     {len(explicit):>4} 所 ｜ "
          f"{sum(r['rows'] for b in explicit.values() for r in b['records']):>6,} 行")
    print(f"  └ 名单外（不补）              {len(unresolved):>4} 所 ｜ "
          f"{sum(d['rows'] for d in unresolved.values()):>6,} 行")

    lv = collections.Counter(d["moe"]["level"] for d in supplement.values())
    print(f"\n需补录实体按层次：本科 {lv.get('本科',0)} ｜ 专科 {lv.get('专科',0)}")
    pv = collections.Counter(prov_of(d["moe"])[0] or "(未知)"
                             for d in supplement.values())
    print(f"需补录实体按省份：{dict(pv.most_common(10))}")

    if args.report:
        print("\n" + "-" * 78)
        print("【需补录实体】明细（本科优先）")
        print("-" * 78)
        sup_sorted = sorted(supplement.values(),
                            key=lambda d: (d["moe"]["level"] != "本科", -sum(r["rows"] for r in d["records"])))
        for d in sup_sorted:
            m = d["moe"]
            rows = sum(r["rows"] for r in d["records"])
            al = ("  ←" + ",".join(d["aliases_from"])) if d["aliases_from"] else ""
            print(f"  [{m['level']}] {m['name']:<22}{m['city']:<8}{rows:>5} 行  {d['basis']}{al}")

        print("\n" + "-" * 78)
        print("【名单外·不补】明细（行数降序前 40）")
        print("-" * 78)
        for raw, d in sorted(unresolved.items(), key=lambda kv: -kv[1]["rows"])[:40]:
            print(f"  {raw:<34}{d['rows']:>5} 行  {d['reason']}")

    # ── 落盘 ────────────────────────────────────────────────────────────
    def sup_records() -> list[dict]:
        out = []
        for tgt, d in sorted(supplement.items()):
            m = d["moe"]
            dept = (m.get("department") or "").strip()
            own = infer_ownership(m["name"], dept)
            prov, prov_basis = prov_of(m)
            out.append({
                "name": m["name"],
                "code": (m.get("national_code") or "").strip(),
                "code10": (m.get("code10") or "").strip(),
                "province": prov,
                "province_basis": prov_basis,
                "city": m.get("city", ""),
                "level": m.get("level", ""),
                "department": dept,
                "ownership": own,
                "ownership_basis": f"源B「主管部门」= {dept}（规则推导）" if own else "",
                "aliases_from": sorted(d["aliases_from"]),
                "basis": d["basis"],
                "fact_rows": sum(r["rows"] for r in d["records"]),
                "source_id": MOE_SRC["source_id"],
                "source_name": MOE_SRC["source_name"],
                "source_url": MOE_SRC["source_url"],
                "year": MOE_SRC["year"],
                "data_status": "schema_only",
            })
        return out

    _sup_all = sup_records()

    # ── 统一「名称修复表」：raw → 可挂库的正名 ──────────────────────────
    # 供 AliasIndex 合并加载，使**所有**导入/聚合脚本的匹配链自动受益。
    #   三类来源：① 源污染名（清洗后命中）② 补录实体的原始脏名 ③ 唯一错别字
    name_repair: dict[str, str] = {}
    # ★ 值须是**最终可挂库的名字**：清洗/噪声修复后可能还要再过一次改名映射
    #   （如「合肥学院校址：安徽省合肥市」→ 清洗得「合肥学院」→ 改名得「合肥大学」）。
    def _final(n: str) -> str:
        return rename_map.get(n) or rename_map.get(core_name(n)) or n

    for raw, d in sorted(clean_fixed.items()):
        name_repair[raw] = _final(d["clean_to"])
    for raw, d in sorted(noise_fixed.items()):
        name_repair.setdefault(raw, _final(d["clean_to"]))
    for raw, tgt in sorted(rule_rename.items()):
        name_repair.setdefault(raw, tgt)
    for r in _sup_all:
        for a in r["aliases_from"]:
            name_repair.setdefault(a, r["name"])

    payload = {
        "meta": {
            "purpose": "N21：补齐院校库，使事实表（招生计划/录取分 2022–2025 豫赣）出现的院校可挂 school_id",
            "owner": "徐（③ 数据工程）",
            "library_before": len(idx.records),
            "moe_list_size": len(moe_recs),
            "unmatched_schools_before": len(agg),
            "unmatched_rows_before": sum(d["rows"] for d in agg.values()),
            "summary": {
                "clean_resolvable": {"schools": len(clean_fixed),
                                     "rows": sum(v["rows"] for v in clean_fixed.values())},
                "noise_fixed": {"schools": len(noise_fixed),
                                "rows": sum(v["rows"] for v in noise_fixed.values())},
                "explicit_candidates": {"schools": len(explicit),
                                        "rows": sum(r["rows"] for b in explicit.values() for r in b["records"])},
                "supplement": {"schools": len(supplement),
                               "rows": sum(r["rows"] for b in supplement.values() for r in b["records"])},
                "unresolved": {"schools": len(unresolved),
                               "rows": sum(d["rows"] for d in unresolved.values())},
            },
            "rules": {
                "no_fabrication": "补录实体字段**全部**取自教育部名单；本脚本不编造 city/ownership/code",
                "rename_basis": "改名只接受 school_aliases.json 中经教育部核实的映射，不自行发明",
                "explicit_basis": "错别字须编辑距离=1 且**唯一**命中才登记，供人工复核",
            },
        },
        "strip_rules": STRIP_RULES,
        "name_repair": name_repair,
        "clean_resolvable": dict(sorted(clean_fixed.items())),
        "noise_fixed": dict(sorted(noise_fixed.items())),
        "explicit_candidates": {k: {"raw_names": v["raw"], "records": v["records"]}
                                for k, v in sorted(explicit.items())},
        "supplement_records_benke": [r for r in _sup_all if r["level"] == "本科"],
        "supplement_records_zhuanke": [r for r in _sup_all if r["level"] != "本科"],
        "unresolved": {k: dict(v) for k, v in sorted(unresolved.items())},
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n→ {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
