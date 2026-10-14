# -*- coding: utf-8 -*-
"""
E3 · L2 试点核实 —— 我方一分一段 vs 官方转载页（全量逐行）
==========================================================

对象：试点省份（河南 / 江西）中**可取得官方来源页**的 4 组数据
  - 河南 2023（文科 / 理科）
  - 河南 2024（文科 / 理科）
  - 河南 2025（历史类 / 物理类）
  - 江西 2024（历史类 / 物理类）

来源页：`gaokao.eol.cn`（中国教育在线，页面标注转载省考试院一分一段表）。
★ 该站为**商业转载平台**，非考试院直发；其定位（`source_type` 归 `权威媒体` 还是
`其他`）属待裁项。本脚本只做**核实**，不写入任何文件。

HTML 缓存在 `--cache` 目录（默认 C:/Users/lenovo/.pg16/e3_html），可离线复跑 `--offline`。

用法
====
  python data/scripts/verify_e3_official.py                     # 联网抓取 + 比对
  python data/scripts/verify_e3_official.py --offline           # 用缓存
  python data/scripts/verify_e3_official.py --json out.json
  python data/scripts/verify_e3_official.py --strict            # 有差异则退出码 1

退出码：0 = 全部一致；1 = 存在差异（仅 --strict）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OURS_DIR = ROOT / "data" / "score_segment"
DEFAULT_CACHE = Path("C:/Users/lenovo/.pg16/e3_html")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# (我方文件, 科类, 官方转载页 URL)
PAGES = [
    ("score_segment_2023_河南.json", "文科", "https://gaokao.eol.cn/he_nan/dongtai/202306/t20230625_2446851.shtml"),
    ("score_segment_2023_河南.json", "理科", "https://gaokao.eol.cn/he_nan/dongtai/202306/t20230625_2446847.shtml"),
    ("score_segment_2024_河南.json", "文科", "https://gaokao.eol.cn/he_nan/dongtai/202406/t20240625_2619212.shtml"),
    ("score_segment_2024_河南.json", "理科", "https://gaokao.eol.cn/he_nan/dongtai/202406/t20240625_2619212_1.shtml"),
    ("score_segment_2025_河南.json", "历史类", "https://gaokao.eol.cn/he_nan/dongtai/202506/t20250625_2676858.shtml"),
    ("score_segment_2025_河南.json", "物理类", "https://gaokao.eol.cn/he_nan/dongtai/202506/t20250625_2676859.shtml"),
    ("score_segment_2024_江西.json", "历史类", "https://gaokao.eol.cn/jiang_xi/dongtai/202406/t20240626_2619467.shtml"),
    ("score_segment_2024_江西.json", "物理类", "https://gaokao.eol.cn/jiang_xi/dongtai/202406/t20240626_2619478.shtml"),
]


def fetch(url: str, cache: Path, offline: bool) -> str:
    cache.mkdir(parents=True, exist_ok=True)
    fp = cache / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".html")
    fp.with_suffix(".url").write_text(url, encoding="utf-8")
    if fp.exists():
        return fp.read_text(encoding="utf-8", errors="replace")
    if offline:
        raise FileNotFoundError(f"缓存缺失且 --offline：{url}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    fp.write_text(html, encoding="utf-8")
    return html


def parse_table(html: str) -> list[tuple[str, str, str, str]]:
    """返回 [(分数表达式, 人数, 累计人数, 批注)]，跳过表头。

    官方页在批次线位置的行**带中文批注**，如「471（本科线）」「185（专科线）」
    「552（特招线）」；高分区间首行写作「665及以上」。批注单独剥离以保留语义。
    """
    rows = re.findall(r"<tr.*?</tr>", html, re.S)
    out: list[tuple[str, str, str, str]] = []
    for r in rows:
        tds = re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)
        cells = [re.sub(r"<[^>]+>", "", c).replace("&nbsp;", " ").strip() for c in tds]
        if len(cells) < 3:
            continue
        if cells[0] in ("分数", "") or "分数" in cells[0]:
            continue
        note = ""
        mm = re.search(r"[（(]([^）)]*)[）)]", cells[0])
        if mm:
            note = mm.group(1).strip()
        out.append((cells[0], cells[1], cells[2], note))
    return out


def norm_score(expr: str):
    """'685-750' → 685（区间取下界）；'681' → 681；'665及以上' → 665；'471（本科线）' → 471。"""
    s = re.sub(r"[（(].*?[）)]", "", expr).strip()          # 剥离中文批注
    s = re.sub(r"及?以[上下]", "", s).strip()                # 「及以上 / 以下」
    m = re.match(r"^(\d{1,3})\s*[-~—]\s*(\d{1,3})$", s)     # 区间
    if m:
        return int(m.group(1))
    m = re.match(r"^(\d{1,3})$", s)                          # 单分
    if m:
        return int(m.group(1))
    return None


def _int(s: str):
    s = s.strip().replace(",", "")
    m = re.match(r"^-?\d+$", s)
    return int(s) if m else None


def main() -> int:
    ap = argparse.ArgumentParser(description="E3 我方 vs 官方页 全量核实")
    ap.add_argument("--cache", default=str(DEFAULT_CACHE))
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--json")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    cache = Path(args.cache)

    print("=" * 78)
    print("E3 · L2 试点核实 —— 我方一分一段 vs 官方转载页（全量逐行）")
    print("=" * 78)

    our_cache: dict[str, list[dict]] = {}
    report = {"pages": [], "total_ok": 0, "total_mismatch": 0,
              "total_off_only": 0, "total_ours_only": 0}
    any_bad = False

    for our_name, subj, url in PAGES:
        try:
            html = fetch(url, cache, args.offline)
        except Exception as e:  # noqa: BLE001
            print(f"❌ 抓取失败 {url}：{type(e).__name__}: {e}")
            any_bad = True
            continue

        rows = parse_table(html)
        m = re.search(r"<title>(.*?)</title>", html, re.S)
        title = (m.group(1).strip() if m else "")
        # 官方 → {分数: (人数, 累计)}；批注（本科线/专科线/特招线…）单列留证
        off: dict[int, tuple] = {}
        notes: dict[int, str] = {}
        for expr, cnt, cum, note in rows:
            k = norm_score(expr)
            if k is None:
                continue
            off[k] = (_int(cnt), _int(cum))
            if note:
                notes[k] = note

        if our_name not in our_cache:
            d = json.loads((OURS_DIR / our_name).read_text(encoding="utf-8"))
            our_cache[our_name] = d.get("segments", [])
        ours = {int(r["score"]): (r.get("segment_count"), r.get("cumulative_rank"))
                for r in our_cache[our_name] if r.get("subject_type") == subj}

        common = set(off) & set(ours)
        off_only = set(off) - set(ours)
        our_only = set(ours) - set(off)
        diff = [k for k in common if off[k] != ours[k]]
        # 「0 人行」：官方不列该分（人数为 0），我方保留 ⇒ 表述差异，非数值差异
        zero_rows = sorted(k for k in our_only if (ours[k][0] or 0) == 0)
        real_our_only = sorted(our_only - set(zero_rows))

        rep = {"our_file": our_name, "subject_type": subj, "url": url,
               "title": title, "official_rows": len(off), "our_rows": len(ours),
               "consistent": len(common) - len(diff), "mismatch": len(diff),
               "official_only": sorted(off_only)[:30], "ours_only": sorted(our_only)[:30],
               "zero_rows_official_absent": zero_rows,
               "official_annotations": {str(k): v for k, v in sorted(notes.items())},
               "mismatch_detail": [{"score": k, "official": off[k], "ours": ours[k]}
                                   for k in sorted(diff)][:30]}
        report["pages"].append(rep)
        report["total_ok"] += rep["consistent"]
        report["total_mismatch"] += rep["mismatch"]
        report["total_off_only"] += len(off_only)
        report["total_ours_only"] += len(real_our_only)
        report["total_zero_rows"] = report.get("total_zero_rows", 0) + len(zero_rows)

        print(f"\n▌ {our_name} · {subj}")
        print(f"   标题：{title}")
        print(f"   官方 {len(off)} 行 ｜ 我方 {len(ours)} 行")
        print(f"   一致 {rep['consistent']} ｜ 不一致 {rep['mismatch']} ｜ "
              f"仅官方 {len(off_only)} ｜ 仅我方(真) {len(real_our_only)} ｜ "
              f"0 人行(官方不列) {len(zero_rows)}")
        if notes:
            print(f"   官方批注行：{ {k: v for k, v in sorted(notes.items())} }")
        if diff:
            any_bad = True
            for k in sorted(diff)[:15]:
                print(f"   ⚠ {k}: 官方{off[k]} vs 我方{ours[k]}")
        for k in sorted(off_only)[:15]:
            print(f"   ➕ 仅官方 {k}: {off[k]}")
        for k in real_our_only[:15]:
            print(f"   ➖ 仅我方 {k}: {ours[k]}")
        for k in zero_rows:
            print(f"   ○ 0 人行 {k}: 我方{ours[k]}（官方未列该分）")

    print("\n" + "=" * 78)
    print(f"合计：一致 {report['total_ok']} ｜ 不一致 {report['total_mismatch']} ｜ "
          f"仅官方 {report['total_off_only']} ｜ 仅我方(真) {report['total_ours_only']} ｜ "
          f"0 人行(官方不列) {report.get('total_zero_rows', 0)}")
    print("=" * 78)

    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        print(f"结果已写入：{args.json}")
    if args.strict and any_bad:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
