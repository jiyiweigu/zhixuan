# -*- coding: utf-8 -*-
"""
D3 · 招生章程 / 录取规则（enrollment_rule）数据构建
====================================================
目标表：`enrollment_rule`（产品书 7.3）
    id, school_id, year, content, subject_req, health_req, foreign_lang_req, source_id
    索引：(school_id, year)

★ 数据源与口径（务必如实理解）
  本脚本**不采招生章程原文**（章程需逐校抓官网，属独立采集任务），
  而是从 **Gaokao-Compass 招生计划数据集**（`data/raw/*_enrollment-plan.csv`）
  的 **专业级字段** 聚合出**院校级**要求：

    | 目标字段            | 源字段                          |
    |---------------------|---------------------------------|
    | `subject_req`       | 招生计划 `subject_req`          |
    | `health_req`        | 招生计划 `major_note`（体检类） |
    | `foreign_lang_req`  | 招生计划 `major_note`（语种类） |
    | `content`           | `major_note` 其余限制（性别等） |

  ⚠️ **语义边界**：专业备注是**专业级**的（如"某专业不招色盲"），
  聚合到院校级会失真（"该校不招色盲" ≠ 事实）。
  因此每条产出的文本**必须带「仅部分专业」限定**，绝不可写成全校要求。

★ 铁律
  1. 忠实原文：只做**归类与去重**，不改写表述。
  2. 抽不到即留空（宁可缺，不可猜）。
  3. 老高考年份（河南 ≤2024、江西 ≤2023）**无选科概念**，`subject_req` 留空而非报错。

用法：
    python build_enrollment_rule.py                # 全量
    python build_enrollment_rule.py --limit 30     # 试点
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
SCHOOLS = DATA / "schools" / "schools_merged.json"
OUT = DATA / "schools" / "enrollment_rule_rows.json"

SRC_ID = "SRC-GAOKAO-COMPASS"
# ★ 来源三要素（依据 `source-table.json` 中 SRC-GAOKAO-COMPASS 的 plan 字段：
#   「作品内事实结论的 source_url 须指向省考试院/阳光高考，不指向本数据集」）
SRC_NAME = "河南省教育考试院 / 江西省教育考试院 普通高校招生计划（专业备注）"
PROV_URL = {
    "河南": "https://www.haeea.cn/",       # 河南省教育考试院
    "江西": "http://www.jxeea.cn/",        # 江西省教育考试院
}
SRC_CHANNEL = "Gaokao-Compass-11M（MIT，DOI 10.57967/hf/9882）"
OWNER = "徐（③ 数据工程）"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_major_score import SchoolIndex, AliasIndex  # noqa: E402


def is_benke(batch: str) -> bool:
    b = (batch or "").strip()
    return bool(b) and "专" not in b and "本" in b


# ── 语种抽取 ───────────────────────────────────────────────────────────
LANGS = ("英语", "日语", "俄语", "德语", "法语", "西班牙语", "朝鲜语", "阿拉伯语")
RE_LANG = [
    re.compile(r"外语语种要求[：:]\s*([\u4e00-\u9fa5、，,和及]+)"),
    re.compile(r"只招\s*([\u4e00-\u9fa5、，,和及]{2,20}?)\s*语种"),
    re.compile(r"仅招\s*([\u4e00-\u9fa5、，,和及]{2,20}?)\s*语种"),
]
RE_LANG_HINT = re.compile(r"非英语语种考生慎重|小语种考生慎重|外语只用英语授课|外语仅用英语授课|全英文教学|不建议语种")

# ── 体检抽取 ───────────────────────────────────────────────────────────
# 按**优先级分类**：一条备注只归一类，避免「色盲色弱 / 色盲 / 色弱」三行重复。
# 顺序即优先级（先匹配者胜）。
HEALTH_RULES = [
    ("色盲色弱", re.compile(r"色盲[、,，\s]*色弱|色弱[、,，\s]*色盲|色盲色弱|不招(?:收)?[^。；;]{0,8}色盲[^。；;]{0,6}色弱")),
    ("色弱",     re.compile(r"不招(?:收)?[^。；;]{0,8}色弱|色弱(?:不予录取|限报|不宜|考生不能录取)")),
    ("色盲",     re.compile(r"不招(?:收)?[^。；;]{0,8}色盲|色盲(?:不予录取|限报|不宜|考生不能录取)")),
    ("色觉异常", re.compile(r"辨色(?:力)?异常|色觉异常|色觉障碍|辨色力")),
    ("视力",     re.compile(r"裸眼视力|矫正视力|视力(?:不低|要求|达到)")),
    ("乙肝",     re.compile(r"乙?肝|肝功能")),
    ("听力",     re.compile(r"听力(?:障碍|正常|不低于|要求)")),
    ("身高",     re.compile(r"身高(?:不低|要求|男生|女生|达到|限)")),
]
RE_HEALTH_ANY = re.compile(
    r"色盲|色弱|色觉|辨色|视力|裸眼|乙肝|肝功|听力|身高|体检|不予录取|限报"
)
# ── 性别（模型无字段 → 归入 content）──────────────────────────────────
RE_GENDER = re.compile(r"只招(男|女)生|性别要求[：:]\s*只招(男|女)生|仅招(男|女)生|原则上只招(男|女)生")


def norm_langs(s: str) -> list[str]:
    out = []
    for tok in re.split(r"[、，,和及]", s or ""):
        tok = tok.strip()
        for L in LANGS:
            if tok and (tok == L or L.startswith(tok) and len(tok) >= 2):
                if L not in out:
                    out.append(L)
    if not out:
        for L in LANGS:
            if L in (s or ""):
                out.append(L)
    return out


def classify_health(note: str) -> tuple[str, str]:
    """→ (归一条件, 原文片段)。未命中返回 ('','')。"""
    if not note:
        return "", ""
    for cond, pat in HEALTH_RULES:
        if pat.search(note):
            return cond, ""
    if RE_HEALTH_ANY.search(note):
        return "其他体检要求", note[:48]      # 保留原文片段，不臆断归因
    return "", ""


def extract_note(note: str) -> dict:
    """从一条 major_note 抽取 (体检条件, 语种有序列表, 性别)

    ★ 语种用**有序 list**（非 set）—— set 的遍历顺序受 PYTHONHASHSEED 影响，
      会导致下游 Counter 插入顺序漂移、产物 md5 每次不同（破坏幂等）。
    """
    r = {"health": "", "health_raw": "", "langs": [], "gender": ""}
    if not note:
        return r
    r["health"], r["health_raw"] = classify_health(note)
    for p in RE_LANG:
        m = p.search(note)
        if m:
            for L in norm_langs(m.group(1)):
                if L not in r["langs"]:
                    r["langs"].append(L)
    if RE_LANG_HINT.search(note) and "英语" not in r["langs"]:
        r["langs"].append("英语")          # 原文语焉「英语授课 / 非英语慎重报考」→ 限英语
    m = RE_GENDER.search(note)
    if m:
        r["gender"] = f"只招{m.group(1) or m.group(2)}生"
    return r


def fmt_block(title: str, n_major: int, lines: list[str]) -> str:
    """构造带「仅部分专业」限定的忠实文本块"""
    if not lines:
        return ""
    return (
        f"【适用范围】仅部分专业（{n_major} 个），**非全校统一要求**\n"
        f"【{title}】" + "；".join(lines) + "\n"
        f"【来源】{SRC_NAME}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    print("=" * 76)
    print("D3 · 招生章程/录取规则（enrollment_rule）构建")
    print("=" * 76)

    idx = SchoolIndex(SCHOOLS)
    alias = AliasIndex(DATA / "schools" / "school_aliases.json")

    # agg[(sid, year)] = {...}
    agg: dict[tuple[int, int], dict] = collections.defaultdict(lambda: {
        "subj": collections.Counter(), "health": collections.Counter(),
        "health_raw": collections.Counter(), "lang": collections.Counter(),
        "gender": collections.Counter(),
        "n_note": 0, "n_subj": 0, "n_health": 0, "n_lang": 0, "n_gender": 0,
        "provinces": set(),
    })
    name_cache: dict[str, int | None] = {}
    stats = collections.Counter()

    files = sorted(RAW.glob("*_enrollment-plan.csv"))
    if args.limit:
        files = files[:1]

    for f in files:
        year = int(f.stem.split("_", 1)[0])
        province = "河南" if "henan" in f.stem else "江西"
        with f.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                stats["rows"] += 1
                if not is_benke(row.get("batch")):
                    stats["skip_not_benke"] += 1
                    continue
                nm = (row.get("university_name") or "").strip()
                if not nm or nm.upper() == "<NA>":
                    stats["skip_no_name"] += 1
                    continue
                sid = name_cache.get(nm, "?")
                if sid == "?":
                    sid = (idx.resolve_henan(row.get("university_code") or "")
                           or idx.resolve_name(nm))
                    if sid is None:
                        cur = alias.resolve(nm)
                        if cur:
                            sid = idx.resolve_name(cur)
                    name_cache[nm] = sid
                if sid is None:
                    stats["unmatched_rows"] += 1
                    continue
                a = agg[(sid, year)]
                a["provinces"].add(province)

                s = (row.get("subject_req") or "").strip()
                if s and s.upper() != "<NA>":
                    a["subj"][s] += 1
                    a["n_subj"] += 1

                note = (row.get("major_note") or "").strip()
                if note and note.upper() != "<NA>":
                    ex = extract_note(note)
                    if ex["health"] or ex["langs"] or ex["gender"]:
                        a["n_note"] += 1
                    if ex["health"]:
                        a["health"][ex["health"]] += 1
                        a["n_health"] += 1
                        if ex["health_raw"]:
                            a["health_raw"][ex["health_raw"]] += 1
                    for L in ex["langs"]:
                        a["lang"][L] += 1
                    if ex["langs"]:
                        a["n_lang"] += 1
                    if ex["gender"]:
                        a["gender"][ex["gender"]] += 1
                        a["n_gender"] += 1
                if args.limit and stats["rows"] > 4000:
                    break

    # ── 组装 ──
    lib = json.loads(SCHOOLS.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in lib["records"]}
    out = []
    for (sid, year), a in sorted(agg.items()):
        src = by_id.get(sid)
        if not src:
            continue
        health_lines = [f"{c}（{n} 个专业）" for c, n in a["health"].most_common()]
        # 「其他体检要求」保留原文片段，避免臆断归因
        for raw, n in a["health_raw"].most_common(3):
            health_lines.append(f"原文：「{raw}」（{n} 个专业）")
        health = fmt_block("体检要求", a["n_health"], health_lines)
        lang = fmt_block("外语语种要求", a["n_lang"],
                         [f"限{L}（{n} 个专业）" for L, n in a["lang"].most_common()])
        # content：章程正文未采 → 填「其余限制」摘要（性别等），并显式声明非章程原文
        others = []
        if a["gender"]:
            others.append("性别要求：" + "；".join(f"{g}（{n} 个专业）" for g, n in a["gender"].most_common()))
        content = ""
        if others:
            content = (
                "【说明】本字段**非招生章程原文**，系招生计划专业备注中的其他限制汇总\n"
                + "\n".join(others) + "\n"
                f"【来源】{SRC_NAME}"
            )
        # subject_req：保留原文取值 + 频次（不归一，避免失真）
        subj_txt = ""
        if a["subj"]:
            subj_txt = (
                f"【覆盖】该校 {year} 年在 " + "、".join(sorted(a["provinces"], reverse=True))
                + f" 招生计划共 {a['n_subj']} 条记录\n"
                "【选科要求取值（原文·频次）】"
                + "；".join(f"{k}（{v}）" for k, v in a["subj"].most_common()) + "\n"
                f"【来源】{SRC_NAME}"
            )
        if not (health or lang or subj_txt or content):
            continue
        provs = sorted(a["provinces"])
        out.append({
            "school_id": sid,
            "school_name": src["name"],
            "year": year,
            "content": content,
            "subject_req": subj_txt,
            "health_req": health,
            "foreign_lang_req": lang,
            "source_id": SRC_ID,
            "source_name": SRC_NAME,
            "source_url": PROV_URL["河南" if "河南" in provs else provs[0]],
            "source_type": "官方",
            "data_status": "schema_only",
            "_provinces": provs,
            "_major_rows_with_note": a["n_note"],
            "_source_channel": SRC_CHANNEL,
        })

    payload = {
        "meta": {
            "generated_at": date.today().isoformat(),
            "owner": OWNER,
            "target_table": "enrollment_rule",
            "purpose": "招生章程/录取规则（产品书 7.3）",
            "basis": "Gaokao-Compass 招生计划数据集的专业级字段聚合；**未采招生章程原文**",
            "semantics_caveat": "★ 专业备注为专业级，聚合至院校级后**必须带「仅部分专业」限定**，"
                                "不得表述为全校统一要求。`content` 亦非章程原文。",
            "scope": "仅本科批；老高考年份（河南≤2024、江西≤2023）无选科概念，subject_req 为空",
            "source_id": SRC_ID,
            "source_channel": SRC_CHANNEL,
            "source_attribution": "数据由省考试院发布、经 Gaokao-Compass-11M 数据集分发；"
                                  "依 SRC-GAOKAO-COMPASS 的 plan 要求，source_url 指向省考试院而非数据集。",
            "not_official_charter": "★ 本表**不是招生章程原文**。章程正文需逐校抓官网，属独立采集任务（content 字段因此基本为空）。",
        },
        "records": out,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    n = len(out)
    print(f"\n聚合统计: {json.dumps(dict(stats), ensure_ascii=False)}")
    print(f"{'─' * 76}")
    print(f"共 {n} 行 → {OUT.relative_to(ROOT)}")
    for k in ("subject_req", "health_req", "foreign_lang_req", "content"):
        c = sum(1 for r in out if r.get(k))
        print(f"    {k:20s} {c}/{n} = {(c / n * 100 if n else 0):.1f}%")
    yr = collections.Counter(r["year"] for r in out)
    print(f"    年份分布: {dict(sorted(yr.items()))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
