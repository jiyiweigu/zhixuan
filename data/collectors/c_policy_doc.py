"""
政策文件全文采集器（D-16）→ knowledge_doc + knowledge_chunk（RAG 切片）。

数据源（静态官方页，逐条登记来源三要素）：
  - 《河南省2025年普通高校招生考试和录取工作实施方案》 河南省教育厅
  - 《河南省2025年普通高校招生考生指南》（含投档规则/志愿设置） 河南省政府门户
  - 《河南省教育厅关于做好2024年普通高等学校招生工作的通知》 河南省教育厅
  - 《河南省近三年本科二批平行投档分数线》 省政府门户（数据类补充）

切片规则：约 300 字/片、重叠 50 字；切片带 province/pathway_id 元数据。
"""
from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from .base import RawRecord, fetch, get_soup, save_raw

logger = logging.getLogger(__name__)

# (year, title, url, source_name, doc_type, pathway_name)
REGISTRY: list[tuple[int, str, str, str, str, str]] = [
    (2025, "河南省2025年普通高校招生考试和录取工作实施方案",
     "https://jyt.henan.gov.cn/2025/01-24/3117467.html",
     "河南省教育厅", "政策", ""),
    (2025, "河南省2025年普通高校招生考生指南",
     "https://www.henan.gov.cn/2025/06-24/3173548.html",
     "河南省人民政府门户网站（转河南省教育考试院）", "政策", ""),
    (2025, "2025年河南省普通高校招生录取控制分数线",
     "https://jyt.henan.gov.cn/2025/06-25/3173853.html",
     "河南省教育厅", "分数线", ""),
    (2024, "河南省教育厅关于做好2024年普通高等学校招生工作的通知",
     "https://jyt.henan.gov.cn/2024/04-29/2985024.html",
     "河南省教育厅", "政策", ""),
    (2024, "河南省近三年本科二批平行投档分数线",
     "https://m.henan.gov.cn/2024/06-25/3012671.html",
     "河南省人民政府门户网站（转河南省教育考试院）", "分数线", ""),
]

CHUNK_SIZE = 300
CHUNK_OVERLAP = 50


def _extract_main_text(soup: BeautifulSoup) -> str:
    """提取正文：gov 站点常见容器 → 兜底取最长文本块。"""
    for sel in [("div", {"id": "p1"}), ("div", {"class": "article"}),
                ("div", {"class": re.compile("article-content|TRS_Editor|content", re.I)}),
                ("article", {})]:
        el = soup.find(sel[0], sel[1] or None)
        if el and len(el.get_text(strip=True)) > 200:
            return el.get_text("\n", strip=True)
    # 兜底：取页面中文字符最多的 div
    best, best_len = "", 0
    for div in soup.find_all(["div", "section", "article"]):
        t = div.get_text("\n", strip=True)
        cn = len(re.findall(r"[\u4e00-\u9fff]", t))
        if cn > best_len:
            best, best_len = t, cn
    return best


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """滑窗切片：按段落聚合到约 size 字，重叠 overlap 字。"""
    paras = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    chunks: list[str] = []
    cur = ""
    for p in paras:
        if len(cur) + len(p) + 1 > size and cur:
            chunks.append(cur)
            cur = cur[-overlap:] if overlap < len(cur) else ""
        cur = (cur + "\n" + p).strip() if cur else p
    if cur:
        chunks.append(cur)
    return [c for c in chunks if len(c) >= 20]


def collect_all(batch_no: str) -> list[RawRecord]:
    """采集政策文件全文并切片。"""
    records: list[RawRecord] = []
    row_no = 0
    for year, title, url, source_name, doc_type, pathway in REGISTRY:
        try:
            soup = get_soup(url)
        except Exception as e:
            logger.error("policy %s fetch failed: %s", title, e)
            continue
        text = _extract_main_text(soup)
        cn = len(re.findall(r"[\u4e00-\u9fff]", text))
        if cn < 200:
            logger.warning("policy %s 正文过短(%d 字)，跳过", title, cn)
            continue
        logger.info("policy [%d] %s: %d 汉字", year, title, cn)

        # knowledge_doc 主文档
        row_no += 1
        records.append(RawRecord(
            data={
                "title": title, "doc_category": doc_type, "province": "河南",
                "pathway_name": pathway, "content": text,
                "char_count": cn,
            },
            source_name=source_name, source_url=url, year=year,
            doc_type="knowledge_doc", batch_no=batch_no, row_no=row_no,
        ))
        save_raw(url, text, "txt")

        # knowledge_chunk 切片
        for ci, chunk in enumerate(chunk_text(text), start=1):
            row_no += 1
            records.append(RawRecord(
                data={
                    "doc_title": title, "chunk_index": ci, "content": chunk,
                    "province": "河南", "pathway_name": pathway,
                },
                source_name=source_name, source_url=url, year=year,
                doc_type="knowledge_chunk", batch_no=batch_no, row_no=row_no,
            ))
    return records
