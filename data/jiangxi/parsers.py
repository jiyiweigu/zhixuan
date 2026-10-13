"""
江西采集 · 页面解析层。

提供与「页面解析方式」一一对应的函数：
- HTML 表格  -> parse_html_table / iter_table_rows
- 正文文本   -> extract_article_text
- 列表页链接 -> extract_links
- PDF 表格   -> parse_pdf_tables（需 pdfplumber）
- 一分一段   -> parse_segment_rows
- 分数单元格 -> parse_score_cell
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

logger = logging.getLogger("jx.parsers")


# ---------------------------------------------------------------------------
# 通用数值
# ---------------------------------------------------------------------------
def to_int(s: object) -> int | None:
    """安全转 int（兼容千分位、全角逗号、'1.2万' 等）。"""
    if s is None:
        return None
    t = str(s).strip().replace(",", "").replace("，", "").replace(" ", "")
    if not t:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*万", t)
    if m:
        return int(float(m.group(1)) * 10000)
    m = re.search(r"\d+(?:\.\d+)?", t)
    if not m:
        return None
    return int(float(m.group(0)))


def to_float(s: object) -> float | None:
    if s is None:
        return None
    t = str(s).strip().replace(",", "").replace("，", "")
    m = re.search(r"\d+(?:\.\d+)?", t)
    return float(m.group(0)) if m else None


def parse_score_cell(cell: str) -> tuple[int | None, int | None]:
    """
    解析分数单元格，返回 (score, score_end)。
      "681及以上"  -> (681, 750)
      "665~750"    -> (665, 750)
      "448(本科线)"-> (448, 448)
      "550"        -> (550, 550)
      "≥681"       -> (681, 750)
    """
    if cell is None:
        return None, None
    s = str(cell).strip().replace(" ", "")
    # 区间 / 及以上
    m = re.match(r"^(\d{1,3})\s*[-–~至]\s*(\d{1,3})$", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    if re.search(r"(及以上|以上|≥|>=)", s):
        m = re.match(r"^(?:≥|>=)?\s*(\d{1,3})", s)
        if m:
            return int(m.group(1)), 750
    # 带批注（448(本科线)）
    m = re.match(r"^(\d{1,3})", s)
    if m:
        v = int(m.group(1))
        return v, v
    return None, None


# ---------------------------------------------------------------------------
# HTML 表格
# ---------------------------------------------------------------------------
def parse_html_table(table) -> list[list[str]]:
    """把一个 <table> 解析为二维字符串列表（自动展开 rowspan/colspan）。"""
    grid: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells: list[str] = []
        for cell in tr.find_all(["td", "th"]):
            text = cell.get_text(" ", strip=True)
            span = to_int(cell.get("colspan")) or 1
            cells.append(text)
            cells.extend([""] * (span - 1))
        if any(c for c in cells):
            grid.append(cells)
    return grid


def iter_table_rows(soup: BeautifulSoup, table_selector: str | None = None):
    """
    遍历页面所有表格行，yield list[str]。
    table_selector 支持 CSS（如 'table.list'）；None 表示全部 <table>。
    """
    tables = soup.select(table_selector) if table_selector else soup.find_all("table")
    for tb in tables:
        for row in parse_html_table(tb):
            yield row


def find_best_table(soup: BeautifulSoup, min_rows: int = 5, min_cols: int = 2):
    """挑选页面上「行数最多」的表格（一分一段/投档表通常是最长表）。"""
    best, best_n = None, 0
    for tb in soup.find_all("table"):
        grid = parse_html_table(tb)
        n = sum(1 for r in grid if len(r) >= min_cols)
        if n > best_n and n >= min_rows:
            best, best_n = grid, n
    return best


# ---------------------------------------------------------------------------
# 正文
# ---------------------------------------------------------------------------
_ARTICLE_SELECTORS = [
    "div.article", "div.content", "div.TRS_Editor", "div#content",
    "div.article-content", "div.view", "article", "div#p1", "div.zoom",
    "div.news_content", "div.main-content",
]


def extract_article_text(soup: BeautifulSoup) -> str:
    """抽取正文纯文本（尝试多个常见容器，兜底 body）。"""
    for sel in _ARTICLE_SELECTORS:
        el = soup.select_one(sel)
        if el and len(el.get_text(strip=True)) >= 80:
            return el.get_text("\n", strip=True)
    if soup.body:
        return soup.body.get_text("\n", strip=True)
    return ""


def extract_title(soup: BeautifulSoup) -> str:
    h1 = soup.find(["h1", "h2"])
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)
    if soup.title and soup.title.get_text(strip=True):
        return soup.title.get_text(strip=True)
    return ""


# ---------------------------------------------------------------------------
# 列表页链接
# ---------------------------------------------------------------------------
def _json_block(text: str, key: str, open_ch: str = "[", close_ch: str = "]") -> str:
    """
    从 text 中定位 `key` 后首个 open_ch，并做「引号感知」的括号配对，
    返回含首尾括号的完整块（用于抽取内联 JSON 数组/对象）。
    """
    ki = text.find(key)
    if ki < 0:
        return ""
    start = text.find(open_ch, ki)
    if start < 0:
        return ""
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return ""


# Hanweb CMS（江西省教育考试院 jxeea.cn 等政务站）：
#   文章列表在 list.html 内联为 `listData = { articleList: [ {...} ] }`，
#   每项含 "title" 与 "urls":"{\"pc\":\"/...content_<id>.html\"}"，不是 <a href>。
_ITEM_TITLE = re.compile(r'"title":"((?:[^"\\]|\\.)*)"')
_ITEM_URLS = re.compile(r'"urls":"\{\\"pc\\":\\"([^"\\]+)\\"')


def _json_unescape(s: str) -> str:
    try:
        import json
        return json.loads(f'"{s}"')
    except Exception:  # noqa: BLE001
        return s


def extract_hanweb_links(html: str, base_url: str,
                         keyword: str | None = None) -> list[tuple[str, str]]:
    """抽取 Hanweb 内联 `articleList` 中的文章链接 → [(title, absolute_url)]。"""
    if not html or "articleList" not in html:
        return []
    block = _json_block(html, "articleList")
    if not block:
        return []
    titles = _ITEM_TITLE.findall(block)
    paths = _ITEM_URLS.findall(block)
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for t, p in zip(titles, paths):
        title = _json_unescape(t).strip()
        url = urljoin(base_url, p.strip())
        if not url or url in seen:
            continue
        if keyword and keyword not in title and keyword not in url:
            continue
        seen.add(url)
        out.append((title or url, url))
    return out


def extract_links(soup: BeautifulSoup, base_url: str,
                  keyword: str | None = None) -> list[tuple[str, str]]:
    """
    抽取列表页链接，返回 [(title, absolute_url)]。
    支持两类：① 常规 <a href>；② 内联 JSON（Hanweb CMS 的 articleList）。
    keyword：仅保留标题/链接包含该关键词的项（如 "一分一段" / "投档"）。
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        title = a.get_text(" ", strip=True)
        if not href or href.startswith(("javascript:", "#", "mailto:")):
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        if keyword and keyword not in title and keyword not in url:
            continue
        seen.add(url)
        out.append((title or url, url))
    # ② 内联 JSON（原始 HTML 由 Fetcher.get_soup 挂到 soup.__dict__）
    raw = soup.__dict__.get("_raw_html", "") if hasattr(soup, "__dict__") else ""
    for title, url in extract_hanweb_links(raw, base_url, keyword):
        if url not in seen:
            seen.add(url)
            out.append((title, url))
    return out


# ---------------------------------------------------------------------------
# 一分一段
# ---------------------------------------------------------------------------
def parse_segment_rows(rows: list[list[str]]) -> list[dict]:
    """
    从表格行解析一分一段：取前 3 列 = 分数 | 本段人数 | 累计人数。
    返回 [{'score','score_end','same_score_count','cumulative_rank'}]。
    """
    out: list[dict] = []
    for r in rows:
        if len(r) < 3:
            continue
        raw_score = r[0].strip()
        if not re.search(r"\d", raw_score):
            continue
        if raw_score in ("分数", "分段", "成绩", "档分"):
            continue
        score, score_end = parse_score_cell(raw_score)
        cum = to_int(r[2])
        cnt = to_int(r[1])
        if score is None or cum is None or cum <= 0:
            continue
        out.append({
            "score": score,
            "score_end": score_end if score_end and score_end != score else None,
            "same_score_count": cnt,
            "cumulative_rank": cum,
        })
    return out


def fill_single_score_gaps(rows: list[dict]) -> list[dict]:
    """填补间隔恰为 1 的缺行（数学可精确还原）；多分缺口保留并告警。"""
    if len(rows) < 3:
        return rows
    by_score = {r["score"]: r for r in rows}
    scores = sorted(by_score)
    out = list(rows)
    for lo, hi in zip(scores, scores[1:]):
        gap = hi - lo
        if gap <= 1:
            continue
        if gap == 2:
            a, b = by_score[lo], by_score[hi]
            missing = lo + 1
            cum_m = a["cumulative_rank"] - (a["same_score_count"] or 0)
            cnt_m = cum_m - b["cumulative_rank"]
            out.append({"score": missing, "score_end": None,
                        "same_score_count": cnt_m, "cumulative_rank": cum_m})
            logger.info("  插值补缺分 %d (count=%s, cum=%s)", missing, cnt_m, cum_m)
        else:
            logger.warning("  多分缺口 %d~%d，无法插值，跳过", lo, hi)
    return out


# ---------------------------------------------------------------------------
# PDF 表格
# ---------------------------------------------------------------------------
def parse_pdf_tables(pdf_bytes: bytes) -> list[list[list[str]]]:
    """用 pdfplumber 抽取 PDF 中的所有表格（未安装则返回空）。"""
    try:
        import io

        import pdfplumber  # type: ignore
    except ImportError:  # pragma: no cover
        logger.warning("未安装 pdfplumber，跳过 PDF 解析：pip install pdfplumber")
        return []
    tables: list[list[list[str]]] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                for tb in page.extract_tables() or []:
                    tables.append([[ (c or "").strip() for c in row] for row in tb])
    except Exception as e:  # noqa: BLE001
        logger.error("PDF 解析失败：%s", e)
    return tables


# ---------------------------------------------------------------------------
# 通用正则抽取
# ---------------------------------------------------------------------------
def search_float(text: str, pattern: str) -> float | None:
    m = re.search(pattern, text)
    return to_float(m.group(1)) if m else None


def find_all_float(text: str, pattern: str) -> list[float]:
    vals: list[float] = []
    for m in re.finditer(pattern, text):
        v = to_float(m.group(1))
        if v is not None:
            vals.append(v)
    return vals
