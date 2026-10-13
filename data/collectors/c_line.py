"""批次录取控制分数线采集器（batch_score_line）—— 平台结构化表来源（次要）。

数据源：河南省阳光高考信息平台「分数线汇总」
    https://gaokao.haedu.cn/scoreline

⚠️ 实测结论（2026-10-11）：
    `/scoreline` 是**栏目索引页**（无 <table>），其子页为逐年文章，而逐年文章里的
    分数线表格是**图片**（<img> 而非 <table>），另有部分为 JS 动态加载（/content/xxx
    返回"载入中..."）。因此该站**无法用静态解析拿到分数线数值**。
    本模块的 `parse_scoreline` 仍保留（对任何结构规范的 <table> 源均可用，且被离线
    自检覆盖），作为**次要/兜底**来源；D-3 的**主来源**改用政府公告页
    （见 `c_batch_line.py`：省教育厅/省政府门户的静态正文公告）。

页面按年份分块，每块一张表，两种表头：
    2025 起：录取批次 | 历史类 | 物理类
    2024 及以前：录取批次 | 文科 | 理科

该数据用于冲稳保梯度判断与资格判定的分数门槛，属 P0。
"""
from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from .base import RawRecord, get_soup, to_int, normalize_batch, normalize_subject

logger = logging.getLogger(__name__)

SOURCE_NAME = "河南省阳光高考信息平台"
SOURCE_URL = "https://gaokao.haedu.cn/scoreline"

SUBJECT_KEYS = ("历史类", "物理类", "文科", "理科", "综合")
BATCH_HINTS = ("特殊类型", "本科", "专科", "高职", "提前")


def _table_year(table, default_year: int | None) -> int | None:
    """从表格上方最近的「XXXX年」标题中取年份。"""
    for el in table.find_all_previous(string=True):
        m = re.search(r"(\d{4})\s*年", el)
        if m:
            y = int(m.group(1))
            if 2000 <= y <= 2100:
                return y
    return default_year


def parse_scoreline(soup: BeautifulSoup, source_url: str = SOURCE_URL,
                    default_year: int | None = None) -> list[RawRecord]:
    """解析分数线汇总页，返回 batch_score_line 记录。"""
    records: list[RawRecord] = []
    for table in soup.find_all("table"):
        rows = [[c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
                for tr in table.find_all("tr")]
        if not rows:
            continue

        # 定位「科类表头行」：包含 历史类/物理类/文科/理科 的那一行
        subj_cols: dict[int, str] = {}
        header_ri: int | None = None
        for ri, cells in enumerate(rows):
            found = {ci: k for ci, txt in enumerate(cells)
                     for k in SUBJECT_KEYS if k == txt}
            if found:
                subj_cols, header_ri = found, ri
                break
        if not subj_cols or header_ri is None:
            continue

        year = _table_year(table, default_year)
        if not year:
            logger.warning("  无法确定年份，跳过一张分数线表")
            continue

        for cells in rows[header_ri + 1:]:
            if len(cells) < 2:
                continue
            batch = normalize_batch(cells[0])
            if not batch or not any(h in batch for h in BATCH_HINTS):
                continue
            for ci, subject in subj_cols.items():
                if ci >= len(cells):
                    continue
                score = to_int(cells[ci])
                if score is None or not (0 <= score <= 750):
                    continue
                subj = normalize_subject(subject)
                if not subj:
                    continue
                records.append(RawRecord(
                    data={
                        "province": "河南",
                        "year": year,
                        "batch": batch,
                        "subject_type": subj,
                        "score": score,
                    },
                    source_name=SOURCE_NAME,
                    source_url=source_url,
                    year=year,
                    doc_type="batch_score_line",
                ))
    logger.info("batch_score_line -> %d rows", len(records))
    return records


def collect_all(batch_no: str) -> list[RawRecord]:
    """抓取分数线汇总页并解析全部年份。"""
    try:
        soup = get_soup(SOURCE_URL, referer="https://gaokao.haedu.cn/")
    except Exception as e:                       # noqa: BLE001
        logger.error("采集批次分数线失败：%s", e)
        return []
    records = parse_scoreline(soup)
    for i, r in enumerate(records, start=1):
        r.batch_no = batch_no
        r.row_no = i
    return records
