"""批次录取控制分数线采集器（D-3）—— 官方政府发布页来源【主来源】。

与 `c_line.py`（河南省阳光高考信息平台「分数线汇总」结构化表）互为交叉验证：
  - 本模块：逐年抓取省政府门户的**官方发布原文**，正文全文落
    knowledge_doc（可溯源、可阅读），同时抽取结构化行 batch_score_line。
    ✅ 实测该来源为静态正文、可稳定解析；而平台站(gaokao.haedu.cn)的分数线
       表格为**图片/JS 动态加载**（见 c_line.py 文件头说明），故本模块是 D-3 的
       **主来源**。
  - `c_line.py`：结构化 <table> 解析器（对规范表格源可用），作为**次要/兜底**来源。

两者统一产出 doc_type=batch_score_line（同名批次按主键去重，主来源优先），
不再使用历史上的 batch_line 独立 doc_type（已废弃）。

数据源（均为实测静态的官方发布页，逐条登记来源三要素）：
  2025  省政府门户    https://www.henan.gov.cn/2025/06-25/3173563.html
  2024  省政府门户    https://m.henan.gov.cn/2024/06-25/3012665.html
  2023  省政府门户    https://www.henan.gov.cn/2023/06-25/2765748.html
  注：jyt.henan.gov.cn 与 www.henan.gov.cn 部分同主题文章为 JS 渲染壳页，
  已逐条实测换成可静态解析的发布页。
"""
from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from .base import (RawRecord, get_soup, save_raw, normalize_batch,
                   normalize_subject)

logger = logging.getLogger(__name__)

# (year, source_name, url)
REGISTRY: list[tuple[int, str, str]] = [
    (2025, "河南省人民政府门户网站（转河南省教育考试院）",
     "https://www.henan.gov.cn/2025/06-25/3173563.html"),
    (2024, "河南省人民政府门户网站（转河南省教育考试院）",
     "https://m.henan.gov.cn/2024/06-25/3012665.html"),
    (2023, "河南省人民政府门户网站（转河南省教育考试院）",
     "https://www.henan.gov.cn/2023/06-25/2765748.html"),
]

SUBJECT_PAT = r"(文科|理科|历史类|物理类|综合改革)"


def _extract_rows_from_tables(soup: BeautifulSoup) -> list[dict]:
    """优先：解析页面中的批次线表格（一行可能同时含文/理 或 历史/物理两科）。"""
    rows: list[dict] = []
    for tb in soup.find_all("table"):
        for tr in tb.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            line = " | ".join(cells)
            rows.extend(_parse_batch_line_row(line))
    return rows


def _extract_rows_from_text(text: str) -> list[dict]:
    """兜底：从正文段落解析"本科一批文科547分，理科514分"式文本。"""
    rows: list[dict] = []
    for m in re.finditer(
        r"(本科一批|本科二批|本科批|特殊类型|高职高专批|专科批|普通高职（专科）批)[^。；\n]{0,120}",
        text,
    ):
        seg = m.group(0)
        batch = normalize_batch(m.group(1))
        # 形如 "文科547分，理科514分" / "历史类471分，物理类427分"
        for sm in re.finditer(SUBJECT_PAT + r"[^\d]{0,8}(\d{3})分", seg):
            subj = normalize_subject(sm.group(1))
            if subj:
                rows.append({"batch": batch, "subject_type": subj,
                             "score": int(sm.group(2))})
        # 形如 "文科 521 / 理科 511"（无"分"字）
        if not any(r["batch"] == batch for r in rows):
            for sm in re.finditer(SUBJECT_PAT + r"\s*(\d{3})(?![\d])", seg):
                subj = normalize_subject(sm.group(1))
                if subj:
                    rows.append({"batch": batch, "subject_type": subj,
                                 "score": int(sm.group(2))})
    return rows


def _parse_batch_line_row(line: str) -> list[dict]:
    """解析一行文本，返回其中所有「批次 + 科类 + 分数」组合。"""
    out: list[dict] = []
    for bm in re.finditer(
        r"(本科一批|本科二批|本科批|特殊类型|高职高专批|专科批)", line
    ):
        batch = normalize_batch(bm.group(1))
        for sm in re.finditer(SUBJECT_PAT + r"[^\d]{0,8}(\d{3})", line):
            subj = normalize_subject(sm.group(1))
            if not subj:
                continue
            out.append({"batch": batch, "subject_type": subj,
                        "score": int(sm.group(2))})
    return out


def _norm_subject(s: str) -> str:
    """兼容旧调用：委托给 base.normalize_subject，无法识别时回退「综合」。"""
    return normalize_subject(s) or "综合"


def collect_all(batch_no: str) -> list[RawRecord]:
    """采集三年批次控制线 -> knowledge_doc + batch_line 结构化行。"""
    records: list[RawRecord] = []
    row_no = 0
    for year, source_name, url in REGISTRY:
        try:
            soup = get_soup(url)
        except Exception as e:
            logger.error("batch_line %d fetch failed: %s", year, e)
            continue
        title = soup.title.get_text(strip=True) if soup.title else f"{year}年河南省普通高校招生录取控制分数线"
        # 正文文本（优先 article 容器）
        main = (soup.find("div", id="p1") or soup.find("article")
                or soup.find("div", class_=re.compile("article|content", re.I))
                or soup.body)
        text = main.get_text("\n", strip=True) if main else ""

        rows = _extract_rows_from_tables(soup)
        if not rows:
            rows = _extract_rows_from_text(text)
        logger.info("batch_line %d: %d 条 (来源:%s)", year, len(rows), source_name)
        if not rows:
            continue

        # 结构化行（校验/未来建表）
        structured_lines = [
            f"{r['batch']} {r['subject_type']} {r['score']}分" for r in rows
        ]
        content = (
            f"{year}年河南省普通高校招生录取控制分数线：\n"
            + "\n".join(structured_lines)
            + f"\n\n【原文摘录】\n{text[:800]}"
        )
        # knowledge_doc 行
        row_no += 1
        records.append(RawRecord(
            data={
                "title": title,
                "doc_category": "分数线",
                "province": "河南",
                "content": content,
                "lines": structured_lines,
            },
            source_name=source_name, source_url=url, year=year,
            doc_type="knowledge_doc", batch_no=batch_no, row_no=row_no,
        ))
        # batch_score_line 结构化行（与 c_line.py 同表，靠主键去重）
        for r in rows:
            row_no += 1
            records.append(RawRecord(
                data={
                    "province": "河南", "year": year,
                    "batch": r["batch"], "subject_type": r["subject_type"],
                    "score": r["score"],
                },
                source_name=source_name, source_url=url, year=year,
                doc_type="batch_score_line", batch_no=batch_no, row_no=row_no,
            ))
        save_raw(url, content, "txt")
    return records
