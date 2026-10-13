"""
一分一段表采集器（score_segment）。

数据源：中国教育在线 · 掌上高考（gaokao.eol.cn）
  - robots.txt 允许抓取
  - 提供 2023–2025 年河南高考一分一段表，HTML 表格，结构统一：分数 | 人数 | 累计人数
  - 来源类型：公开网络（转载自河南省教育考试院），可靠性 high

河南口径（数据工程方案 §二）：
  - 2023–2024：老高考，科类 = 文科 / 理科
  - 2025+   ：新高考，科类 = 历史类 / 物理类
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from bs4 import BeautifulSoup

from .base import RawRecord, fetch, get_soup, parse_score_cell, to_int

logger = logging.getLogger(__name__)

SOURCE_NAME = "中国教育在线·掌上高考（转载河南省教育考试院）"

# (year, subject_type, url)
# subject_type 对齐 schema 枚举：文科|理科|历史类|物理类
SCORE_SEGMENT_URLS: list[tuple[int, str, str]] = [
    (2025, "物理类", "https://gaokao.eol.cn/he_nan/dongtai/202506/t20250625_2676859.shtml"),
    (2025, "历史类", "https://gaokao.eol.cn/he_nan/dongtai/202506/t20250625_2676858.shtml"),
    (2024, "理科",   "https://gaokao.eol.cn/he_nan/dongtai/202406/t20240625_2619212_1.shtml"),
    (2024, "文科",   "https://gaokao.eol.cn/he_nan/dongtai/202406/t20240625_2619212.shtml"),
    (2023, "理科",   "https://gaokao.eol.cn/he_nan/dongtai/202306/t20230625_2446847.shtml"),
    (2023, "文科",   "https://gaokao.eol.cn/he_nan/dongtai/202306/t20230625_2446851.shtml"),
]


@dataclass
class SegmentRow:
    score: int
    same_score_count: int | None
    cumulative_rank: int
    score_end: int | None = None   # 区间上界（仅最高分段 710-750 有）


def _parse_table(soup: BeautifulSoup) -> list[SegmentRow]:
    """解析 eol.cn 一分一段 HTML 表格。"""
    table = soup.find("table")
    if not table:
        return []
    rows: list[SegmentRow] = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        if len(cells) < 3:
            continue
        score_raw, cnt_raw, cum_raw = cells[0], cells[1], cells[2]
        # 跳过表头
        if score_raw in ("分数", "分段"):
            continue
        score, score_end = parse_score_cell(score_raw)
        cum = to_int(cum_raw)
        cnt = to_int(cnt_raw)
        if score is None or cum is None:
            continue
        rows.append(SegmentRow(
            score=score, same_score_count=cnt, cumulative_rank=cum,
            score_end=score_end if score_end != score else None,
        ))
    return rows


def _fill_single_score_gaps(rows: list[SegmentRow]) -> list[SegmentRow]:
    """
    填补源表中缺失的单个分数行（源网站偶有缺行，如恰好本科线分数）。
    仅填补间隔为 1 的缺口（数学可精确还原）：
      cum(S+1) = cum(S) - count(S)
      count(S+1) = cum(S+1) - cum(S+2)
    间隔 > 1 的缺口保留并记录。
    """
    if len(rows) < 3:
        return rows
    by_score = {r.score: r for r in rows}
    sorted_scores = sorted(by_score.keys())
    filled = list(rows)
    gaps_multiple = 0
    for i in range(len(sorted_scores) - 1):
        s_lo = sorted_scores[i]
        s_hi = sorted_scores[i + 1]
        gap = s_hi - s_lo
        if gap <= 1:
            continue
        if gap == 2:
            # 恰好缺失一个分数
            lo = by_score[s_lo]
            hi = by_score[s_hi]
            missing = s_lo + 1
            cum_missing = lo.cumulative_rank - (lo.same_score_count or 0)
            cnt_missing = cum_missing - hi.cumulative_rank
            filled.append(SegmentRow(
                score=missing, same_score_count=cnt_missing,
                cumulative_rank=cum_missing,
            ))
            logger.info("  填补缺失分数 %d (count=%d, cum=%d)", missing, cnt_missing, cum_missing)
        else:
            gaps_multiple += 1
            logger.warning("  多分缺口 (%d~%d) 无法插值，跳过", s_lo, s_hi)
    return filled


def collect_segment(year: int, subject_type: str, url: str,
                    batch_no: str) -> list[RawRecord]:
    """采集单张一分一段表。"""
    logger.info("collect score_segment: %d %s <- %s", year, subject_type, url)
    soup = get_soup(url, referer="https://gaokao.eol.cn/")
    rows = _parse_table(soup)
    rows = _fill_single_score_gaps(rows)
    records: list[RawRecord] = []
    for i, r in enumerate(rows, start=1):
        data = {
            "province": "河南",
            "year": year,
            "subject_type": subject_type,
            "score": r.score,
            "same_score_count": r.same_score_count,
            "cumulative_rank": r.cumulative_rank,
            "score_end": r.score_end,
        }
        records.append(RawRecord(
            data=data, source_name=SOURCE_NAME, source_url=url,
            year=year, doc_type="score_segment", batch_no=batch_no, row_no=i,
        ))
    logger.info("  -> %d rows", len(records))
    return records


def collect_all(batch_no: str) -> list[RawRecord]:
    """采集所有一分一段表。"""
    all_records: list[RawRecord] = []
    for year, subject_type, url in SCORE_SEGMENT_URLS:
        try:
            all_records.extend(collect_segment(year, subject_type, url, batch_no))
        except Exception as e:
            logger.error("collect_segment failed for %d %s: %s", year, subject_type, e)
    return all_records
