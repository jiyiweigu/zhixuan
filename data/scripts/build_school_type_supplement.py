#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
软科数据定性 + `school.type` 候选补充（D2）

═══ 一、先纠正 D2 的原始假设 ═══
原清单把 D2 写成「软科 JSON → discipline_eval」。**这是错的**，实测依据：

  · `DisciplineEval` 模型要的是「学科名称 + 评估等级(A+/B) + 轮次」——
    即**教育部学位与研究生教育发展中心**的**学科评估**结果；
  · 而 `data/schools/shanghairanking_2024.json` 是软科**院校综合排名**
    （字段：ranking / rankOverall / score / category / tags），
    粒度是**院校**、不是**学科**，模板完全对不上。

结论：**学科评估不能由软科数据充当**。官方源 `cdgdc.edu.cn` 实测 **HTTP 412**
（瑞数 WAF，与本项目已知的 haeea.cn / heao.com.cn 同类）→ 只能人工下载 + 脚本解析。
本脚本不臆造学科评估数据。

═══ 二、软科数据真正能补的字段：`school.type` ═══
实测 `school.type` 现为空 **1367/1367 = 100%**；而软科每条记录自带
`univCategory`（综合 / 理工 / 师范 / 农业 / 林业 / 医药 / 财经 / 政法 / 语言 / 民族 / 体育），
正是「院校类型」的现成来源。

⚠️ 原采集脚本只抓了 `bcur_type=11`（主榜，594 条，仅 5 个类别）。
本脚本实测发现同接口还有多个**单科榜**，合并后：
  type=11 主榜 594 ｜ 14 综合 8 ｜ 15 综合榜 180 ｜ 16 财经 36 ｜ 17 语言 9
  21 医药 84 ｜ 22 财经 54 ｜ 23 语言/民族 16 ｜ 24 民族 13 ｜ 25 政法 34 ｜ 26 体育 14
  ⇒ 去重后 **1042 所院校 / 11 个类别 / 类型冲突 0**
  （type=30 的 48 条无 `univCategory`，未参与）

═══ 三、口径与边界 ═══
· 软科是**第三方机构排名，非官方**。本产物仅供 `school.type` 补空，
  **不得**替代高校官网/教育部的官方分类；界面若展示须标注来源。
· 校名匹配：先**全名精确**，再**核心名**（去括号）匹配。括号内容含
  校区 / 分校 / 中外合作办学 / 软件类 / 联合办学 等，均为**同一所高校的不同招生单位**，
  类型相同，故一并赋值并单独标注 `matched_by=core` 供 ② 复核。

用法
  python data/scripts/build_school_type_supplement.py             # 联网抓取并生成
  python data/scripts/build_school_type_supplement.py --offline   # 只用缓存
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "schools"
CACHE_DIR = OUT_DIR / ".cache_srk"          # 与 fetch_shanghairanking.py 同一缓存约定
CACHE = CACHE_DIR / "bcur_all_boards_2024.json"
OUT = OUT_DIR / "school_type_supplement.json"
SCHOOLS = OUT_DIR / "schools_merged.json"

API = "https://www.shanghairanking.cn/api/pub/v1/bcur"
YEAR = 2024
BOARDS = [11, 14, 15, 16, 17, 21, 22, 23, 24, 25, 26]   # 实测有 univCategory 的榜单

SOURCE = {
    "source_id": "SRC-SHANGHAIRANKING",
    "source_name": "上海软科教育信息咨询有限公司（软科中国大学排名）",
    "source_url": "https://www.shanghairanking.cn/rankings/bcur/2024",
    "year": 2024,
    "source_type": "其他",
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.shanghairanking.cn/rankings/bcur/2024",
}

RE_PAREN_ALL = re.compile(r"[（(][^）)]*[）)]")
RE_FORMER = re.compile(r"[（(]\s*原\s*([^）)]+?)\s*[）)]")


def core_name(n: str) -> str:
    """去掉**所有**括号内容（校区 / 办学性质 / 原名 等）"""
    return RE_PAREN_ALL.sub("", str(n or "")).strip()


def fetch_boards() -> tuple[dict, dict]:
    """抓取全部榜单，返回 ({校名: {category, ...}}, 每榜统计)"""
    by_name: dict[str, dict] = {}
    board_stat: dict[int, dict] = {}
    for t in BOARDS:
        url = f"{API}?bcur_type={t}&year={YEAR}"
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            board_stat[t] = {"error": str(exc)}
            print(f"  type={t:>3}  ✗ {exc}")
            continue
        lst = (payload.get("data") or {}).get("rankings") or []
        cats = collections.Counter()
        for x in lst:
            nm = x.get("univNameCn")
            cat = x.get("univCategory") or x.get("category")
            if not nm or not cat:
                continue
            cats[cat] += 1
            rec = by_name.setdefault(nm, {})
            rec.setdefault("categories", set()).add(cat)
            rec.setdefault("boards", []).append(t)
            # 记录最好名次（rankOverall 为字符串，可能是 '54' 或 '54-55'）
            ro = str(x.get("rankOverall") or "").split("-")[0]
            if ro.isdigit():
                prev = rec.get("rank_overall")
                rec["rank_overall"] = min(prev, int(ro)) if prev else int(ro)
            rec.setdefault("tags", set()).update(x.get("univTags") or [])
            rec["province"] = rec.get("province") or x.get("province")
        board_stat[t] = {"n": len(lst), "categories": dict(cats)}
        print(f"  type={t:>3}  n={len(lst):>4}  {dict(cats)}")
        time.sleep(0.3)
    return by_name, board_stat


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="只用缓存，不联网")
    args = ap.parse_args()

    print("=" * 72)
    print("D2 软科榜单合并 → school.type 候选补充")
    print("=" * 72)

    board_stat: dict = {}
    if CACHE.exists() and args.offline:
        raw = json.loads(CACHE.read_text(encoding="utf-8"))
        by_name = {k: {**v, "categories": set(v["categories"]), "tags": set(v["tags"])}
                   for k, v in raw["schools"].items()}
        board_stat = raw["meta"].get("boards", {})
        print(f"（离线）读缓存 {CACHE.name}：{len(by_name)} 所")
    else:
        print("抓取软科各榜单：")
        by_name, board_stat = fetch_boards()

    # 类型冲突检查
    conflicts = {k: sorted(v["categories"]) for k, v in by_name.items()
                 if len(v["categories"]) > 1}
    cat_counter = collections.Counter()
    for v in by_name.values():
        cat_counter.update(v["categories"])

    print()
    print(f"合并后唯一院校 : {len(by_name)}")
    print(f"类别分布       : {dict(cat_counter.most_common())}")
    print(f"类型冲突院校   : {len(conflicts)}")

    # ── 与院校库匹配 ──────────────────────────────────────────
    lib = json.loads(SCHOOLS.read_text(encoding="utf-8"))
    lib_recs = lib["records"] if isinstance(lib, dict) else lib
    lib_names = [r["name"] for r in lib_recs]
    lib_by_name = {r["name"]: r for r in lib_recs}
    by_core: dict[str, list[str]] = collections.defaultdict(list)
    by_former: dict[str, list[str]] = collections.defaultdict(list)
    for n in lib_names:
        by_core[core_name(n)].append(n)
        for fn in RE_FORMER.findall(n):
            by_former[fn.strip()].append(n)

    assigned: list[dict] = []
    for srk_name, info in sorted(by_name.items()):
        cats = sorted(info["categories"])
        if len(cats) != 1:
            continue                      # 有冲突的不用，交人工
        cat = cats[0]
        targets: list[tuple[str, str]] = []
        if srk_name in lib_by_name:
            targets.append((srk_name, "exact"))
        # ★ 核心名要用**软科名的核心名**去查（软科用全角括号，如「中国石油大学（北京）」，
        #   而院校库用半角「中国石油大学(北京)」；两侧都先归一再比）
        for cname in by_core.get(core_name(srk_name), []):
            if cname != srk_name:
                targets.append((cname, "core"))
        # ★ 改名院校：院校库名为 `新名(原旧名)`，而软科仍用**旧名** →
        #   用括号内原名反查（如「苏州工学院(原常熟理工学院)」← 「常熟理工学院」）
        for fname in by_former.get(srk_name, []):
            if fname != srk_name:
                targets.append((fname, "former_name"))
        if not targets:
            continue
        for lib_name, how in targets:
            src = lib_by_name[lib_name]
            assigned.append({
                # 前 4 个字段取自院校库，使本文件自身也能通过 school 表校验
                "id": src.get("id"),
                "name": lib_name,
                "code": src.get("code") or None,
                "province": src.get("province"),
                "school_name": lib_name,          # ② 按此合并 school.type
                "type": cat,
                "matched_by": how,                # exact / core
                "srk_name": srk_name,             # 软科原始校名
                "srk_rank_overall": info.get("rank_overall"),
                "srk_tags": sorted(info["tags"]),
                "srk_boards": sorted(info["boards"]),
            })

    covered = {a["school_name"] for a in assigned}
    print()
    print(f"院校库匹配成功 : {len(covered)}/{len(lib_names)}"
          f" = {len(covered)/len(lib_names)*100:.1f}%   （记录数 {len(assigned)}，含校区/办学单位）")
    print(f"  其中 core 匹配: {sum(1 for a in assigned if a['matched_by'] == 'core')}")
    print(f"  未匹配校数    : {len(lib_names) - len(covered)}")

    if args.offline and not CACHE.exists():
        print("✗ --offline 但无缓存", file=sys.stderr)
        return 2

    # ── 写缓存（与 fetch_shanghairanking.py 一致的隐藏缓存目录）──
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({
        "meta": {
            "generated_at": str(date.today()),
            "api": API, "year": YEAR, "boards": board_stat,
            "note": "软科多榜单合并原始缓存（含 univCategory）。第三方排名，非官方数据。",
            **{k: v for k, v in SOURCE.items() if k != "source_type"},
        },
        "schools": {k: {
            "categories": sorted(v["categories"]),
            "boards": sorted(v["boards"]),
            "rank_overall": v.get("rank_overall"),
            "province": v.get("province"),
            "tags": sorted(v["tags"]),
        } for k, v in sorted(by_name.items())},
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 写补充表 ──────────────────────────────────────────────
    payload = {
        "meta": {
            "generated_at": str(date.today()),
            "owner": "徐（③ 数据工程）",
            "target_table": "school",
            "target_field": "type",
            "purpose": (
                "school.type 现 0 填充（1367/1367 为空）。本表给出软科口径下的院校类型候选，"
                "供 ② 在灌数时按「仅填空值」的原则合并。"
            ),
            "not_official": True,
            "proxy_rule": (
                "★ 本产物是第三方机构排名分类，**非官方**。仅用于补 school.type 空值；"
                "若界面展示须标注来源，不得表述为官方分类。官方口径需逐校官网/教育部材料采集（D5）。"
            ),
            "match_rule": (
                "全名精确 → 核心名（去全部括号）→ 括号内「原名」（`新名(原旧名)` 型改名院校）；"
                "括号含校区/分校/中外合作办学/软件类/联合办学等，均为同一高校的不同招生单位，"
                "类型一致，故一并赋值，并用 matched_by 区分 exact / core / former_name 供复核。"
            ),
            "boards": board_stat,
            "coverage": {
                "lib_total": len(lib_names),
                "matched": len(covered),
                "matched_rate": round(len(covered) / len(lib_names), 4),
                "records": len(assigned),
                "matched_by_core": sum(1 for a in assigned if a["matched_by"] == "core"),
            },
            "category_distribution": dict(cat_counter.most_common()),
            "conflicts": conflicts,
            **SOURCE,
        },
        "records": sorted(assigned, key=lambda a: a["school_name"]),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print(f"✅ 已写出 {CACHE.relative_to(ROOT)}（缓存 {len(by_name)} 所）")
    print(f"✅ 已写出 {OUT.relative_to(ROOT)}（{len(assigned)} 条，覆盖 {len(covered)} 所）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
