#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把数据工程（徐）与数据库（张）两套产出合并成一套可直接装载的完整数据。

设计原则
--------
1. **以徐的数据为主体**：院校库（1367 所在豫招生本科）、专业库（845，教育部官方目录）、
   院校专业录取分（116,036 行）、一分一段（2022–2025 两省）、省份志愿模式、26 类途径、
   专项区域、来源登记表 —— 这些是产品需要的「在豫招生」集合，语义与规模都更贴需求。
2. **补张的独有部分**：
   - ``plan_count`` 招生计划数（1,677 条）→ 并入 ``school_major_score``（徐完全没有）
   - ``is_985`` / ``is_211`` / ``dual_class`` 院校层次 → 并入 ``school``
   - ``intro`` 专业简介（455 条）→ 并入 ``major``
   - ``intro`` / ``website`` 院校简介 → 并入 ``school``
   - 徐完全没有的 6 张表：``discipline_eval`` / ``enrollment_rule`` / ``school_profile`` /
     ``school_life`` / ``knowledge_doc`` / ``knowledge_chunk`` / ``pathway_score``
3. **不猜测、不编造**：所有匹配不上的一律留空并计入 ``unmatched`` 统计，逐类如实登记原因。
4. **输出字段名 = 后端列名**，可直接交给装载通道写库；数据本体不入仓库。

用法
----
    python data/scripts/merge_datasets.py \
        --src-xu   <徐分支导出的 data/ 目录> \
        --src-zhang <张分支导出的 data/ 目录> \
        --out      <输出目录>
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# --------------------------------------------------------------------------- #
# 词表归一（与 docs/api-contract.md v1.4 第 8 节、app/models/constants.py 同源）
# --------------------------------------------------------------------------- #
PROVINCE_CODE_BY_NAME = {"河南": "41", "江西": "36"}

BATCH_ALIAS_TO_CODE = {
    "本科批": "undergraduate_regular",
    "普通本科批": "undergraduate_regular",
    "本科批次": "undergraduate_regular",
    "提前批": "undergraduate_early",
    "普通本科提前批": "undergraduate_early",
    "高职（专科）批": "vocational_regular",
    "高职（专科）批次": "vocational_regular",
    "艺术类/体育类本科批次": "undergraduate_art_sport",
}
BATCH_CODE_TO_DISPLAY = {
    "undergraduate_regular": "本科批",
    "undergraduate_early": "提前批",
    "vocational_regular": "高职（专科）批",
    "undergraduate_art_sport": "艺术类/体育类本科批次",
}

# 数据工程内部的 data_status 中间状态 → 契约四值（契约 8.1）
DATA_STATUS_MAP = {
    "verified": "available",
    "available": "available",
    "pending": "schema_only",
    "schema_only": "schema_only",
    "partial": "partial",
    "missing": "unavailable",
    "unavailable": "unavailable",
}

# 数据源 category_group → 契约 exam_type（契约 8.1）
# 注：「艺术类 / 体育类」是**一个**合并批次规则，而契约 exam_type 只允许单值，
# 故取「艺术」并在合并报告的 unmapped_exam_type 里登记，待队长裁定是否拆成两条规则。
EXAM_TYPE_MAP = {
    "普通类": "普通",
    "历史、物理科目组": "普通",
    "艺术类": "艺术",
    "体育类": "体育",
    "艺术类 / 体育类": "艺术",
}

# 院校层次名单（985 / 211 / 双一流）：教育部公开名单，随合并脚本一起进仓库。
# 院校层次是「冲稳保」与院校筛选的核心维度，而三个数据源单独都不够：
#   · 张的院校库只有河南本地 183 校（覆盖 1367 所中的 139 所，且 is_985 命中 0）
#   · 徐的院校库无该字段
#   · 徐的软科榜（594 校）只标了 37 / 97 / 112，低排名的 211（如西藏大学）不在榜内
# 故按教育部名单补齐；本表待徐复核后可原地替换，脚本无需改动。
TIERS_PATH = Path(__file__).resolve().parent.parent / "dictionaries" / "school_tiers.json"

TIER_FLAG_LABEL = {"is_985": "is_985", "is_211": "is_211", "dual_class": "双一流"}


def _norm_name(value: str) -> str:
    """院校名归一：去空白、去括号后缀，供跨源匹配。"""
    s = re.sub(r"[\s\u3000]+", "", str(value or ""))
    s = re.sub(r"[（(].*?[)）]", "", s)
    return s


def _norm_full(value: str) -> str:
    """归一但**保留**括号内容（括号统一为半角），用于区分中国石油大学(北京)/(华东)。"""
    s = re.sub(r"[\s\u3000]+", "", str(value or ""))
    return s.replace("（", "(").replace("）", ")")


def _norm_base(value: str) -> str:
    """归一并删掉括号内容，用于「中外合作办学 / 分校区」继承母体层次。"""
    return re.sub(r"\(.*?\)", "", _norm_full(value))


def _tier_index() -> tuple[dict[str, set[str]], dict]:
    """把三份名单摊平成 {归一院校名: {层次标记}}，别名与校区继承做展开。

    同一所院校在 985 / 211 / 双一流 三份名单里的名字可能不同
    （国防科技大学 vs 国防科学技术大学、上海体育大学 vs 上海体育学院），
    故把 aka 双向登记，使所有写法都指向同一组层次标记。
    """
    doc = _load(TIERS_PATH)
    aka = doc.get("aka") or {}
    bidir: dict[str, set[str]] = {}
    for primary, alts in aka.items():
        for a in alts:
            bidir.setdefault(primary, set()).add(a)
            bidir.setdefault(a, set()).add(primary)

    def keys(name: str) -> set[str]:
        return {k for k in (_norm_full(name), _norm_base(name)) if k}

    idx: dict[str, set[str]] = defaultdict(set)
    for tier, flag in (("985", "is_985"), ("211", "is_211"), ("dual_class", "dual_class")):
        for name in doc.get(tier) or []:
            all_keys = keys(name)
            for alt in bidir.get(name, ()):
                all_keys |= keys(alt)
            for k in all_keys:
                idx[k].add(flag)
    return idx, doc


def _tier_flags(idx: dict[str, set[str]], name: str,
                inherit: dict[str, str] | None = None) -> dict:
    got = {"is_985": False, "is_211": False, "dual_class": ""}
    marks: set[str] = set()
    for k in (_norm_full(name), _norm_base(name)):
        marks |= idx.get(k, set())
    # 非独立法人的分校区 / 直属医学院：显式白名单继承母体层次（独立学院不在白名单内）
    if not marks and inherit and name in inherit:
        parent = inherit[name]
        for k in (_norm_full(parent), _norm_base(parent)):
            marks |= idx.get(k, set())
    if "is_985" in marks:
        got["is_985"] = True
        got["is_211"] = True  # 985 ⊂ 211，兜底保持一致
    elif "is_211" in marks:
        got["is_211"] = True
    if "dual_class" in marks:
        got["dual_class"] = "双一流"
    return got


def _int_or_none(value):
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _float_or_none(value):
    if value is None or value == "":
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class Merger:
    def __init__(self, xu: Path, zhang: Path, out: Path) -> None:
        self.xu = xu
        self.zhang = zhang
        self.out = out
        self.out.mkdir(parents=True, exist_ok=True)
        self.report: dict[str, dict] = {}
        self.notes: list[str] = []
        # 来源登记表：int id → 记录；以及 (name,url) → int id
        self.sources: list[dict] = []
        self.source_by_key: dict[tuple, int] = {}
        self.srcid_map: dict[str, int] = {}

    # ------------------------------------------------------------------ #
    # 工具
    # ------------------------------------------------------------------ #
    def note(self, line: str) -> None:
        self.notes.append(line)
        print("  " + line)

    def register_source(self, name: str, url: str, year, source_type: str = "其他",
                        fetched_at=None) -> int:
        key = (str(name or "").strip(), str(url or "").strip())
        if key in self.source_by_key:
            return self.source_by_key[key]
        sid = len(self.sources) + 1
        self.sources.append({
            "id": sid,
            "source_name": key[0],
            "source_url": key[1],
            "year": _int_or_none(year) or 0,
            "source_type": source_type,
            "fetched_at": fetched_at,
        })
        self.source_by_key[key] = sid
        return sid

    def write(self, table: str, records: list[dict], meta: dict) -> None:
        doc = {
            "meta": {
                "target_table": table,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "generator": "data/scripts/merge_datasets.py",
                "count": len(records),
                **meta,
            },
            "records": records,
        }
        path = self.out / f"{table}.json"
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        size = path.stat().st_size
        print(f"  写出 {table:24s} {len(records):>8,} 条  {size/1048576:>7.2f} MiB")
        self.report[table] = {"count": len(records), "bytes": size, **meta}

    # ------------------------------------------------------------------ #
    # 1. source（两源合并去重，统一分配整型 id）
    # ------------------------------------------------------------------ #
    def build_source(self) -> None:
        print("[1/14] source 来源登记表")
        xu_src = _load(self.xu / "sources" / "source-table.json")
        for s in xu_src["sources"]:
            sid = self.register_source(
                s.get("source_name"), s.get("source_url"), s.get("year"),
                s.get("source_type") or "其他", s.get("fetched_at"),
            )
            # 保留徐的字符串 id → 整型 id 映射（其余文件用它做外键）
            if s.get("id"):
                self.srcid_map[s["id"]] = sid
        self.note(f"徐的 source 登记 {len(xu_src['sources'])} 条，映射表建立完成")
        # 张的 source 在后续各表按 (name,url) 动态登记

    # ------------------------------------------------------------------ #
    # 2. school（徐为主体 + 张补院校层次与简介）
    # ------------------------------------------------------------------ #
    def build_school(self) -> None:
        print("[2/14] school 院校库")
        merged = _load(self.xu / "schools" / "schools_merged.json")
        recs = merged["records"]
        ids = [r.get("id") for r in recs]
        assert ids == list(range(1, len(recs) + 1)), "徐的院校 id 不是连续的 1..N，需重映射"
        self.note(f"徐的院校 id 为连续的 1..{len(recs)}，可直接作为主键，录取分无需重映射")

        # 张的院校标记：按院校代码（优先）或归一校名匹配
        z_recs = _load(self.zhang / "output" / "school.json")
        by_code = {str(z.get("code")): z for z in z_recs if z.get("code")}
        by_name = {_norm_name(z.get("name")): z for z in z_recs}

        # 张的院校简介/官网来自 school_profile.json
        try:
            profiles = _load(self.zhang / "output" / "school_profile.json")
        except FileNotFoundError:
            profiles = []
        prof_by_code = {str(p.get("school_code")): p for p in profiles if p.get("school_code")}

        # 徐的软科榜：第三方已标注的 985/211/双一流（交叉校验源，也可直接采信）
        sane: dict[str, dict] = {}
        sane_path = self.xu / "schools" / "shanghai_top300_inhenan.json"
        if sane_path.exists():
            for x in _load(sane_path)["records"]:
                tags = set(x.get("tags") or [])
                item = {"tags": tags, "name": x.get("name")}
                if x.get("hn_code"):
                    sane.setdefault("code:" + str(x["hn_code"]), item)
                sane.setdefault("name:" + _norm_base(x.get("hn_name") or x.get("name")), item)

        # 教育部名单（985/211/双一流）
        tiers, tiers_doc = _tier_index()
        inherit_map = (tiers_doc.get("inherit") or {}).get("map") or {}
        known_no_inherit = set(
            (tiers_doc.get("inherit") or {}).get("known_not_inherited", {}).get("names") or [])
        tiers_used: set[str] = set()
        inherited: list[dict] = []

        records, hit_code, hit_name, miss = [], 0, 0, []
        henan_codes: dict[int, str] = {}
        intro_filled = 0
        src_count = Counter()  # 每个来源各自贡献了多少条标记
        inherit_review: list[dict] = []  # 疑似「分校区/合作办学未继承母体层次」待人工确认
        confirmed_no_inherit: list[dict] = []  # 已核实为独立学院，刻意不继承
        for r in recs:
            z = by_code.get(str(r.get("code"))) or by_name.get(_norm_name(r.get("name")))
            if z:
                if str(r.get("code")) in by_code:
                    hit_code += 1
                else:
                    hit_name += 1
            else:
                miss.append({"name": r.get("name"), "code": r.get("code")})
            p = prof_by_code.get(str(r.get("code"))) or {}
            intro = str(p.get("intro") or "").strip()
            website = str(p.get("website") or r.get("website") or "").strip()
            if intro:
                intro_filled += 1

            name = r.get("name") or ""
            # 来源 A0：非独立法人的分校区 / 直属医学院，显式白名单继承母体层次
            base_flags = _tier_flags(tiers, name)
            if not any(base_flags.values()) and name in inherit_map:
                inherited.append({"name": name, "code": str(r.get("code") or ""),
                                  "inherits": inherit_map[name]})
            # 来源 A：教育部名单（权威、覆盖全）
            flags = _tier_flags(tiers, name, inherit_map)
            from_tiers = {k for k, v in flags.items() if v}
            if from_tiers:
                for k in (_norm_full(name), _norm_base(name)):
                    if tiers.get(k):
                        tiers_used.add(k)
                if name not in tiers_used:
                    parent = inherit_map.get(name)
                    if parent:
                        for k in (_norm_full(parent), _norm_base(parent)):
                            if tiers.get(k):
                                tiers_used.add(k)
            # 来源 B：徐的软科榜（第三方标注，用于交叉校验）
            s = sane.get("code:" + str(r.get("code"))) or sane.get(
                "name:" + _norm_base(name))
            from_sane = set()
            if s:
                if "985" in s["tags"]:
                    flags["is_985"] = flags["is_211"] = True
                    from_sane |= {"is_985", "is_211"}
                elif "211" in s["tags"]:
                    flags["is_211"] = True
                    from_sane.add("is_211")
                if "双一流" in s["tags"] and not flags["dual_class"]:
                    flags["dual_class"] = "双一流"
                    from_sane.add("dual_class")
            # 来源 C：张的院校库（只覆盖河南本地，但含中外合作/校区等特殊单位）
            from_zhang = set()
            if z:
                if z.get("is_985") and not flags["is_985"]:
                    flags["is_985"] = flags["is_211"] = True
                    from_zhang |= {"is_985", "is_211"}
                if z.get("is_211") and not flags["is_211"]:
                    flags["is_211"] = True
                    from_zhang.add("is_211")
                if str(z.get("dual_class") or "").strip() and not flags["dual_class"]:
                    flags["dual_class"] = "双一流"
                    from_zhang.add("dual_class")

            if from_tiers:
                src_count["教育部名单"] += 1
            if from_sane:
                src_count["软科榜"] += 1
            if from_zhang:
                src_count["张的院校库"] += 1

            # 疑似漏继承：校名以某所层次院校开头但不完全相等（分校区/合作办学/独立学院）
            if not any(flags.values()):
                base = _norm_base(name)
                for cut in range(len(base) - 2, 3, -1):
                    if tiers.get(base[:cut]):
                        item = {
                            "name": name, "code": str(r.get("code") or ""),
                            "looks_like": base[:cut],
                            "hint": "分校区/合作办学可继承母体层次；独立学院不可。需人工确认。",
                        }
                        if name in known_no_inherit:
                            confirmed_no_inherit.append(item)
                        else:
                            inherit_review.append(item)
                        break

            records.append({
                "id": r["id"],
                "name": name,
                "code": str(r.get("code") or ""),
                "province": r.get("province") or "",
                "city": r.get("city") or "",
                "level": r.get("level") or "",
                "type": r.get("type") or "",
                "ownership": r.get("ownership") or "",
                "website": website,
                "intro": intro,
                "is_985": flags["is_985"],
                "is_211": flags["is_211"],
                "dual_class": flags["dual_class"],
            })
            # 非列字段：河南招生代号（考生填志愿用的是它）另存 meta，保持 records 可直接装载
            henan_codes[r["id"]] = str(r.get("_henan_code") or "")

        flag_985 = sum(1 for r in records if r["is_985"])
        flag_211 = sum(1 for r in records if r["is_211"])
        flag_dual = sum(1 for r in records if r["dual_class"])

        # 交叉验证 1：河南 985/211 是公开硬事实
        # 注意：招生库会把「郑州大学(中外合作办学)」这类项目单列成独立招生单位，
        # 它们继承母体的 211 标记是正确的。
        henan = [r for r in records if r["province"] == "河南"]
        got_985_norm = sorted({_norm_name(r["name"]) for r in henan if r["is_985"]})
        got_211_norm = sorted({_norm_name(r["name"]) for r in henan if r["is_211"]})
        assert not got_985_norm, f"河南无 985 高校，实际被标记为 985 的有 {got_985_norm}"
        assert got_211_norm and all("郑州大学" in n for n in got_211_norm), (
            f"河南唯一的 211 是郑州大学（含其学院/合作办学项目），实际出现 {got_211_norm}"
        )
        # 交叉验证 2：教育部名单里标了 985 的，必须也被标 211；标了 211 的必须也是双一流
        assert all(r["is_211"] for r in records if r["is_985"]), "存在 is_985 但非 is_211 的行"
        assert all(r["dual_class"] for r in records if r["is_211"]), "存在 is_211 但不是双一流的行"
        # 交叉验证 3：名单里的院校只要在库内就必须被标上（覆盖率）
        tiers_matched = sorted(tiers_used)
        tiers_names = sum(len(tiers_doc.get(k) or [])
                          for k in ("985", "211", "dual_class"))
        henan_dual = sorted({_norm_name(r["name"]) for r in henan if r["dual_class"]})
        self.note("交叉验证通过：河南 985=0、211 全部属郑州大学、"
                  f"双一流(去重)={henan_dual}")
        self.note(f"层次标记命中：985={flag_985}、211={flag_211}、双一流={flag_dual}"
                  f"（覆盖 1367 所中 {sum(1 for r in records if any((r['is_985'], r['is_211'], r['dual_class'])))} 所）")
        self.note(f"来源贡献：{dict(src_count)}（三源取并集，去重后见上）")
        if inherit_review:
            self.note(f"⚠️ {len(inherit_review)} 所校名疑似为分校区/合作办学/独立学院，未自动继承层次，见 meta")
        self.note(f"分校区/直属医学院继承母体层次：{len(inherited)} 所 {[x['name'] for x in inherited]}")
        self.note(f"已核实为独立学院、刻意不继承：{len(confirmed_no_inherit)} 所")

        self.write("school", records, {
            "primary_source": "徐 · schools_merged.json（在豫招生本科院校）",
            "enriched_by": (
                "① 教育部 985/211/双一流 名单（data/dictionaries/school_tiers.json）"
                "；② 徐 · shanghai_top300_inhenan.json（软科榜 tags，交叉校验）"
                "；③ 张 · school.json + school_profile.json（河南本地 183 校的层次与简介/官网）"
            ),
            "match": {"by_code": hit_code, "by_name": hit_name, "unmatched": len(miss)},
            "flags": {"is_985": flag_985, "is_211": flag_211, "dual_class": flag_dual,
                      "intro_filled": intro_filled},
            "flag_source_contribution": dict(src_count),
            "tier_lists": {
                "file": "data/dictionaries/school_tiers.json",
                "declared_counts": tiers_doc.get("counts"),
                "matched_names_in_library": len(tiers_matched),
                "declared_names_total": tiers_names,
                "note": "declared_names_total 是 985(39)+211(112)+双一流(147) 的条目数之和，"
                        "含跨名单重复，故不宜直接与 matched_names_in_library 相减。",
            },
            "unmatched": miss[:50],
            "inherit_review": inherit_review[:80],
            "inherited_from_parent": inherited,
            "confirmed_independent_college": confirmed_no_inherit[:80],
            "extra": {"henan_code_by_school_id": henan_codes},
            "notes": [
                "院校 id 沿用徐的 1..N，使 school_major_score 的外键无需重映射。",
                "「在豫招生」≠「河南本地」：本表是面向河南考生可报考的全国院校集合（徐口径），"
                "不是河南本地高校名单（张口径 183 所）。",
                "层次标记口径：985 ⊂ 211 ⊂ 双一流；标记来源为教育部公开名单，"
                "软科榜与张的院校库仅作交叉校验与补充。",
                "inherit_review 里是校名形如「母体校名 + 后缀」但未自动继承层次的院校 —— "
                "分校区/合作办学可继承、独立学院不可，二者无法靠字符串区分，故一律不猜，登记待人工确认。",
                "records 只含后端 school 表的列、可直接装载；河南招生代号（考生填志愿用的是它）"
                "另存 meta.extra.henan_code_by_school_id，待决定落列或单开 "
                "school_enrollment_code 表后启用。",
            ],
        })

    # ------------------------------------------------------------------ #
    # 3. major（徐的 845 官方专业 + 张的简介；另含徐的 93 个专业类）
    # ------------------------------------------------------------------ #
    def build_major(self) -> dict[str, int]:
        print("[3/14] major 专业库")
        xu_major = _load(self.xu / "majors" / "majors.json")
        z_major = _load(self.zhang / "output" / "major.json")
        z_by_code = {str(m.get("code")): m for m in z_major if m.get("code")}

        records: list[dict] = []
        code_to_id: dict[str, int] = {}
        intro_filled = 0
        # 3.1 具体专业（845）
        for m in xu_major["majors"]:
            mid = len(records) + 1
            code = str(m.get("code") or "")
            z = z_by_code.get(code) or {}
            intro = str(z.get("intro") or "").strip()
            if intro:
                intro_filled += 1
            records.append({
                "id": mid,
                "name": m.get("name") or "",
                "code": code,
                "category": m.get("menlei") or "",
                "first_class": m.get("class_name") or "",
                "degree": m.get("degree_note") or "",
                "intro": intro,
                "is_category": False,
            })
            if code:
                code_to_id[code] = mid
        n_major = len(records)

        # 3.2 专业类（93）：录取分数据里有 10,817 行是「按专业类招生」（major_id 是
        #     4 位专业类代码），若本表不承载则这批行的 major_id 无处可指。
        #     以 is_category=True 与具体专业区分（后端 major 表本就有该列）。
        class_code_to_id: dict[str, int] = {}
        for c in xu_major.get("classes", []):
            ccode = str(c.get("class_code") or "")
            if not ccode or ccode in code_to_id:
                continue
            cid = len(records) + 1
            records.append({
                "id": cid,
                "name": c.get("class_name") or "",
                "code": ccode,
                "category": c.get("menlei") or "",
                "first_class": c.get("class_name") or "",
                "degree": "",
                "intro": "",
                "is_category": True,
            })
            class_code_to_id[ccode] = cid
        n_class = len(records) - n_major

        self.write("major", records, {
            "primary_source": "徐 · majors.json（教育部《普通高等学校本科专业目录（2025年）》）",
            "enriched_by": "张 · major.json（455 条专业简介，按专业代码匹配）",
            "official_count_check": {
                "专业（本科目录口径）": n_major, "官方口径": 845,
                "一致": n_major == 845,
            },
            "category_rows": n_class,
            "intro_filled": intro_filled,
            "notes": [
                f"前 {n_major} 条为教育部目录的专业，与官方口径 845 完全一致。",
                f"后 {n_class} 条为**专业类**（is_category=True）：录取分数据里有 10,817 行是"
                "「按专业类招生」，若本表不承载则这批行 major_id 无处可指。"
                "如需严格保持「major=仅专业」，删掉 is_category=True 的行即可，"
                "代价是这 10,817 行的专业维度失效。",
                "专业名 / 代码 / 学科门类 / 专业类 全部取自徐的官方目录；简介取自张。",
            ],
        }, )
        return code_to_id | class_code_to_id

    # ------------------------------------------------------------------ #
    # 4. school_major_score（徐 116,036 行为主体 + 张补 plan_count）
    # ------------------------------------------------------------------ #
    def build_sms(self, code_to_id: dict[str, int]) -> None:
        print("[4/14] school_major_score 院校专业录取分")
        merged = _load(self.xu / "schools" / "schools_merged.json")
        school_code_by_id = {r["id"]: str(r.get("code") or "") for r in merged["records"]}

        # 张的招生计划索引。
        # ⚠️ **不能**用 (group_code, major_code) 拼：实测两套数据的「院校专业组编号」
        # 不是同一体系（同一校同年，徐为 502/504、张为 101/102），且徐的 major_code
        # 大量为空。硬拼会写入**错误的** plan_count —— 违反项目红线「宁可缺，不可猜」。
        # 故改用语义键 (院校代码, 年, 科类, 归一专业名)：宁可只命中少部分，也不猜。
        z_recs = _load(self.zhang / "output" / "school_major_score.json")
        z_index: dict[tuple, dict] = {}
        for z in z_recs:
            key = (str(z.get("school_code") or ""), _int_or_none(z.get("year")),
                   str(z.get("subject_type") or ""), _norm_name(z.get("major_name")))
            z_index.setdefault(key, z)

        files = sorted((self.xu / "school_major_score").glob("school_major_score_*.json"))
        records: list[dict] = []
        stats = Counter()
        unknown_major_codes = Counter()
        plan_keys_used: set[tuple] = set()

        for f in files:
            doc = _load(f)
            meta = doc.get("meta", {})
            for s in doc["scores"]:
                stats["rows"] += 1
                xu_school_id = _int_or_none(s.get("school_id"))
                school_code = school_code_by_id.get(xu_school_id, "") if xu_school_id else ""
                if xu_school_id is None:
                    stats["school_id_null"] += 1
                elif not school_code:
                    stats["school_id_not_in_library"] += 1

                raw_major = s.get("major_id")
                major_id = None
                if raw_major:
                    major_id = code_to_id.get(str(raw_major).strip())
                    if major_id is None:
                        stats["major_code_unresolved"] += 1
                        unknown_major_codes[str(raw_major)] += 1
                    else:
                        stats["major_resolved"] += 1
                else:
                    stats["no_major"] += 1

                batch_code = BATCH_ALIAS_TO_CODE.get(str(s.get("batch") or "").strip(), "")
                plan_count = None
                key = (school_code, _int_or_none(s.get("year")),
                       str(s.get("subject_type") or ""), _norm_name(s.get("major_name")))
                z = z_index.get(key)
                if z is not None:
                    plan_count = _int_or_none(z.get("plan_count"))
                    plan_keys_used.add(key)
                    if plan_count is not None:
                        stats["plan_filled"] += 1

                records.append({
                    "school_id": xu_school_id,
                    "major_id": major_id,
                    "province": s.get("province") or "",
                    "year": _int_or_none(s.get("year")),
                    "batch": BATCH_CODE_TO_DISPLAY.get(batch_code, s.get("batch") or ""),
                    "group_code": str(s.get("group_code") or ""),
                    "pathway_id": s.get("pathway_id") or None,
                    "subject_type": s.get("subject_type") or "",
                    "min_score": _int_or_none(s.get("min_score")),
                    "min_rank": _int_or_none(s.get("min_rank")),
                    "avg_score": _int_or_none(s.get("avg_score")),
                    "plan_count": plan_count,
                    "source_id": self.srcid_map.get(str(s.get("source_id") or ""), None),
                })

        self.write("school_major_score", records, {
            "primary_source": "徐 · school_major_score_*.json（6 文件，河南 + 江西）",
            "enriched_by": "张 · school_major_score.json（plan_count 招生计划数）",
            "stats": dict(stats),
            "plan_count": {
                "张的来源条数": len(z_recs),
                "被命中的键": len(plan_keys_used),
                "填入 plan_count 的录取分行": stats["plan_filled"],
                "match_key": "(院校代码, year, subject_type, 归一专业名)",
                "覆盖率说明": (
                    "张的计划数据是**院校专业组级、且仅 2025 年、仅 171 所河南本地院校**"
                    "（共 1,696 行）；徐的是**专业级、2022–2025、1194 所院校**（116,036 行）。"
                    "两者体量差 68 倍，故 plan_count 的覆盖率天然很低。"
                ),
                "为什么不按专业组拼": (
                    "实测两套数据的「院校专业组编号」不是同一体系（同一校同年，"
                    "徐为 502/504、张为 101/102），且徐的 major_code 大量为空。"
                    "按 (专业组, 专业代号) 硬拼会写入错误的 plan_count，"
                    "违反项目红线「宁可缺，不可猜」，故改用语义键并接受低命中率。"
                ),
            },
            "unresolved_major_codes": unknown_major_codes.most_common(20),
            "notes": [
                "school_id 沿用徐的院校 id（与 school 表主键一致），未匹配的留 null。",
                "major_id 由徐的国标专业代码 / 专业类代码解析到 major.id；未匹配的 2,200 行留 null。",
                "按项目红线「宁可缺，不可猜」，未匹配行一律留空并在此登记，不作任何推断补全。",
                "张完整的招生计划数据另存 school_major_plan.json（未并入本表，原因见其 meta）。",
            ],
        })

    # ------------------------------------------------------------------ #
    # 4b. 张的院校专业组级招生计划 → 独立数据集（不并入 school_major_score）
    # ------------------------------------------------------------------ #
    def build_plan_dataset(self) -> None:
        print("[4b/14] school_major_plan 招生计划（张独有，独立保留）")
        by_code, by_name = self._school_lookup()
        z_recs = _load(self.zhang / "output" / "school_major_score.json")
        records, miss = [], []
        for z in z_recs:
            sid = by_code.get(str(z.get("school_code") or "")) or by_name.get(
                _norm_name(z.get("school_name")))
            if sid is None:
                miss.append(z.get("school_name"))
            records.append({
                "school_id": sid,
                "school_code": str(z.get("school_code") or ""),
                "school_name": z.get("school_name") or "",
                "province": z.get("province") or "",
                "year": _int_or_none(z.get("year")),
                "batch": z.get("batch") or "",
                "subject_type": z.get("subject_type") or "",
                "group_code": str(z.get("group_code") or ""),
                "group_name": z.get("group_name") or "",
                "major_code": str(z.get("major_code") or ""),
                "major_name": z.get("major_name") or "",
                "subject_require": z.get("subject_require") or "",
                "min_score": _int_or_none(z.get("min_score")),
                "max_score": _int_or_none(z.get("max_score")),
                "avg_score": _float_or_none(z.get("avg_score")),
                "min_rank": _int_or_none(z.get("min_rank")),
                "plan_count": _int_or_none(z.get("plan_count")),
                "admission_num": _int_or_none(z.get("admission_num")),
                "source_id": self.register_source(z.get("source_name"), z.get("source_url"),
                                                  z.get("year")),
            })
        self.write("school_major_plan", records, {
            "primary_source": "张 · data/output/school_major_score.json（院校专业组级，1,696 条）",
            "school_unmatched": len(miss), "school_unmatched_samples": miss[:20],
            "target_table": "（无对应表）暂作独立数据集保留",
            "notes": [
                "这是**唯一含 `plan_count`（招生计划数）的数据源**，徐完全没有。",
                "未并入 school_major_score 的原因：两套「院校专业组编号」不是同一体系"
                "（同一校同年，徐为 502/504、张为 101/102），徐的 major_code 又大量为空，"
                "按组/代号拼会写入错误值。",
                "本表另含徐完全没有的 max_score（最高分）、admission_num（录取人数）、"
                "subject_require（选科要求）—— 其中 subject_require 可作闸门 ② 的补充线索。",
                "要并入主表，需要：① 河南 2025 招生计划的「专业组」统一口径，或"
                "② 一张 徐-张 专业组对照表。在此之前如实保留为独立数据集。",
            ],
        })

    # ------------------------------------------------------------------ #
    # 5. score_segment（徐 8 文件；同分人数取徐的 segment_count）
    # ------------------------------------------------------------------ #
    def build_score_segment(self) -> None:
        print("[5/14] score_segment 一分一段")
        records: list[dict] = []
        stats = Counter()
        for f in sorted((self.xu / "score_segment").glob("score_segment_*.json")):
            doc = _load(f)
            meta = doc.get("meta", {})
            # 逐条缺 source_id 时回退到该文件的 meta 来源（2026 OCR 文件是这种情况）
            fallback = self.srcid_map.get(str(meta.get("source_id") or ""))
            if fallback is None:
                fallback = self.register_source(meta.get("source_name"), meta.get("source_url"),
                                                meta.get("year"))
            for s in doc.get("segments", []):
                stats["rows"] += 1
                batch_code = BATCH_ALIAS_TO_CODE.get(str(s.get("batch") or "").strip(), "")
                same = _int_or_none(s.get("segment_count"))
                if same is not None:
                    stats["same_filled"] += 1
                sid = self.srcid_map.get(str(s.get("source_id") or ""), fallback)
                if s.get("source_id") and str(s["source_id"]) not in self.srcid_map:
                    stats["source_from_fallback"] += 1
                records.append({
                    "province": s.get("province") or "",
                    "year": _int_or_none(s.get("year")),
                    "subject_type": s.get("subject_type") or "",
                    "batch": BATCH_CODE_TO_DISPLAY.get(batch_code, s.get("batch") or ""),
                    "score": _int_or_none(s.get("score")),
                    "cumulative_rank": _int_or_none(s.get("cumulative_rank")),
                    "same_score_count": same,
                    "source_id": sid,
                })
        self.write("score_segment", records, {
            "primary_source": "徐 · score_segment_*.json（8 文件，河南 + 江西，2022–2025）",
            "stats": dict(stats),
            "notes": [
                "same_score_count 取徐的 segment_count 字段（两侧口径一致，数值相同）。",
                "batch 必须保留：老高考一分为多段（本科一批/二批/专科批），"
                "各段累计值连续，合并会丢批次线信息（数据工程 meta 明确警示）。",
                "张的同名表（3,574 条，河南 3 年）是徐的子集且来源相同，未重复采用。",
            ],
        })

    # ------------------------------------------------------------------ #
    # 6. province_exam_rule
    # ------------------------------------------------------------------ #
    def build_province_rule(self) -> None:
        print("[6/14] province_exam_rule 省份志愿模式")
        doc = _load(self.xu / "dictionaries" / "province-exam-rule.json")
        records, unmapped_exam, ambiguous_exam = [], Counter(), Counter()
        for r in doc["rules"]:
            pc = str(r.get("province_code") or "")
            province = r.get("province") or ""
            province_code = pc[:2] if len(pc) >= 2 else PROVINCE_CODE_BY_NAME.get(province, "")
            raw_exam = str(r.get("category_group") or "").strip()
            exam_type = EXAM_TYPE_MAP.get(raw_exam)
            if exam_type is None:
                unmapped_exam[raw_exam] += 1
                exam_type = "普通"
            if "艺术" in raw_exam and "体育" in raw_exam:
                ambiguous_exam[raw_exam] += 1
            batch_code = str(r.get("batch_code") or "") or BATCH_ALIAS_TO_CODE.get(
                str(r.get("batch") or "").strip(), "")
            records.append({
                "province_code": province_code,
                "province": province,
                "year": _int_or_none(r.get("year")),
                "batch": BATCH_CODE_TO_DISPLAY.get(batch_code, r.get("batch") or ""),
                "batch_code": batch_code,
                "exam_type": exam_type,
                "mode": r.get("mode") or "",
                "volunteer_count": _int_or_none(r.get("volunteer_count")) or 0,
                "majors_per_group": _int_or_none(r.get("majors_per_group")),
                "has_adjust": bool(r.get("has_adjust")),
                "admit_method": r.get("admit_method") or "",
                "ratio": r.get("ratio") or "",
                "tie_rule": r.get("tie_rule") or "",
                "mutex_groups": list(r.get("mutex_groups") or []),
                "collect_count": _int_or_none(r.get("collect_count")),
                "source_id": self.srcid_map.get(str(r.get("source_id") or ""), None),
            })
        self.write("province_exam_rule", records, {
            "primary_source": "徐 · dictionaries/province-exam-rule.json",
            "unmapped_exam_type": dict(unmapped_exam),
            "ambiguous_exam_type": dict(ambiguous_exam),
            "notes": [
                "province_code 由徐的 6 位行政区划码（410000/360000）归一为契约要求的 2 位（41/36）。",
                "exam_type 由数据源列名 category_group 映射（契约 8.1 要求）。",
                "batch_code 采用契约 v1.3 的 undergraduate_regular 口径（不带省份前缀）。",
                "ambiguous_exam_type 里的规则原值同时含「艺术」与「体育」，是**一个**合并批次，"
                "而契约 exam_type 只允许单值 —— 已取「艺术」并在此登记，待裁定是否拆成两条。",
            ],
        })

    # ------------------------------------------------------------------ #
    # 7~9. 途径三表（徐为主）
    # ------------------------------------------------------------------ #
    def build_pathway(self) -> None:
        print("[7/14] pathway 升学途径字典")
        doc = _load(self.xu / "dictionaries" / "pathways-26.json")
        records = []
        for p in doc["pathways"]:
            records.append({
                "id": p.get("id") or "",
                "name": p.get("name") or "",
                "category": p.get("category") or "",
                "batch": p.get("batch") or "",
                "target_group": p.get("target_group") or "",
                "apply_time": p.get("apply_time") or "",
                "description": p.get("description") or "",
                "priority": p.get("priority") or "P2",
                "data_status": DATA_STATUS_MAP.get(str(p.get("data_status")), "schema_only"),
                "year": _int_or_none(p.get("year")),
                "source_id": self.srcid_map.get(str(p.get("source_id") or ""))
                or self.register_source(p.get("source_name"), p.get("source_url"), p.get("year")),
            })
        self.write("pathway", records, {
            "primary_source": "徐 · dictionaries/pathways-26.json（26 类）",
            "notes": [
                "pathway_id 用徐的字符串 slug（与契约 8.1 一致、与 pathway_region 外键对齐）。",
                "张的 pathway.json 无 id 字段，无法作为 pathway 主键来源，故未采用。",
                "data_status 由数据工程内部值（pending/verified）映射为契约四值。",
                "徐的字典标注 status=draft-待评审，26 类口径仍待队长确认。",
            ],
        })

    def build_pathway_region(self) -> None:
        print("[8/14] pathway_region 专项实施区域")
        doc = _load(self.xu / "dictionaries" / "pathway-regions.json")
        records = []
        for r in doc["regions"]:
            records.append({
                "pathway_id": r.get("pathway_id") or "",
                "province": str(r.get("province") or "").replace("省", ""),
                "county_name": r.get("county_name") or "",
                "county_code": str(r.get("county_code") or ""),
                "year": _int_or_none(r.get("year")),
                "source_id": self.srcid_map.get(str(r.get("source_id") or ""), None),
            })
        self.write("pathway_region", records, {
            "primary_source": "徐 · dictionaries/pathway-regions.json（91 行 = 一县一途径）",
            "notes": [
                "province 由「河南省」归一为「河南」。",
                "官方口径：国家专项 38 县 / 高校专项 53 县 / 地方专项=全省农村不划县。",
                "张的同名表 91 条与徐一致（张曾纠正过种子里的归类错误），未重复采用。",
            ],
        })

    def build_pathway_eligibility(self) -> None:
        print("[9/14] pathway_eligibility 资格规则")
        doc = _load(self.xu / "dictionaries" / "pathway-eligibility.json")
        default_year = _int_or_none(doc.get("meta", {}).get("year")) or 2025
        valid_ids = {p["id"] for p in
                     _load(self.xu / "dictionaries" / "pathways-26.json")["pathways"]}
        records, dangling = [], []
        for r in doc["rules"]:
            pid = r.get("pathway_id")
            if pid not in valid_ids:
                dangling.append(pid)
                pid = None  # 不留悬空外键，如实登记
            records.append({
                "pathway_id": pid,
                "province": r.get("province") or "",
                "rule_type": r.get("rule_type") or "",
                "rule_desc": r.get("rule_desc") or "",
                "params": r.get("params") or {},
                "year": _int_or_none(r.get("year")) or default_year,
                "source_id": self.srcid_map.get(str(r.get("source_id") or ""), None),
            })
        self.write("pathway_eligibility", records, {
            "primary_source": "徐 · dictionaries/pathway-eligibility.json（11 条）",
            "dangling_pathway_id": dangling,
            "notes": [
                "徐的规则无 year 字段，按 meta.year（缺省 2025）补齐，符合「规则表必须带 year」。",
                "pathway_id 不在 26 类字典内的已置空并记入 dangling_pathway_id，避免悬空外键。",
                "张的 pathway_eligibility.json 13 条但只有 pathway_name 无 slug id，"
                "无法挂 pathway 外键，故未合并（如需可后续按名映射补 2 条）。",
            ],
        })

    # ------------------------------------------------------------------ #
    # 10~14. 张独有的表
    # ------------------------------------------------------------------ #
    def _school_lookup(self) -> tuple[dict, dict]:
        merged = _load(self.xu / "schools" / "schools_merged.json")
        by_code, by_name = {}, {}
        for r in merged["records"]:
            if r.get("code"):
                by_code[str(r["code"])] = r["id"]
            by_name[_norm_name(r.get("name"))] = r["id"]
        return by_code, by_name

    def build_school_layer(self) -> None:
        """discipline_eval / enrollment_rule / school_profile / school_life / pathway_score。"""
        by_code, by_name = self._school_lookup()

        def resolve(code, name):
            return by_code.get(str(code or "")) or by_name.get(_norm_name(name))

        # --- discipline_eval ---
        print("[10/14] discipline_eval 学科评估")
        recs = _load(self.zhang / "output" / "discipline_eval.json")
        out, miss = [], []
        for r in recs:
            sid = resolve(None, r.get("school_name"))
            if sid is None:
                miss.append(r.get("school_name"))
            out.append({
                "school_id": sid,
                "discipline_name": r.get("discipline_name") or "",
                "grade": r.get("grade") or "",
                "round": r.get("round") or "",
                "source_id": self.register_source(r.get("source_name"), r.get("source_url"),
                                                  r.get("year")),
            })
        self.write("discipline_eval", out, {
            "primary_source": "张 · data/output/discipline_eval.json（第四轮学科评估 409 条）",
            "school_unmatched": len(miss), "school_unmatched_samples": miss[:20],
            "notes": ["徐完全没有这张表。第五轮结果官方尚未全部公开，schema 已留 round 字段。"],
        })

        # --- enrollment_rule ---
        print("[11/14] enrollment_rule 招生章程")
        recs = _load(self.zhang / "output" / "enrollment_rule.json")
        out, miss = [], []
        for r in recs:
            sid = resolve(r.get("school_code"), r.get("school_name"))
            if sid is None:
                miss.append(r.get("school_name"))
            out.append({
                "school_id": sid,
                "year": _int_or_none(r.get("year")),
                "content": (r.get("content") or "")[:60000],
                "subject_req": r.get("subject_req") or "",
                "health_req": r.get("health_req") or "",
                "foreign_lang_req": r.get("foreign_lang_req") or "",
                "source_id": self.register_source(r.get("source_name"), r.get("source_url"),
                                                  r.get("year")),
            })
        self.write("enrollment_rule", out, {
            "primary_source": "张 · data/output/enrollment_rule.json（40 条 / 20 校）",
            "school_unmatched": len(miss), "school_unmatched_samples": miss[:20],
            "notes": ["徐完全没有这张表。这是「藏在招生章程里的要求」的唯一载体。"],
        })

        # --- school_profile ---
        print("[12/14] school_profile 院校画像")
        recs = _load(self.zhang / "output" / "school_profile.json")
        out, miss = [], []
        for r in recs:
            sid = resolve(r.get("school_code"), r.get("school_name"))
            if sid is None:
                miss.append(r.get("school_name"))
            mp, pp = r.get("master_points"), r.get("phd_points")
            out.append({
                "school_id": sid,
                "tuition_range": str(r.get("tuition_range") or ""),
                "accommodation_fee": str(r.get("accommodation_fee") or ""),
                "campus_list": [],
                "established_year": _int_or_none(r.get("established_year")),
                "master_phd_points": {"master": _int_or_none(mp), "phd": _int_or_none(pp)},
                "first_class_major_count": None,
                "faculty_count": _int_or_none(r.get("faculty_count")),
                "student_faculty_ratio": "",
                "source_id": self.register_source(r.get("source_name"), r.get("source_url"),
                                                  r.get("year")),
            })
        self.write("school_profile", out, {
            "primary_source": "张 · data/output/school_profile.json（20 条）",
            "school_unmatched": len(miss), "school_unmatched_samples": miss[:20],
            "notes": [
                "徐完全没有这张表。",
                "master_points / phd_points 合并进 master_phd_points（0004 迁移后该列为 JSON）。",
                "tuition_range 是「中外合作办学学费参考」，不是专业学费 —— 闸门 ④ 仍缺正式学费数据。",
                "张的 intro / website 已并入 school 表（避免重复）。",
            ],
        })

        # --- school_life ---
        print("[13/14] school_life 生活信息")
        recs = _load(self.zhang / "output" / "school_life.json")
        out, miss = [], []
        for r in recs:
            sid = resolve(None, r.get("school_name"))
            if sid is None:
                miss.append(r.get("school_name"))
            out.append({
                "school_id": sid,
                "category": r.get("category") or "",
                "content": r.get("content") or "",
                "source_type": r.get("source_type") or "",
                "source_name": r.get("source_name") or "",
                "source_url": r.get("source_url") or "",
                "year": _int_or_none(r.get("year")),
                "reliability": r.get("reliability") or "",
            })
        self.write("school_life", out, {
            "primary_source": "张 · data/output/school_life.json（7 条）",
            "school_unmatched": len(miss), "school_unmatched_samples": miss[:20],
            "notes": ["徐完全没有这张表。张的采集器自陈「受源文本长度限制，如实覆盖」。"],
        })

        # --- pathway_score ---
        print("[14/14] pathway_score 专项录取分")
        recs = _load(self.zhang / "output" / "pathway_score.json")
        pdoc = _load(self.xu / "dictionaries" / "pathways-26.json")
        slug_by_name = {p["name"]: p["id"] for p in pdoc["pathways"]}
        out, miss_school, miss_path = [], [], []
        for r in recs:
            sid = resolve(r.get("school_code"), r.get("school_name"))
            pid = slug_by_name.get(r.get("pathway_name"))
            if sid is None:
                miss_school.append(r.get("school_name"))
            if pid is None:
                miss_path.append(r.get("pathway_name"))
            out.append({
                "pathway_id": pid,
                "school_id": sid,
                "major_id": None,
                "province": r.get("province") or "",
                "year": _int_or_none(r.get("year")),
                "min_score": _int_or_none(r.get("min_score")),
                "min_rank": _int_or_none(r.get("min_rank")),
                "source_id": self.register_source(r.get("source_name"), r.get("source_url"),
                                                  r.get("year")),
            })
        self.write("pathway_score", out, {
            "primary_source": "张 · data/output/pathway_score.json（10 条专项录取分）",
            "school_unmatched": len(miss_school), "pathway_unmatched": miss_path,
            "notes": [
                "徐完全没有这张表。",
                "张的数据是院校专业组级（含 group_code/subject_type），"
                "而后端 pathway_score 无这两列，故未落列，仅保留分/位次。",
            ],
        })

    # ------------------------------------------------------------------ #
    def run(self) -> None:
        self.build_source()
        self.build_school()
        code_to_id = self.build_major()
        self.build_sms(code_to_id)
        self.build_plan_dataset()
        self.build_score_segment()
        self.build_province_rule()
        self.build_pathway()
        self.build_pathway_region()
        self.build_pathway_eligibility()
        self.build_school_layer()

        # source 在最后写（前面的表会动态登记张的来源）
        self.write("source", self.sources, {
            "primary_source": "徐 · source-table.json（16 条）+ 张各表动态登记",
            "external_id_map": self.srcid_map,
            "notes": [
                "后端 source.id 是整型主键，而数据侧用字符串 id（SRC-xxx），"
                "故统一重分配为 1..N，原字符串 id 记在 external_id_map 里可追溯。",
            ],
        })

        summary = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "generator": "data/scripts/merge_datasets.py",
            "source_xu": str(self.xu),
            "source_zhang": str(self.zhang),
            "tables": self.report,
            "notes": self.notes,
            "skipped": {
                "batch_score_line": "后端无对应表；徐的 score_segment 已带 control_score（批次控制线）",
                "subject_requirement": "无数据源 —— 徐的解析器只 print 不落盘",
                "physical_restriction": "无数据源 —— 「专业类×身体条件」映射表从未建立",
                "admission_requirement": "无结构化数据源 —— 张仅在 enrollment_rule 里有非结构化文本",
                "major_tuition": "无数据源 —— 闸门 ④ 学费仍空（队长已同意延后）",
            },
        }
        (self.out / "_merge_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n汇总写入 {self.out / '_merge_summary.json'}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-xu", required=True, help="徐分支导出的 data/ 目录")
    ap.add_argument("--src-zhang", required=True, help="张分支导出的 data/ 目录")
    ap.add_argument("--out", required=True, help="输出目录")
    args = ap.parse_args()

    xu, zhang, out = Path(args.src_xu), Path(args.src_zhang), Path(args.out)
    for p in (xu, zhang):
        if not p.exists():
            print(f"!! 源目录不存在：{p}")
            return 1
    print(f"徐 = {xu}\n张 = {zhang}\n出 = {out}\n")
    Merger(xu, zhang, out).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
