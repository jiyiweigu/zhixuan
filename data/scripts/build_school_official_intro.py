#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
D5：`school.intro` 的**官方**来源采集（逐校官网「学校简介 / 学校概况」页）

═══ 定位 ═══
`build_school_web_intro_supplement.py` 用软科院校详情接口拿 `intro`，但实测**仅约 1/3**
院校有简介（`intro` 为 null 者 718/1085）——软科源本身缺失，非脚本问题。

本脚本补这一块：对**已实测校验通过的官网**（见 web 补丁 `website_verified=true`），
抓取官网首页 → 定位「学校简介 / 学校概况 / 学校介绍」入口 → 抓正文 →
抽取主体段落，产出 **官方级** `intro`（来源＝该校官网本身）。

  · 官方来源 → 可写入 `school.intro`（前端展示无需折叠）；
  · 抽取失败（无简介入口 / JS 渲染 / 正文过短）→ **留空**，绝不臆造（宁可缺不可猜）。

═══ 抽取口径 ═══
· 入口识别：首页 <a> 文本命中 `简介|概况|介绍`（含「学校简介 / 学校概况 / 学校介绍 / 河大概况」等）；
· 正文抽取：剔除 script/style/nav/header/footer 后，取 `<p>` 段落中含中文 ≥ 30 字的连续段，
  取前若干段拼接到 `MAX_CHARS`；若 <p> 抽取不达标，回退为整页文本最长连续块；
· 噪声过滤：剔除含「版权所有 / 备案号 / 技术支持 / 联系我们 / 招生热线」等页脚特征的段落。

用法
  python data/scripts/build_school_official_intro.py --limit 20        # 试点
  python data/scripts/build_school_official_intro.py                   # 全量
  python data/scripts/build_school_official_intro.py --all             # 含已有软科简介者一并重采
  python data/scripts/build_school_official_intro.py --offline         # 只用页面缓存
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "schools"
CACHE_DIR = OUT_DIR / ".cache_site"          # 页面缓存（首页 + 简介页）
OUT = OUT_DIR / "school_official_intro_supplement.json"
WEB_SUPP = OUT_DIR / "school_web_intro_supplement.json"
SCHOOLS = OUT_DIR / "schools_merged.json"

MAX_CHARS = 420
MIN_CJK = 30

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
HDR = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

_lock = threading.Lock()

RE_SCRIPT = re.compile(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>")
RE_HEADER_FOOTER = re.compile(r"(?is)<(nav|header|footer)[^>]*>.*?</\1>")
RE_P = re.compile(r"(?is)<p[^>]*>(.*?)</p>")
RE_A = re.compile(r"(?is)<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>")
RE_ALL_TAGS = re.compile(r"(?s)<[^>]+>")
RE_CJK = re.compile(r"[\u4e00-\u9fff]")
RE_INTRO_TEXT = re.compile(r"(简介|概况|介绍|概览)")
NOISE = ("版权所有", "备案", "技术支持", "联系我们", "招生热线", "友情链接", "关注我们",
         "版权所", "ICP", "公安备", "网站地图", "书记信箱", "校长信箱",
         "浏览器", "请升级您", "无法正常显示")
# 导航 / 栏目串入特征（出现 ≥3 个即判为菜单段，剔除）
NAV_TOKENS = ("部门", "机构", "学院", "招生", "就业", "图书馆", "邮箱", "English",
              "党委", "办公室", "服务平台", "信息公开", "校友", "访客", "教职工",
              "科学研究", "人才培养", "合作交流", "学科建设", "师资队伍", "校园文化")
RE_CJK_SPACE = re.compile(r"(?<=[\u4e00-\u9fff])[ \t\u3000]+(?=[\u4e00-\u9fff])")


def normalize_url(u: str, base: str = "") -> str:
    u = (u or "").strip()
    if not u or u.startswith(("#", "javascript:", "mailto:")):
        return ""
    if u.startswith("//"):
        return "https:" + u
    if re.match(r"^https?://", u, re.I):
        return u
    if not base:
        return ""
    m = re.match(r"(https?://[^/]+)", base)
    if u.startswith("/"):
        return (m.group(1) if m else "") + u
    return base.rstrip("/") + "/" + u


def http_get(url: str, timeout: int = 10, retries: int = 1) -> tuple[int, bytes, str]:
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as resp:
                return resp.status, resp.read(), resp.geturl()
        except urllib.error.HTTPError as exc:
            return exc.code, b"", url
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.3)
    raise last  # type: ignore[misc]


def decode(raw: bytes) -> str:
    head = raw[:2000].decode("latin-1", "ignore")
    m = re.search(r"charset=[\"']?([\w-]+)", head, re.I)
    for enc in ([m.group(1)] if m else []) + ["utf-8", "gb18030", "gbk"]:
        try:
            return raw.decode(enc)
        except Exception:  # noqa: BLE001
            continue
    return raw.decode("utf-8", "ignore")


def clean_text(h: str) -> str:
    h = h.replace("&nbsp;", " ").replace("&#160;", " ").replace("&amp;", "&")
    h = RE_ALL_TAGS.sub(" ", h)
    h = re.sub(r"\s+", " ", h).strip()
    # 中文之间的多余空格（多见于带标签的排版）→ 去掉
    return RE_CJK_SPACE.sub("", h)


def cjk_len(s: str) -> int:
    return len(RE_CJK.findall(s))


def url_candidates(url: str) -> list[str]:
    """★ 优先 https（软科给的 http 地址在本机/沙箱下 80 端口常被拦截，且多数高校已启 https）"""
    u = (url or "").strip()
    if not u or not re.match(r"^https?://", u, re.I):
        return [u] if u else []
    if u.startswith("https://"):
        return [u, u.replace("https://", "http://", 1)]
    return [u.replace("http://", "https://", 1), u]


def fetch_page(url: str, offline: bool, tag: str) -> tuple[str | None, str]:
    """返回 (html, 实际可用 URL)"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cands = url_candidates(url)
    for cand in cands:
        cf = CACHE_DIR / (re.sub(r"[^\w.-]", "_", cand)[:120] + f".{tag}.html")
        if cf.exists():
            try:
                return cf.read_text(encoding="utf-8"), cand
            except Exception:  # noqa: BLE001
                pass
    if offline:
        return None, url
    for cand in cands:
        try:
            status, raw, final = http_get(cand, timeout=10)
        except Exception:  # noqa: BLE001
            continue
        if status != 200 or not raw:
            continue
        html = decode(raw)
        with _lock:
            try:
                cf = CACHE_DIR / (re.sub(r"[^\w.-]", "_", cand)[:120] + f".{tag}.html")
                cf.write_text(html, encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
        return html, final or cand
    return None, url


def find_intro_links(home_html: str, home_url: str) -> list[str]:
    out: list[str] = []
    for href, inner in RE_A.findall(home_html):
        txt = clean_text(inner)
        if not txt or len(txt) > 14 or not RE_INTRO_TEXT.search(txt):
            continue
        u = normalize_url(href, home_url)
        if u and u not in out:
            out.append(u)
    return out[:4]


def is_nav_like(t: str) -> bool:
    return sum(1 for k in NAV_TOKENS if k in t) >= 3


def trim_to_name(t: str, names: list[str]) -> str:
    """若段落开头串入了栏目/导航文字，从**首个校名出现处**截断（校名须在前 200 字内）"""
    best = None
    for n in names:
        i = t.find(n)
        if 0 < i <= 200:
            best = i if best is None else min(best, i)
    return t[best:] if best else t


def extract_intro(page_html: str, names: list[str] | None = None) -> str:
    names = [n for n in (names or []) if n]
    h = RE_SCRIPT.sub(" ", page_html)
    h = RE_HEADER_FOOTER.sub(" ", h)
    paras: list[str] = []
    for inner in RE_P.findall(h):
        t = clean_text(inner)
        if cjk_len(t) < MIN_CJK or any(n in t for n in NOISE) or is_nav_like(t):
            continue
        paras.append(trim_to_name(t, names) if names else t)
    if not paras:
        # 回退：整页按标签切块，取最长且非导航的连续块
        blocks = [clean_text(b) for b in RE_ALL_TAGS.split(h)]
        blocks = [b for b in blocks
                  if cjk_len(b) >= MIN_CJK and not any(n in b for n in NOISE) and not is_nav_like(b)]
        if not blocks:
            return ""
        blk = max(blocks, key=cjk_len)
        paras = [trim_to_name(blk, names) if names else blk]
    buf = ""
    for p in paras:
        if cjk_len(buf) >= MAX_CHARS:
            break
        buf += p
    return buf[:MAX_CHARS].strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--all", action="store_true", help="含已有（软科）简介者一并重采")
    args = ap.parse_args()

    print("=" * 74)
    print("D5  school.intro 官方来源采集（逐校官网「学校简介」页）")
    print("=" * 74)

    web = json.loads(WEB_SUPP.read_text(encoding="utf-8"))["records"]
    lib = json.loads(SCHOOLS.read_text(encoding="utf-8"))
    lib_recs = lib["records"] if isinstance(lib, dict) else lib
    have_intro = {r["name"] for r in lib_recs if (r.get("intro") or "").strip()}

    targets: list[dict] = []
    seen: set[str] = set()
    for r in web:
        n = r["school_name"]
        if n in seen:
            continue
        if not r.get("website_verified") or not r.get("website"):
            continue
        if not args.all and n in have_intro:
            continue
        seen.add(n)
        targets.append({"name": n, "website": r["website"], "id": r.get("id"),
                        "code": r.get("code"), "province": r.get("province")})
    if args.limit:
        targets = targets[: args.limit]
    print(f"目标院校：{len(targets)} 所（已校验官网且缺 intro）")

    results: list[dict] = []
    stats = collections.Counter()

    def work(t: dict) -> dict | None:
        home, home_url = fetch_page(t["website"], args.offline, "home")
        if not home:
            return {"name": t["name"], "_status": "home_unreachable"}
        names = [t["name"]]
        links = find_intro_links(home, home_url)
        if not links:
            # ★ 不再回退到首页正文：首页多为新闻/轮播，抽出来不是简介（宁可缺不可猜）
            return {"name": t["name"], "_status": "no_intro_link"}
        for u in links:
            page, used = fetch_page(u, args.offline, "intro")
            if not page:
                continue
            txt = extract_intro(page, names)
            if cjk_len(txt) >= 120:
                return {"name": t["name"], "id": t["id"], "code": t["code"],
                        "province": t["province"], "intro": txt,
                        "source_name": f"{t['name']}官网·学校简介",
                        "source_url": used, "year": 2026,
                        "source_type": "高校官网", "page": "intro"}
        return {"name": t["name"], "_status": "extract_failed"}

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, t): t for t in targets}
        for done, fut in enumerate(as_completed(futs), 1):
            try:
                r = fut.result()
            except Exception as exc:  # noqa: BLE001
                r = {"name": futs[fut]["name"], "_status": f"error:{type(exc).__name__}"}
            if r and r.get("intro"):
                results.append(r)
                stats["ok"] += 1
            elif r:
                stats[r.get("_status", "unknown")] += 1
            if done % 100 == 0 or done == len(targets):
                print(f"  ...{done}/{len(targets)}  成功 {stats['ok']}")

    n = len(targets)
    print()
    print(f"采集成功 : {stats['ok']}/{n} = {(stats['ok']/n*100 if n else 0):.1f}%")
    for k, v in stats.most_common():
        if k != "ok":
            print(f"  失败-{k}: {v}")

    payload = {
        "meta": {
            "generated_at": str(date.today()),
            "owner": "徐（③ 数据工程）",
            "target_table": "school",
            "target_field": "intro",
            "purpose": ("软科接口仅约 1/3 院校有简介 → 本表对**已校验官网**逐校抓取其官网"
                        "「学校简介 / 学校概况」页正文，产出**官方级** intro（可覆盖软科非官方值）。"),
            "official": True,
            "source_name": "各高校官网（学校简介 / 学校概况页）",
            "source_url": "（逐条见记录 source_url，均为该校官网简介页）",
            "year": 2026,
            "triplet_note": "★ 三要素为**逐条**粒度：每条记录的 source_name/source_url/year 指向该校官网简介页本身。",
            "extract_rule": ("首页定位含「简介/概况/介绍」的入口 → 抓正文 → 取含中文≥30 字的 <p> 段落"
                             f"拼接至 {MAX_CHARS} 字；页脚特征词过滤；抽取不达标**留空**。"),
            "caveat": "抽取文本为官网原页面节选，可能夹带页头/栏目残留；不改变原文措辞，不做改写。",
            "coverage": {"targets": n, "ok": stats["ok"], **{f"fail_{k}": v for k, v in stats.items() if k != "ok"}},
        },
        "records": sorted(results, key=lambda a: a["name"]),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"✅ 已写出 {OUT.relative_to(ROOT)}（{len(results)} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
