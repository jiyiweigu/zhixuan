# -*- coding: utf-8 -*-
"""
N3 · 2026 一分一段表（score_segment_2026_*）来源可验证性复核
=============================================================

背景
====
``score_segment_2026_历史类.json`` / ``score_segment_2026_物理类.json`` 是
从河南省教育考试院官方发布的**扫描件 PDF** 经 OCR 解析而来。其来源三要素
写在这两个文件的**文件级 meta** 里，而非每条记录内。

2026-10-13 的来源回溯（N3）确认了三件事，本脚本负责**机械复核**它们：

  1. **来源 URL 存活且内容对得上**
     页面标题、栏目、发布时间、附件编号必须与登记值一致。
  2. **原始文件在库且指纹对得上**
     ``data/samples/raw/分数段统计表_2026_*.pdf`` 的 /Author、页数、
     「无文本层」特征，须与登记值一致。
  3. **JSON 里引用的 source_id 必须已在 source 表中登记**
     空引用（悬空外键）视为失败 —— 这正是 N3 回溯前存在的缺陷。

复核对象（登记值）
==================
三者必须互相一致：
  - ``data/sources/source-table.json`` 中 ``SRC-HENAN-SCORE-SEG-2026`` 条目
  - ``data/score_segment/score_segment_2026_*.json`` 的 ``meta``
  - 真实网页 / 真实 PDF（--offline 时跳过）

用法
====
  python data/scripts/verify_score_segment_2026_source.py            # 含联网探测
  python data/scripts/verify_score_segment_2026_source.py --offline  # 仅本地一致性
  python data/scripts/verify_score_segment_2026_source.py --strict   # 失败则退出码 1

退出码：0 = 全部通过；1 = 存在失败项（--strict 时）
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_TABLE = ROOT / "data" / "sources" / "source-table.json"
SEG_DIR = ROOT / "data" / "score_segment"
RAW_DIR = ROOT / "data" / "samples" / "raw"

SOURCE_ID = "SRC-HENAN-SCORE-SEG-2026"

# 两个 2026 数据集文件 ↔ 对应的原始扫描件
DATASETS = [
    ("score_segment_2026_历史类.json", "分数段统计表_2026_历史类.pdf", "历史类"),
    ("score_segment_2026_物理类.json", "分数段统计表_2026_物理类.pdf", "物理类"),
]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 期望值（回溯时实测得到；如官方页面改版需人工复核后更新）
EXPECT_PAGE_TITLE = "2026年河南省普通高招分数段统计表"
EXPECT_PUBLISH_DATE = "2026-06-25"
EXPECT_PDF_AUTHOR = "河南省招生办公室"
EXPECT_PDF_PAGES = 8


def _load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _dec_pdf_str(v) -> str:
    """pypdf 读出的 PDF 元数据字符串可能是 '<hex>' 形式（GBK/UTF-16）。"""
    if v is None:
        return ""
    if isinstance(v, bytes):
        v = v.decode("latin-1")
    s = str(v).strip()
    if s.startswith("<") and s.endswith(">"):
        try:
            b = bytes.fromhex(s[1:-1])
            if b.startswith(b"\xfe\xff"):
                return b[2:].decode("utf-16-be", errors="replace")
            return b.decode("gbk", errors="replace")
        except Exception:
            return s
    return s


def check_local() -> tuple[list[str], list[str]]:
    """本地一致性：source 表登记 ↔ 两份 JSON 的 meta ↔ 原始 PDF 指纹。"""
    ok: list[str] = []
    bad: list[str] = []

    # ── 1) source 表登记 ──────────────────────────────────────
    if not SOURCE_TABLE.exists():
        bad.append(f"source 表不存在：{SOURCE_TABLE}")
        return ok, bad
    sources = _load_json(SOURCE_TABLE).get("sources", [])
    entry = next((x for x in sources if x.get("id") == SOURCE_ID), None)
    if entry is None:
        bad.append(f"⛔ 悬空外键：{SOURCE_ID} 未登记在 source 表（共 {len(sources)} 条）")
        return ok, bad

    reg_name = entry.get("source_name", "")
    reg_url = entry.get("source_url", "")
    reg_year = entry.get("year")
    reg_type = entry.get("source_type", "")
    ok.append(f"source 表已登记 {SOURCE_ID}（source_type={reg_type}，year={reg_year}）")

    ids = [x.get("id") for x in sources]
    if len(ids) != len(set(ids)):
        bad.append("source 表存在 id 重复")
    triples = [(x.get("source_name"), x.get("source_url"), x.get("year")) for x in sources]
    if len(triples) != len(set(triples)):
        bad.append("source 表存在 (source_name, source_url, year) 重复 —— 违反三要素唯一性")

    # ── 2) 两份 JSON 的 meta 是否与之逐字一致 ──────────────────
    for json_name, pdf_name, subject in DATASETS:
        jp = SEG_DIR / json_name
        if not jp.exists():
            bad.append(f"缺少数据集文件：{jp.relative_to(ROOT).as_posix()}")
            continue
        d = _load_json(jp)
        m = d.get("meta", {})
        recs = d.get("segments", [])

        if m.get("source_name") != reg_name:
            bad.append(f"{json_name}：meta.source_name 与 source 表不一致\n"
                       f"      JSON = {m.get('source_name')!r}\n"
                       f"      表   = {reg_name!r}")
        if m.get("source_url") != reg_url:
            bad.append(f"{json_name}：meta.source_url 与 source 表不一致\n"
                       f"      JSON = {m.get('source_url')!r}\n"
                       f"      表   = {reg_url!r}")
        if m.get("year") != reg_year:
            bad.append(f"{json_name}：meta.year={m.get('year')!r} ≠ 表 {reg_year!r}")
        if m.get("source_id") != SOURCE_ID:
            bad.append(f"{json_name}：meta.source_id={m.get('source_id')!r} ≠ {SOURCE_ID}")

        # 记录级：score_segment 属 SOURCE_ID_KINDS，靠 source_id 外键满足来源要求
        miss_sid = sum(1 for r in recs if not r.get("source_id"))
        if recs and miss_sid == len(recs):
            ok.append(f"{json_name}：{len(recs)} 条记录均无记录级 source_id，"
                      f"依赖文件级 meta 回退（validate.py 已支持，PASS）")

        if not recs:
            bad.append(f"{json_name}：segments 为空")

        # ── 3) 原始 PDF 指纹 ─────────────────────────────────
        pp = RAW_DIR / pdf_name
        if not pp.exists():
            bad.append(f"{json_name}：原始扫描件缺失 {pp.relative_to(ROOT).as_posix()}")
            continue
        try:
            from pypdf import PdfReader
        except ImportError:
            ok.append(f"{pdf_name}：未安装 pypdf，跳过 PDF 指纹核对")
            continue
        r = PdfReader(str(pp))
        author = _dec_pdf_str((r.metadata or {}).get("/Author"))
        npages = len(r.pages)
        text_len = len((r.pages[0].extract_text() or "").strip())

        if author != EXPECT_PDF_AUTHOR:
            bad.append(f"{pdf_name}：/Author={author!r} ≠ 期望 {EXPECT_PDF_AUTHOR!r}")
        if npages != EXPECT_PDF_PAGES:
            bad.append(f"{pdf_name}：页数 {npages} ≠ 期望 {EXPECT_PDF_PAGES}")
        if text_len != 0:
            bad.append(f"{pdf_name}：第 1 页有文本层（{text_len} 字），"
                       f"与「扫描件须 OCR」的登记不符 —— 官方可能已改为电子版，请复核")
        if author == EXPECT_PDF_AUTHOR and npages == EXPECT_PDF_PAGES and text_len == 0:
            ok.append(f"{pdf_name}：指纹一致（/Author={author}，{npages} 页，无文本层）")

    return ok, bad


def check_online(url: str) -> tuple[list[str], list[str]]:
    """联网：页面存活 + 标题/发布时间/附件编号匹配。"""
    ok: list[str] = []
    bad: list[str] = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            code = resp.status
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        bad.append(f"⛔ 来源 URL 不可达：{url}（{type(e).__name__}: {e}）")
        return ok, bad

    if code != 200:
        bad.append(f"⛔ 来源 URL 返回 HTTP {code}（期望 200）：{url}")
        return ok, bad
    ok.append(f"来源 URL 存活 HTTP 200：{url}")

    m = re.search(r"<title>(.*?)</title>", html, re.S)
    title = (m.group(1).strip() if m else "")
    if EXPECT_PAGE_TITLE not in title:
        bad.append(f"页面标题不含期望串：title={title[:80]!r}，期望含 {EXPECT_PAGE_TITLE!r}")
    else:
        ok.append(f"页面标题匹配：{title[:60]}")

    m = re.search(r"(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}", html)
    pub = m.group(1) if m else ""
    if pub != EXPECT_PUBLISH_DATE:
        bad.append(f"页面发布时间 {pub!r} ≠ 期望 {EXPECT_PUBLISH_DATE!r}（页面可能改版）")
    else:
        ok.append(f"页面发布时间匹配：{pub}")

    # 附件编号须与 URL 尾号一致（本页 data-aid=155639）
    m_url = re.search(r"/(\d+)\.html", url)
    m_aid = re.search(r'data-aid="(\d+)"', html)
    if m_url and m_aid:
        if m_url.group(1) == m_aid.group(1):
            ok.append(f"附件 data-aid={m_aid.group(1)} 与 URL 尾号一致")
        else:
            bad.append(f"附件 data-aid={m_aid.group(1)} ≠ URL 尾号 {m_url.group(1)}")

    n_attach = len(re.findall(r"附件\s*\d+\.", html))
    if n_attach >= 2:
        ok.append(f"页面含 {n_attach} 个附件链接（历史类 / 物理类）")
    else:
        bad.append(f"页面附件数 {n_attach} < 2，与登记（两个附件）不符")

    return ok, bad


def main() -> int:
    ap = argparse.ArgumentParser(description="复核 2026 一分一段表的来源可验证性（N3）")
    ap.add_argument("--offline", action="store_true", help="只做本地一致性核对，不联网")
    ap.add_argument("--strict", action="store_true", help="存在失败项时返回退出码 1")
    args = ap.parse_args()

    print("=" * 74)
    print("N3 · 2026 一分一段表来源可验证性复核")
    print("=" * 74)

    ok, bad = check_local()

    if not args.offline:
        # 从 source 表取 URL 做联网探测（取登记值，而非 JSON 里的，避免自证）
        try:
            sources = _load_json(SOURCE_TABLE).get("sources", [])
            url = next((x["source_url"] for x in sources if x.get("id") == SOURCE_ID), None)
        except Exception:  # noqa: BLE001
            url = None
        if url:
            o2, b2 = check_online(url)
            ok += o2
            bad += b2
        else:
            bad.append("无法取得登记 URL，跳过联网探测")
    else:
        print("\n[--offline] 跳过联网探测\n")

    print("\n── 通过 ──")
    for line in ok:
        print("  ✅", line)
    if bad:
        print("\n── 失败 ──")
        for line in bad:
            print("  ❌", line)

    print("\n" + "=" * 74)
    print(f"结论：通过 {len(ok)} 项，失败 {len(bad)} 项")
    print("=" * 74)

    if args.strict and bad:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
