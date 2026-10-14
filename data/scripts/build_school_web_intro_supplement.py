#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
D5：`school.website` / `school.intro` 候选补充（软科院校详情接口）

═══ 一、为什么用软科详情接口 ═══
`school.website` / `school.intro` 现均 **0 填充（1367/1367 为空）**，两处已有源都补不了：

  · 源 A（河南省阳光高考 招生计划系统 SRC-HENAN-ZSJH）：schema 有 website/intro 列，
    但**实测全表 0 条非空**（见 schools_raw.json 2495 行），源本身不提供；
  · 源 B（教育部全国高校名单 SRC-MOE-SCHOOL-LIST）：字段仅
    seq/name/code10/national_code/department/location/province/city/level，**无官网**；
  · 教育部阳光高考 `gaokao.chsi.com.cn` 实测 **HTTP 412**（瑞数 WAF，本项目已知）。

软科榜单接口 `bcur` 只给排名，但**院校详情接口**：

    GET https://www.shanghairanking.cn/api/pub/v1/inst/{univUp}

实测返回（无 WAF、HTTP 200）：

    nameCn / nameEn / url（★官网） / intro（★简介） / cityName / provinceShort /
    adminType（主管部门） / categoryName（类型） / level（双一流等） / isVocational

一条线同时给 `website` 与 `intro` 的候选。

═══ 二、可信度分级（★ 关键设计）═══
软科是**第三方机构，非官方**，其 `url` 只能算**候选**。故本脚本对每条候选官网
**实测校验**：拉取该 URL，判定「HTTP 200 + 页面出现该校名（核心名/原名）」→ `verified=true`。

  · `website_verified = true`  → 值即**该校官网本身**，可视为官方级（provenance 记 SRC-SCHOOL-OFFICIAL），
    灌数时写入 `school.website`；
  · `website_verified = false` → 仅候选，**不得**直接写库，交人工/二次采集（宁可缺不可猜）。

`intro` 为软科自撰简介（约 130–230 字），**非官方**，一律标 `official=false`；
须在《知识产权说明》列明来源，界面展示须标注非官方。

═══ 三、口径与边界 ═══
· 校名匹配：全名精确 → 核心名（去全部括号）→ 括号内「原名」（`新名(原旧名)` 型改名院校）。
  括号内容含校区/分校/中外合作办学/软件类/联合办学等，均为同一高校的不同招生单位，
  类型与官网一致，故一并赋值，用 `matched_by` 区分 exact / core / former_name。
· 已有值不覆盖（本脚本只产出候选，合并时「仅填空值」）。
· 不臆造：软科无覆盖者（军校 / 独立学院 / 职业本科 / 港澳校）**留空**。

用法
  python data/scripts/build_school_web_intro_supplement.py             # 联网全量抓取 + 校验
  python data/scripts/build_school_web_intro_supplement.py --limit 30  # 试点前 30 条
  python data/scripts/build_school_web_intro_supplement.py --no-verify # 只取候选，不校验官网
  python data/scripts/build_school_web_intro_supplement.py --offline   # 只用缓存
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "schools"
CACHE_DIR = OUT_DIR / ".cache_srk"
INST_CACHE = CACHE_DIR / "inst"                     # 每校详情条目缓存
SLUG_CACHE = CACHE_DIR / "bcur_slug_map_2024.json"  # 校名 → univUp
OUT = OUT_DIR / "school_web_intro_supplement.json"
SCHOOLS = OUT_DIR / "schools_merged.json"

API = "https://www.shanghairanking.cn/api/pub/v1"
INST_PAGE = "https://www.shanghairanking.cn/institution"
YEAR = 2024
BOARDS = [11, 14, 15, 16, 17, 21, 22, 23, 24, 25, 26]

SOURCE = {
    "source_id": "SRC-SHANGHAIRANKING",
    "source_name": "上海软科教育信息咨询有限公司（软科中国大学排名）",
    "source_url": "https://www.shanghairanking.cn/rankings/bcur/2024",
    "source_type": "其他",
    "year": YEAR,
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
HDR_SRK = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.shanghairanking.cn/rankings/bcur/2024",
}
HDR_SITE = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

RE_PAREN_ALL = re.compile(r"[（(][^）)]*[）)]")
RE_FORMER = re.compile(r"[（(]\s*原\s*([^）)]+?)\s*[）)]")
RE_TAGS = re.compile(r"(?is)<(script|style)[^>]*>.*?</\1>")
RE_ALL_TAGS = re.compile(r"(?s)<[^>]+>")


def core_name(n: str) -> str:
    """去掉**所有**括号内容（校区 / 办学性质 / 原名 等）"""
    return RE_PAREN_ALL.sub("", str(n or "")).strip()


def former_names(n: str) -> list[str]:
    """抽取 `新名(原旧名)` 括号内的**原名**（改名院校用）"""
    return [m.group(1).strip() for m in RE_FORMER.finditer(str(n or ""))]


def http_get(url: str, headers: dict, timeout: int = 12, retries: int = 1) -> tuple[int, bytes, str]:
    """返回 (status, body_bytes, final_url)；失败抛异常"""
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as resp:
                return resp.status, resp.read(), resp.geturl()
        except urllib.error.HTTPError as exc:
            return exc.code, b"", url
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.5)
    raise last  # type: ignore[misc]


def decode(raw: bytes, ctype: str = "") -> str:
    m = re.search(r"charset=([\w-]+)", ctype or "", re.I)
    for enc in ([m.group(1)] if m else []) + ["utf-8", "gb18030", "gbk"]:
        try:
            return raw.decode(enc)
        except Exception:  # noqa: BLE001
            continue
    return raw.decode("utf-8", "ignore")


def strip_html(h: str) -> str:
    h = RE_TAGS.sub(" ", h)
    h = RE_ALL_TAGS.sub(" ", h)
    h = h.replace("&nbsp;", " ").replace("&#160;", " ")
    return re.sub(r"\s+", " ", h).strip()


# ── 榜单：校名 → univUp slug ────────────────────────────────────────────
def fetch_slugs(offline: bool) -> dict[str, dict]:
    if SLUG_CACHE.exists() and offline:
        data = json.loads(SLUG_CACHE.read_text(encoding="utf-8"))
        print(f"  （离线）读 slug 缓存：{len(data['schools'])} 所")
        return data["schools"]
    out: dict[str, dict] = {}
    print("抓取软科榜单以取得院校 slug（univUp）：")
    for t in BOARDS:
        url = f"{API}/bcur?bcur_type={t}&year={YEAR}"
        try:
            status, raw, _ = http_get(url, HDR_SRK, timeout=30)
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"  type={t:>3}  ✗ {exc}")
            continue
        lst = (payload.get("data") or {}).get("rankings") or []
        for x in lst:
            nm, slug = x.get("univNameCn"), x.get("univUp")
            if not nm or not slug:
                continue
            rec = out.setdefault(nm, {"slug": slug, "boards": [], "category": None,
                                      "province": x.get("province")})
            rec["boards"].append(t)
            rec["category"] = rec["category"] or x.get("univCategory")
        print(f"  type={t:>3}  n={len(lst):>4}  累计院校 {len(out)}")
        time.sleep(0.3)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SLUG_CACHE.write_text(json.dumps({
        "meta": {"generated_at": str(date.today()), "api": f"{API}/bcur", "year": YEAR,
                 "note": "软科榜单→院校 slug 映射（含 univUp）。第三方排名，非官方。"},
        "schools": {k: {**v, "boards": sorted(set(v["boards"]))} for k, v in sorted(out.items())},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


# ── 院校详情 ────────────────────────────────────────────────────────────
def fetch_inst(slug: str, offline: bool, use_cache: bool = True) -> dict | None:
    INST_CACHE.mkdir(parents=True, exist_ok=True)
    cf = INST_CACHE / f"{slug}.json"
    if cf.exists() and use_cache:
        try:
            return json.loads(cf.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    if offline:
        return None
    try:
        status, raw, _ = http_get(f"{API}/inst/{urllib.parse.quote(slug)}", HDR_SRK, timeout=20)
        if status != 200:
            return None
        payload = json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    data = payload.get("data") or {}
    slim = {
        "nameCn": data.get("nameCn"), "nameEn": data.get("nameEn"),
        "url": data.get("url"), "intro": data.get("intro"),
        "cityName": data.get("cityName"), "provinceShort": data.get("provinceShort"),
        "adminType": data.get("adminType"), "categoryName": data.get("categoryName"),
        "level": data.get("level"), "isVocational": data.get("isVocational"),
        "univCode": data.get("univCode"), "up": data.get("up"),
    }
    try:
        cf.write_text(json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return slim


def normalize_url(u: str) -> str:
    """补全 scheme（软科部分记录缺 http:// 前缀）"""
    u = (u or "").strip()
    if not u:
        return ""
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    return u


def verify_site(url: str, names: list[str], timeout: int = 8) -> dict:
    """实测校验官网：HTTP 200 + 页面出现校名（核心名/原名任一命中）

    ★ 候选顺序：优先 https（软科多数记录写的是 http，但 80 端口常被拦截/站点已启 https）。
    """
    res = {"verified": False, "http_status": None, "final_url": url, "name_hit": False,
           "note": ""}
    base = normalize_url(url)
    if not base:
        res["note"] = "候选 URL 为空"
        return res
    if base.startswith("https://"):
        cands = [base, base.replace("https://", "http://", 1)]
    else:
        cands = [base.replace("http://", "https://", 1), base]
    seen: set[str] = set()
    for cand in [c for c in cands if not (c in seen or seen.add(c))]:
        try:
            status, raw, final = http_get(cand, HDR_SITE, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            res["note"] = f"不可达：{type(exc).__name__}"
            continue
        res["http_status"], res["final_url"] = status, final
        if status != 200 or not raw:
            res["note"] = f"HTTP {status}"
            continue
        text = strip_html(decode(raw, ""))
        hit = next((n for n in names if n and n in text), None)
        res["name_hit"] = bool(hit)
        res["verified"] = bool(hit)
        res["note"] = f"命中「{hit}」" if hit else "页面未出现校名"
        return res
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="只用缓存")
    ap.add_argument("--no-verify", action="store_true", help="不实测校验官网")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 所（试点）")
    ap.add_argument("--workers", type=int, default=12, help="并发线程数")
    ap.add_argument("--verify-timeout", type=int, default=8, help="官网校验单请求超时秒")
    ap.add_argument("--refresh", action="store_true", help="忽略详情缓存，强制重取")
    args = ap.parse_args()

    print("=" * 74)
    print("D5  school.website / school.intro 候选补充（软科院校详情接口）")
    print("=" * 74)

    slugs = fetch_slugs(args.offline)
    lib = json.loads(SCHOOLS.read_text(encoding="utf-8"))
    lib_recs = lib["records"] if isinstance(lib, dict) else lib
    lib_by_name = {r["name"]: r for r in lib_recs}
    by_core: dict[str, list[str]] = collections.defaultdict(list)
    by_former: dict[str, list[str]] = collections.defaultdict(list)
    names_for: dict[str, list[str]] = {}
    for r in lib_recs:
        by_core[core_name(r["name"])].append(r["name"])
        for fn in former_names(r["name"]):
            by_former[fn].append(r["name"])
        names_for[r["name"]] = [core_name(r["name"])] + former_names(r["name"])

    items = sorted(slugs.items())
    if args.limit:
        items = items[: args.limit]
    print()
    print(f"处理院校：{len(items)} 所（详情接口，并发 {args.workers}）")

    # ── Phase B：并发抓取院校详情 ─────────────────────────────────────
    details: dict[str, dict | None] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_inst, info["slug"], args.offline, not args.refresh): nm
                for nm, info in items}
        for done, fut in enumerate(as_completed(futs), 1):
            nm = futs[fut]
            try:
                details[nm] = fut.result()
            except Exception:  # noqa: BLE001
                details[nm] = None
            if done % 100 == 0 or done == len(items):
                ok = sum(1 for v in details.values() if v)
                print(f"  ...详情 {done}/{len(items)}  成功 {ok}")

    # ── 匹配 + 组装 ───────────────────────────────────────────────────
    records: list[dict] = []
    notfound: list[str] = []
    for srk_name, info in items:
        detail = details.get(srk_name)
        if not detail:
            notfound.append(srk_name)
            continue
        srk_cn = detail.get("nameCn") or srk_name
        targets: list[tuple[str, str]] = []
        if srk_cn in lib_by_name:
            targets.append((srk_cn, "exact"))
        for cname in by_core.get(core_name(srk_cn), []):
            if cname != srk_cn:
                targets.append((cname, "core"))
        for fname in by_former.get(srk_cn, []):
            targets.append((fname, "former_name"))
        if not targets:
            continue
        for lib_name, how in targets:
            src = lib_by_name[lib_name]
            url = normalize_url(detail.get("url") or "")
            records.append({
                "id": src.get("id"),
                "name": lib_name,
                "code": src.get("code") or None,
                "province": src.get("province"),
                "school_name": lib_name,
                "website": url or None,
                "website_verified": False,
                "website_http_status": None,
                "website_final_url": url or None,
                "website_name_hit": False,
                "website_note": "未校验" if url else "软科未提供官网",
                "intro": (detail.get("intro") or "").strip() or None,
                "matched_by": how,
                "srk_name": srk_cn,
                "srk_slug": info["slug"],
                "srk_url": f"{INST_PAGE}/{info['slug']}",
                "srk_admin_type": detail.get("adminType"),
                "srk_category": detail.get("categoryName"),
                "srk_level": detail.get("level"),
                "srk_city": detail.get("cityName"),
                "srk_is_vocational": detail.get("isVocational"),
            })

    # ── Phase C：并发实测校验官网 ─────────────────────────────────────
    if not args.no_verify:
        todo = [r for r in records if r["website"]]
        print()
        print(f"实测校验官网：{len(todo)} 条（并发 {args.workers}，超时 {args.verify_timeout}s）")
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(verify_site, r["website"], names_for.get(r["school_name"], []),
                              args.verify_timeout): r for r in todo}
            for done, fut in enumerate(as_completed(futs), 1):
                r = futs[fut]
                try:
                    ver = fut.result()
                except Exception:  # noqa: BLE001
                    ver = {"verified": False, "http_status": None, "final_url": r["website"],
                           "name_hit": False, "note": "校验异常"}
                r["website_verified"] = ver["verified"]
                r["website_http_status"] = ver["http_status"]
                r["website_final_url"] = ver["final_url"] or r["website"]
                r["website_name_hit"] = ver["name_hit"]
                r["website_note"] = ver["note"]
                if done % 100 == 0 or done == len(todo):
                    v = sum(1 for x in todo if x["website_verified"])
                    print(f"  ...校验 {done}/{len(todo)}  通过 {v}")

    covered = {r["school_name"] for r in records}
    with_site = {r["school_name"] for r in records if r["website"]}
    verified = {r["school_name"] for r in records if r["website_verified"]}
    with_intro = {r["school_name"] for r in records if r["intro"]}

    print()
    print(f"详情命中院校   : {len(covered)}/{len(lib_recs)}"
          f" = {len(covered)/len(lib_recs)*100:.1f}%   （记录 {len(records)}，含校区/办学单位）")
    print(f"  有官网候选   : {len(with_site)}")
    print(f"  官网实测校验通过: {len(verified)}"
          + ("" if args.no_verify else f"  （通过率 {len(verified)/max(len(with_site),1)*100:.1f}%）"))
    print(f"  有简介       : {len(with_intro)}")
    print(f"  详情接口未命中: {len(notfound)}")

    payload = {
        "meta": {
            "generated_at": str(date.today()),
            "owner": "徐（③ 数据工程）",
            "target_table": "school",
            "target_fields": ["website", "intro"],
            "purpose": (
                "school.website / school.intro 现均 0 填充（1367/1367）。本表以软科院校详情接口"
                "取得官网候选与简介候选，供 ② 在灌数时按「仅填空值」原则合并。"
            ),
            "official": False,
            "proxy_rule": (
                "★ 软科为**第三方机构，非官方**。`intro` 系软科自撰，一律视为**非官方**，"
                "界面展示须标注来源，并须在《知识产权说明》列明；"
                "`website` 已对每条候选做**实测校验**（HTTP 200 + 页面出现校名）→ "
                "`website_verified=true` 者可视为该校**官网本身**（官方级），灌数时方可写入 "
                "`school.website`；`false` 者仅候选，**不得**直接入库（宁可缺不可猜）。"
            ),
            "match_rule": (
                "全名精确 → 核心名（去全部括号）→ 括号内「原名」（`新名(原旧名)` 型改名院校）；"
                "matched_by ∈ exact / core / former_name。"
            ),
            "not_covered_note": (
                "软科 2024 榜单未收录者（军队院校 22 / 独立学院·民办 / 职业本科 / 港澳院校等）"
                "无官网与简介，**留空**，须走各校官网专项采集（D4/D5 后续）。"
            ),
            "coverage": {
                "lib_total": len(lib_recs),
                "matched": len(covered),
                "matched_rate": round(len(covered) / len(lib_recs), 4),
                "records": len(records),
                "with_website": len(with_site),
                "website_verified": len(verified),
                "with_intro": len(with_intro),
                "search_miss": len(notfound),
                "verified_flag": not args.no_verify,
            },
            "fields_layout": "id, name, code, province, school_name, website, intro, ...",
            **SOURCE,
        },
        "records": sorted(records, key=lambda a: a["school_name"]),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"✅ 已写出 {OUT.relative_to(ROOT)}（{len(records)} 条，覆盖 {len(covered)} 所）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
