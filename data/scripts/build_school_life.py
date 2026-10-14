# -*- coding: utf-8 -*-
"""
D4 · 生活信息（school_life）数据构建
=====================================
目标表：`school_life`（产品书 7.3、7.4；接口 6.5.4）
    id, school_id, category, content, source_type, source_name, source_url, year, reliability

★ 本轮**只采官方来源**（各高校官网「学校简介/学校概况」页 + 校园环境页），
  `reliability = official`，前端无需折叠。

真实评估（949 份官网简介页实测命中率）：

  | category     | 命中率 | 处理                     |
  |--------------|--------|--------------------------|
  | 校园环境      | 62%    | ✅ 产出（占地/建筑面积）  |
  | 图书馆        | 35%    | ✅ 产出（馆藏图书）       |
  | 宿舍          |  8%    | ❌ 不产出（多为「公寓管理先进单位」类噪声，非生活描述） |
  | 食堂          |  2%    | ❌ 不产出（同上）         |

  ⚠️ **宿舍 / 食堂 / 交通** 这三类**核心生活信息**，官网简介页承载极少，
  需走**非官方来源**（论坛/自媒体）或各校**后勤服务网**。
  前者涉及内容合规与来源可信度，须 ④/⑤/队长定策略；
  后者需逐校采集（入口深、覆盖率低，已试点验证不可行）。
  → 本轮如实**留空**，登记为 D4 的未完部分（见 `school_profile_D4采集报告.md`）。

用法：
    python build_school_life.py
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "data"
SCHOOLS = DATA / "schools" / "schools_merged.json"
OFFICIAL_INTRO = DATA / "schools" / "school_official_intro_supplement.json"
CACHE_SITE = DATA / "schools" / ".cache_site"
OUT = DATA / "schools" / "school_life_rows.json"

YEAR = 2026
OWNER = "徐（③ 数据工程）"

RE_SCRIPT = re.compile(r"(?is)<(script|style|noscript)\b.*?</\1>")
RE_TAG = re.compile(r"(?s)<[^>]+>")

# category → 正则。★ 模式**必须以「数字 + 单位」收尾**，否则会跨表格单元/相邻字段
# 拼接出无意义串（实测污染：「科生 4623 硕博研究生总占地面积 1.44 万亩」）。
# 非贪婪 `{0,30}?` + 强制单位收尾 ⇒ 片段被收在第一个数值单位处。
UNIT_AREA = r"(?:亩|万平方米|万㎡|公顷|平方米)"
UNIT_VOL = r"(?:万册|余万册|万种|册)"
UNIT_BLDG = r"(?:万平方米|万㎡|平方米)"
LIFE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("校园环境", re.compile(rf"占地面积[^。；;]{{0,30}}?[\d.]+\s*(?:余)?\s*{UNIT_AREA}")),
    ("校园环境", re.compile(rf"(?:总|校舍)?建筑面积[^。；;]{{0,26}}?[\d.]+\s*(?:余)?\s*{UNIT_BLDG}")),
    ("图书馆",   re.compile(rf"馆藏(?:纸质)?(?:图书|文献|资源)[^。；;]{{0,26}}?[\d.]+\s*(?:余)?\s*{UNIT_VOL}")),
    ("图书馆",   re.compile(rf"图书馆[^。；;]{{0,12}}馆藏[^。；;]{{0,26}}?[\d.]+\s*(?:余)?\s*{UNIT_VOL}")),
]
# 噪声：含以下字样的片段不是客观设施描述
NOISE = ("先进", "模范", "示范", "荣誉", "获奖", "表彰", "评比", "称号", "优秀单位",
         "先进集体", "单位", "基地", "平台", "项目")


def strip_html(h: str) -> str:
    h = RE_SCRIPT.sub(" ", h)
    h = RE_TAG.sub(" ", h)
    h = (h.replace("&nbsp;", " ").replace("&#160;", " "))
    h = re.sub(r"(?<=[\u4e00-\u9fa5])\s+(?=[\u4e00-\u9fa5])", "", h)
    return re.sub(r"\s+", " ", h).strip()


def cache_key(url: str, tag: str) -> Path:
    return CACHE_SITE / (re.sub(r"[^\w.-]", "_", url)[:120] + f".{tag}.html")


def fetch_text(url: str) -> str:
    for tag in ("intro", "home"):
        cf = cache_key(url, tag)
        if cf.exists():
            return strip_html(cf.read_text(encoding="utf-8", errors="ignore"))
    return ""


def extract_life(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = collections.defaultdict(list)
    if not text:
        return out
    for cat, pat in LIFE_PATTERNS:
        for m in pat.finditer(text):
            s = m.group(0).strip(" ，,、。；;·-")
            if len(s) < 10 or len(s) > 60:
                continue
            if any(n in s for n in NOISE):
                continue
            if s not in out[cat]:
                out[cat].append(s)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    print("=" * 76)
    print("D4 · 生活信息（school_life）构建 —— 仅官方来源")
    print("=" * 76)

    lib = json.loads(SCHOOLS.read_text(encoding="utf-8"))["records"]
    by_id = {r["id"]: r for r in lib}
    if not OFFICIAL_INTRO.exists():
        print(f"[err] 缺少 {OFFICIAL_INTRO.relative_to(ROOT)}")
        return 2
    intro = json.loads(OFFICIAL_INTRO.read_text(encoding="utf-8"))["records"]

    rows = []
    stat = collections.Counter()
    seen_cat = collections.Counter()
    for r in intro:
        sid, url, name = r.get("id"), (r.get("source_url") or "").strip(), r.get("name")
        if not sid or not url:
            stat["skip_no_url"] += 1
            continue
        text = fetch_text(url)
        if not text:
            stat["no_cache"] += 1
            continue
        stat["scanned"] += 1
        fields = extract_life(text)
        if not fields:
            stat["no_field"] += 1
            continue
        for cat, contents in fields.items():
            for c in contents[:2]:               # 每类最多 2 条
                rows.append({
                    "school_id": sid,
                    "school_name": name,
                    "category": cat,
                    "content": c,
                    "source_type": "官方",
                    "source_name": f"{name}官网·学校简介/学校概况",
                    "source_url": url,
                    "year": YEAR,
                    "reliability": "official",
                    "data_status": "schema_only",
                })
                stat[f"hit_{cat}"] += 1
        seen_cat[len(fields)] += 1

    if args.limit:
        rows = rows[: args.limit]

    payload = {
        "meta": {
            "generated_at": date.today().isoformat(),
            "owner": OWNER,
            "target_table": "school_life",
            "purpose": "生活信息（产品书 7.3/7.4，接口 6.5.4）",
            "reliability_note": "本表**全部为官方来源**（reliability=official），前端无需折叠。",
            "scope": "仅采官网简介页可支撑的两类：校园环境（占地/建筑面积）、图书馆（馆藏）。",
            "gap": "★ 宿舍 / 食堂 / 交通 三类核心生活信息，官网简介页承载极少（命中率 8% / 2%），"
                   "需非官方来源（涉及内容合规与可信度，须 ④/⑤/队长定策略）或逐校后勤网采集（已试点，不可行）。"
                   "故本轮**如实留空**，不作臆测填充。",
        },
        "records": rows,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n统计: {json.dumps(dict(stat), ensure_ascii=False)}")
    print(f"{'─' * 76}")
    print(f"共 {len(rows)} 行 → {OUT.relative_to(ROOT)}")
    cls = collections.Counter(r["category"] for r in rows)
    for k, v in cls.most_common():
        print(f"    {k:12s} {v}")
    print(f"    覆盖院校数: {len({r['school_id'] for r in rows})}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
