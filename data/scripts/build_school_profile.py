# -*- coding: utf-8 -*-
"""
D4 · 院校画像（school_profile）数据构建
========================================
目标表：`school_profile`（产品书 7.4；一校一行，`school_id` unique）

产出字段：
  | 字段                      | 来源                              | 等级     |
  |---------------------------|-----------------------------------|----------|
  | tuition_range             | 招生计划 CSV `tuition` 聚合        | 官方     |
  | established_year          | 校官网「学校简介/概况」页正文       | 高校官网 |
  | faculty_count             | 同上                              | 高校官网 |
  | student_faculty_ratio     | 同上                              | 高校官网 |
  | first_class_major_count   | 同上                              | 高校官网 |
  | campus_list               | 同上（校区名 + 城市）              | 高校官网 |
  | master_phd_points         | 同上（博士/硕士学位授权点）         | 高校官网 |
  | accommodation_fee         | —（官网简介页极少写，留空）        | —        |

★ 铁律
  1. **宁可缺，不可猜**：正则抽不到就留空，不做任何推断。
  2. `tuition` 是**数值直出**（招生计划原文），不加工表述。
  3. 官网抽取**忠实原文**，不做改写；抽取文本带 `source_url` 指向具体页面。

用法：
    python build_school_profile.py                 # 全量
    python build_school_profile.py --part a        # 只做 tuition 聚合
    python build_school_profile.py --part b        # 只做官网画像抽取
    python build_school_profile.py --limit 20      # 试点
    python build_school_profile.py --offline       # 只用页面缓存（不联网）
"""
from __future__ import annotations

import argparse
import collections
import csv
import glob
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent      # 仓库根
DATA = ROOT / "data"
RAW = DATA / "raw"
SCHOOLS = DATA / "schools" / "schools_merged.json"
OFFICIAL_INTRO = DATA / "schools" / "school_official_intro_supplement.json"
CACHE_SITE = DATA / "schools" / ".cache_site"
OUT = DATA / "schools" / "school_profile_rows.json"

YEAR = 2026          # 画像为「当前状态」，年份取采集年
OWNER = "徐（③ 数据工程）"

# ★ 来源三要素（依据 `source-table.json` 中 SRC-GAOKAO-COMPASS 的 plan：
#   「作品内事实结论的 source_url 须指向省考试院/阳光高考，不指向本数据集」）
SRC_TUITION_NAME = "河南省教育考试院 / 江西省教育考试院 普通高校招生计划（学费标准）"
PROV_URL = {"河南": "https://www.haeea.cn/", "江西": "http://www.jxeea.cn/"}
SRC_CHANNEL = "Gaokao-Compass-11M（MIT，DOI 10.57967/hf/9882）"
SRC_INTRO_NAME = "各高校官网「学校简介 / 学校概况」页"

# ── 本科批判定（招生计划必须按本科批过滤：专科批占 40%+，会污染 duration/tuition）──
def is_benke(batch: str) -> bool:
    b = (batch or "").strip()
    if not b:
        return False
    if "专" in b:            # 专科 / 高职（专科）
        return False
    return "本" in b or "本科" in b


# ── 院校索引（复用 import_major_score 的成熟逻辑）─────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_major_score import SchoolIndex, AliasIndex, normalize_school_name, core_name  # noqa: E402


# ══════════════════════════════════════════════════════════════════
# Part A · tuition_range（招生计划聚合）
# ══════════════════════════════════════════════════════════════════
def part_a(idx: SchoolIndex, alias: AliasIndex) -> tuple[dict[int, dict], dict]:
    """按 school_id 聚合本科批学费 → {school_id: {min,max,vals,years,provinces}}"""
    agg: dict[int, dict] = collections.defaultdict(
        lambda: {"vals": [], "years": set(), "provinces": set(), "unmatched_names": set()}
    )
    stats = collections.Counter()
    name_cache: dict[str, int | None] = {}

    for f in sorted(RAW.glob("*_enrollment-plan.csv")):
        parts = f.stem.split("_", 2)                 # 2025_henan_enrollment-plan
        if len(parts) < 3:
            continue
        year = int(parts[0])
        province = "河南" if "henan" in f.stem else "江西"
        with f.open(encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                stats["rows"] += 1
                if not is_benke(r.get("batch")):
                    stats["skip_not_benke"] += 1
                    continue
                raw_t = (r.get("tuition") or "").strip()
                if not raw_t or raw_t.upper() == "<NA>":
                    stats["skip_no_tuition"] += 1
                    continue
                try:
                    t = float(raw_t)
                except ValueError:
                    stats["skip_bad_tuition"] += 1
                    continue
                if t <= 0:                            # 0 = 未定/占位，非真实学费
                    stats["skip_zero_tuition"] += 1
                    continue
                nm = (r.get("university_name") or "").strip()
                if not nm or nm.upper() == "<NA>":
                    stats["skip_no_name"] += 1
                    continue
                sid = name_cache.get(nm, "?")
                if sid == "?":
                    sid = (idx.resolve_henan(r.get("university_code") or "")
                           or idx.resolve_name(nm))
                    # 别名回退：旧名 → 现名
                    if sid is None:
                        cur = alias.resolve(nm)
                        if cur:
                            sid = idx.resolve_name(cur)
                    name_cache[nm] = sid
                if sid is None:
                    stats["unmatched_rows"] += 1
                    agg[-1]["unmatched_names"].add(nm)
                    continue
                a = agg[sid]
                a["vals"].append(int(t))
                a["years"].add(year)
                a["provinces"].add(province)
                stats["used_rows"] += 1

    out: dict[int, dict] = {}
    for sid, a in agg.items():
        if sid == -1 or not a["vals"]:
            continue
        lo, hi = min(a["vals"]), max(a["vals"])
        out[sid] = {
            "tuition_range": str(lo) if lo == hi else f"{lo}-{hi}",
            "lo": lo, "hi": hi,
            "count": len(a["vals"]),
            "median": sorted(a["vals"])[len(a["vals"]) // 2],
            "years": sorted(a["years"]),
            "provinces": sorted(a["provinces"]),
        }
    stats["schools_with_tuition"] = len(out)
    stats["unmatched_school_names"] = len(agg[-1]["unmatched_names"])
    return out, dict(stats)


# ══════════════════════════════════════════════════════════════════
# Part B · 官网画像字段抽取
# ══════════════════════════════════════════════════════════════════
RE_SCRIPT = re.compile(r"(?is)<(script|style|noscript)\b.*?</\1>")
RE_TAG = re.compile(r"(?s)<[^>]+>")
RE_NUM_CN = r"([0-9]+(?:\.[0-9]+)?|[一二三四五六七八九十百千两]+)"

# 建校年份：以「创建/始建/建校/创办/前身…年」为主线
PAT_ESTABLISHED = [
    re.compile(r"(?:创建|始建|建校|创办|成立|诞生)于\s*(1[89]\d{2}|20\d{2})\s*年"),
    re.compile(r"(?:前身|其前身)[^。；;]{0,24}?(1[89]\d{2}|20\d{2})\s*年"),
    re.compile(r"(1[89]\d{2}|20\d{2})\s*年(?:创建|建校|创办|成立)"),
]
# 师资：教职工 / 专任教师 / 教职员工
PAT_FACULTY = [
    re.compile(r"(?:教职工|教职员工|在编教职工)\s*" + RE_NUM_CN + r"\s*余?\s*人"),
    re.compile(r"专任教师\s*" + RE_NUM_CN + r"\s*余?\s*人"),
    re.compile(r"现有?教职工\s*" + RE_NUM_CN + r"\s*余?\s*人"),
]
# 生师比
PAT_RATIO = [
    re.compile(r"生师比\s*(?:为|达|约|：|:)?\s*([0-9]+(?:\.[0-9]+)?)\s*[:：]\s*([0-9]+(?:\.[0-9]+)?)"),
    re.compile(r"生师比\s*(?:为|达|约|：|:)?\s*([0-9]+(?:\.[0-9]+)?)"),
]
# 一流本科专业建设点数量
PAT_FIRSTCLASS = [
    re.compile(r"国家级一流本科专业建设点\s*" + RE_NUM_CN + r"\s*个"),
    re.compile(r"一流本科专业建设点\s*" + RE_NUM_CN + r"\s*个"),
]
# 硕博点
PAT_PHD = re.compile(r"(?:博士学位授权)?一级学科博士(?:学位授权)?点\s*" + RE_NUM_CN + r"\s*个")
PAT_MASTER = re.compile(r"(?:硕士学位授权)?一级学科硕士(?:学位授权)?点\s*" + RE_NUM_CN + r"\s*个")
# 校区：中文没有词边界，滑动匹配 `{2,4}校区` 会吞掉前置动词/名词的末字
# （实测污染如「括黄河路校区」「作科学城校区」「位白云山校区」）。
# 因此**只在列举结构中抽取**——即「现有/设有/共有…A校区、B校区和C校区」，
# 覆盖率略降但质量可控（宁可缺，不可猜）。
RE_CAMPUS_LIST = re.compile(
    r"(?:现有|设有|共有|拥有|包括|下设|分为|建有|建成|分别在|分布于|有)\s*"
    r"((?:[\u4e00-\u9fa5]{2,4}校区)(?:\s*[、和及与]\s*(?:[\u4e00-\u9fa5]{2,4}校区))*)"
)
# 无引导词、但**至少两个校区名直接相连**的列举串（如「思明校区、漳州校区、翔安校区」）。
# 要求 ≥2 个「XX校区」相连 —— 单独一个「XX校区」不作数（无从界定词边界）。
RE_CAMPUS_CHAIN = re.compile(
    r"(?:[\u4e00-\u9fa5]{2,4}校区)(?:\s*[、和及与]\s*[\u4e00-\u9fa5]{2,4}校区)+"
)
RE_CAMPUS_ONE = re.compile(r"([\u4e00-\u9fa5]{2,4})校区")
RE_CAMPUS_SPLIT = re.compile(r"[、和及与]")

# 非校区名的常见误命中（数量词/泛称）
CAMPUS_BLACKLIST = {
    "两个", "三个", "多个", "四个", "五个", "每个", "各个", "一个",
    "校本", "老校", "新校", "北校", "南校", "东校", "西校", "主校", "分校",
    "多校", "各校", "本校", "该校", "全校", "跨校",
    "个校", "等校", "的校", "和校", "与校", "及校", "有校", "设校",
}

CN_DIGIT = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8,
            "九": 9, "十": 10, "两": 2, "百": 100, "千": 1000}


def cn2int(s: str) -> int | None:
    """把 '2300' / '两千三百' 这类转 int；转换失败返回 None（宁缺勿猜）。"""
    s = (s or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        return int(float(s))
    # 中文数字
    if not all(ch in CN_DIGIT for ch in s):
        return None
    if s == "十":
        return 10
    total, unit, num = 0, 1, 0
    for ch in reversed(s):
        v = CN_DIGIT[ch]
        if v >= 10:
            if num == 0:
                num = 1
            total += num * v
            num = 0
        else:
            num += v
    return total + num


def strip_html(h: str) -> str:
    h = RE_SCRIPT.sub(" ", h)
    h = RE_TAG.sub(" ", h)
    h = (h.replace("&nbsp;", " ").replace("&#160;", " ").replace("&amp;", "&")
          .replace("&ldquo;", "“").replace("&rdquo;", "”"))
    # 中文字符间被插空格的常见污染
    h = re.sub(r"(?<=[\u4e00-\u9fa5])\s+(?=[\u4e00-\u9fa5])", "", h)
    return re.sub(r"\s+", " ", h).strip()


def cache_key(url: str, tag: str) -> Path:
    return CACHE_SITE / (re.sub(r"[^\w.-]", "_", url)[:120] + f".{tag}.html")


def fetch_text(url: str, offline: bool) -> str:
    cf = cache_key(url, "intro")
    if cf.exists():
        return strip_html(cf.read_text(encoding="utf-8", errors="ignore"))
    cf2 = cache_key(url, "home")
    if cf2.exists():
        return strip_html(cf2.read_text(encoding="utf-8", errors="ignore"))
    return ""


def _first_num(pats, text: str) -> int | None:
    for p in pats:
        m = p.search(text)
        if m:
            v = cn2int(m.group(1))
            if v:
                return v
    return None


def extract_profile(text: str, name: str) -> dict:
    """从简介页正文抽取画像字段；抽不到的键不出现在结果里。"""
    out: dict = {}
    if not text:
        return out

    # 建校年份（合理区间 1850–2026，越界视为误命中）
    for p in PAT_ESTABLISHED:
        m = p.search(text)
        if m:
            y = int(m.group(1))
            if 1850 <= y <= date.today().year:
                out["established_year"] = y
                break

    # 师资人数（合理区间 100–30000）
    for p in PAT_FACULTY:
        m = p.search(text)
        if m:
            v = cn2int(m.group(1))
            if v and 100 <= v <= 30000:
                out["faculty_count"] = v
                break

    # 生师比
    for p in PAT_RATIO:
        m = p.search(text)
        if m:
            out["student_faculty_ratio"] = m.group(0).replace(" ", "")
            break

    # 一流本科专业建设点数（1–300）
    v = _first_num(PAT_FIRSTCLASS, text)
    if v and 1 <= v <= 300:
        out["first_class_major_count"] = v

    # 硕博点
    m = PAT_PHD.search(text)
    if m:
        v = cn2int(m.group(1))
        if v and 1 <= v <= 200:
            out["_phd_points"] = v
    m = PAT_MASTER.search(text)
    if m:
        v = cn2int(m.group(1))
        if v and 1 <= v <= 300:
            out["_master_points"] = v
    if "_phd_points" in out or "_master_points" in out:
        out["master_phd_points"] = {
            "master": out.pop("_master_points", None),
            "phd": out.pop("_phd_points", None),
        }

    # 校区：只在**列举结构**中抽取（见 RE_CAMPUS_LIST / RE_CAMPUS_CHAIN 注释）
    campuses: list[str] = []
    chunks = [m.group(1) for m in RE_CAMPUS_LIST.finditer(text)]
    chunks += RE_CAMPUS_CHAIN.findall(text)
    for chunk in chunks:
        for seg in RE_CAMPUS_SPLIT.split(chunk):
            seg = seg.strip()
            if not seg.endswith("校区"):
                continue
            name = seg[:-2]
            if not (2 <= len(name) <= 4) or name in CAMPUS_BLACKLIST:
                continue
            if any(ch in name for ch in "和及由有为与在于共设拥有个该"):
                continue
            if seg not in campuses:
                campuses.append(seg)
    # 去重：若某项以另一项结尾（如「括黄河路校区」⊃「黄河路校区」），只保留较短者
    campuses = [c for c in campuses
                if not any(c != o and c.endswith(o) for o in campuses)]
    if campuses:
        out["campus_list"] = [{"name": c, "address": "", "city": ""} for c in campuses[:12]]

    return out


def part_b(offline: bool = True) -> tuple[dict[int, dict], dict]:
    """从官方简介补丁的 source_url 定位缓存页 → 抽画像字段"""
    if not OFFICIAL_INTRO.exists():
        print(f"[warn] 缺少 {OFFICIAL_INTRO.relative_to(ROOT)}，跳过 Part B")
        return {}, {}
    d = json.loads(OFFICIAL_INTRO.read_text(encoding="utf-8"))
    recs = d.get("records", [])
    stats = collections.Counter()
    out: dict[int, dict] = {}
    for r in recs:
        sid = r.get("id")
        url = (r.get("source_url") or "").strip()
        if not sid or not url:
            stats["skip_no_url"] += 1
            continue
        text = fetch_text(url, offline)
        if not text:
            stats["no_cache"] += 1
            continue
        stats["scanned"] += 1
        fields = extract_profile(text, r.get("name") or "")
        if not fields:
            stats["no_field"] += 1
            continue
        fields["_profile_src_url"] = url
        out[sid] = fields
        for k in ("established_year", "faculty_count", "student_faculty_ratio",
                  "first_class_major_count", "master_phd_points", "campus_list"):
            if k in fields:
                stats[f"hit_{k}"] += 1
    return out, dict(stats)


# ══════════════════════════════════════════════════════════════════
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", choices=["a", "b", "all"], default="all")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--offline", action="store_true", default=True)
    args = ap.parse_args()

    print("=" * 76)
    print("D4 · 院校画像（school_profile）构建")
    print("=" * 76)

    lib = json.loads(SCHOOLS.read_text(encoding="utf-8"))
    lib_recs = lib["records"]
    by_id = {r["id"]: r for r in lib_recs}
    idx = SchoolIndex(SCHOOLS)
    alias = AliasIndex(DATA / "schools" / "school_aliases.json")

    rows: dict[int, dict] = {}

    if args.part in ("a", "all"):
        a, st = part_a(idx, alias)
        print(f"\n[Part A] 招生计划 tuition 聚合")
        for k, v in st.items():
            print(f"    {k:24s} {v}")
        for sid, v in a.items():
            rows.setdefault(sid, {})["tuition_range"] = v["tuition_range"]
            rows[sid]["_tuition_stats"] = {
                "min": v["lo"], "max": v["hi"], "median": v["median"],
                "sample_count": v["count"], "years": v["years"], "provinces": v["provinces"],
            }
        if args.limit:
            keep = set(sorted(a)[: args.limit])
            rows = {k: v for k, v in rows.items() if k in keep}

    if args.part in ("b", "all"):
        b, st = part_b(args.offline)
        print(f"\n[Part B] 官网简介页画像抽取")
        for k, v in st.items():
            print(f"    {k:24s} {v}")
        for sid, v in b.items():
            rows.setdefault(sid, {}).update(v)

    # ── 组装为 school_profile 行（一校一行）──
    out_recs = []
    for sid, f in sorted(rows.items()):
        src = by_id.get(sid)
        if not src:
            continue
        intro_url = f.get("_profile_src_url")
        stats_t = f.get("_tuition_stats") or {}
        provs = stats_t.get("provinces") or []
        if intro_url:                       # 有官网画像 → 以官网为主要来源
            s_name = SRC_INTRO_NAME
            if stats_t:
                s_name += " + 招生计划（学费）"
            s_url = intro_url
            s_type = "高校官网"
        else:                               # 仅学费 → 以省考试院为主要来源
            s_name = SRC_TUITION_NAME
            s_url = PROV_URL.get(provs[0] if provs else "河南", PROV_URL["河南"])
            s_type = "官方"
        row = {
            "school_id": sid,
            "school_name": src["name"],
            "province": src.get("province"),
            # ---- 模型字段 ----
            "tuition_range": f.get("tuition_range", ""),
            "accommodation_fee": "",                      # 官网简介页不载此信息 → 留空
            "campus_list": f.get("campus_list", []),
            "established_year": f.get("established_year"),
            "master_phd_points": f.get("master_phd_points"),
            "first_class_major_count": f.get("first_class_major_count"),
            "faculty_count": f.get("faculty_count"),
            "student_faculty_ratio": f.get("student_faculty_ratio", ""),
            # ---- 来源三要素（依主来源择一）----
            "source_name": s_name,
            "source_url": s_url,
            "year": YEAR,
            "source_type": s_type,
            "data_status": "schema_only",
            # ---- ③ 溯源（_ 前缀，不入模型）----
            "_tuition_stats": f.get("_tuition_stats"),
            "_source_channel": SRC_CHANNEL if stats_t else None,
        }
        out_recs.append(row)

    payload = {
        "meta": {
            "generated_at": date.today().isoformat(),
            "owner": OWNER,
            "target_table": "school_profile",
            "purpose": "院校画像：办学/费用信息（产品书 7.4、接口 6.5.3）",
            "one_row_per_school": True,
            "field_source": {
                "tuition_range": "招生计划 CSV `tuition` 字段（本科批）按校聚合 min-max，数值直出，排除 0",
                "established_year / faculty_count / student_faculty_ratio / "
                "first_class_major_count / campus_list / master_phd_points":
                    "各高校官网「学校简介/学校概况」页正文正则抽取（逐条见记录 source_url）",
                "accommodation_fee": "官网简介页不载 → 全部留空，待招生章程专项采集",
            },
            "caveat": "正则抽取**忠实原文、不做推断**；抽不到即留空（宁可缺不可猜）。"
                      "`campus_list` 仅含校区名，address/city 待补。",
        },
        "records": out_recs,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    n = len(out_recs)
    print(f"\n{'─' * 76}")
    print(f"共 {n} 行 → {OUT.relative_to(ROOT)}")
    if n:
        for k in ("tuition_range", "established_year", "faculty_count",
                  "student_faculty_ratio", "first_class_major_count",
                  "campus_list", "master_phd_points"):
            c = sum(1 for r in out_recs if r.get(k) not in (None, "", []))
            print(f"    {k:26s} {c}/{n} = {c / n * 100:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
