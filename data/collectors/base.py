"""
采集基类：统一的 HTTP 会话、限速、重试、robots 协议校验、原始落盘。

设计原则（对齐《开发产品书_智选志愿》§4.6 与数据工程方案）：
1. 遵守目标站 robots.txt —— Disallow 的路径不抓
2. 单站请求间隔 >= 2s（SLEEP_SECONDS），避免压测服务器
3. 失败指数退避重试
4. 原始响应按 源/日期/hash 落盘，可复现、可追溯
5. 每条采集结果必须带来源三要素：source_name / source_url / year
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

try:                       # lxml 解析更快；缺失时回退内置解析器，保证可移植
    import lxml  # noqa: F401
    PARSER = "lxml"
except ImportError:        # pragma: no cover
    PARSER = "html.parser"

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
RAW_DIR = Path(__file__).resolve().parents[1] / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

SLEEP_SECONDS = 2.0          # 单站请求间隔（秒）
RETRY_TIMES = 3
TIMEOUT = 25.0

# 浏览器 UA（避免被当作纯脚本拦截；不伪装成恶意爬虫）
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# robots 缓存：{domain: set(disallowed_paths)}
_ROBOTS_CACHE: dict[str, set[str]] = {}

logger = logging.getLogger("collectors")


# ---------------------------------------------------------------------------
# 数据记录结构
# ---------------------------------------------------------------------------
@dataclass
class RawRecord:
    """一条原始采集记录（未清洗），必带来源三要素。"""
    data: dict[str, Any]
    source_name: str
    source_url: str
    year: int
    doc_type: str                          # score_segment / school / major / admission / ...
    batch_no: str = ""
    row_no: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# robots 协议
# ---------------------------------------------------------------------------
def _domain(url: str) -> str:
    return urlparse(url).netloc


def fetch_robots(domain: str) -> set[str]:
    """拉取并缓存某域名的 robots.txt Disallow 规则。"""
    if domain in _ROBOTS_CACHE:
        return _ROBOTS_CACHE[domain]
    disallowed: set[str] = set()
    try:
        r = httpx.get(
            f"https://{domain}/robots.txt",
            headers=DEFAULT_HEADERS,
            timeout=15,
            follow_redirects=True,
        )
        if r.status_code == 200:
            for line in r.text.splitlines():
                line = line.strip()
                if line.lower().startswith("disallow:"):
                    path = line.split(":", 1)[1].strip()
                    if path:
                        disallowed.add(path)
    except Exception as e:
        logger.warning("robots.txt fetch failed for %s: %s", domain, e)
    _ROBOTS_CACHE[domain] = disallowed
    return disallowed


def is_allowed(url: str) -> bool:
    """检查 URL 是否被 robots.txt 禁止。"""
    domain = _domain(url)
    path = urlparse(url).path
    disallowed = fetch_robots(domain)
    for rule in disallowed:
        # robots.txt 通配：rule 以 * 结尾或完全前缀匹配
        if rule == "/":
            return False
        if rule.endswith("*"):
            if path.startswith(rule[:-1]):
                return False
        elif path.startswith(rule):
            return False
    return True


# ---------------------------------------------------------------------------
# HTTP 抓取
# ---------------------------------------------------------------------------
def fetch(url: str, *, referer: str | None = None,
          sleep: float = SLEEP_SECONDS, retries: int = RETRY_TIMES,
          method: str = "GET", data: dict | None = None,
          headers: dict | None = None) -> httpx.Response:
    """带限速 + 退避重试的 HTTP 请求。"""
    h = dict(DEFAULT_HEADERS)
    if headers:
        h.update(headers)
    if referer:
        h["Referer"] = referer

    last_exc: Exception | None = None
    for i in range(retries):
        try:
            if method.upper() == "POST":
                r = httpx.post(url, headers=h, data=data, timeout=TIMEOUT,
                               follow_redirects=True)
            else:
                r = httpx.get(url, headers=h, timeout=TIMEOUT,
                              follow_redirects=True)
            r.raise_for_status()
            # 礼貌限速
            time.sleep(sleep + random.uniform(0, 0.5))
            return r
        except Exception as e:
            last_exc = e
            wait = sleep * (i + 1) * 1.5
            logger.warning("fetch %s failed (%s/%s): %s; retry in %.1fs",
                           url, i + 1, retries, e, wait)
            time.sleep(wait)
    raise RuntimeError(f"fetch failed after {retries} retries: {url}") from last_exc


def save_raw(url: str, content: bytes | str, kind: str = "html") -> Path:
    """原始响应落盘：data/raw/<kind>/<date>/<md5(url)>.kind"""
    day = datetime.now().strftime("%Y%m%d")
    h = hashlib.md5(url.encode("utf-8")).hexdigest()[:10]
    p = RAW_DIR / kind / day / f"{h}.{kind}"
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        p.write_text(content, encoding="utf-8")
    else:
        p.write_bytes(content)
    return p


def parse_html(text: str) -> BeautifulSoup:
    """统一的 HTML 解析入口（优先 lxml，缺失时回退 html.parser）。"""
    return BeautifulSoup(text, PARSER)


def get_soup(url: str, *, referer: str | None = None) -> BeautifulSoup:
    """抓取并解析为 BeautifulSoup，同时落盘原始 HTML。"""
    r = fetch(url, referer=referer)
    r.encoding = r.encoding or "utf-8"
    save_raw(url, r.content, "html")
    return parse_html(r.text)


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def to_int(s: str | None) -> int | None:
    """安全转 int，处理逗号、空串。"""
    if s is None:
        return None
    s = str(s).strip().replace(",", "").replace("，", "")
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def parse_score_cell(cell: str) -> tuple[int | None, int | None]:
    """
    解析一分一段表的"分数"单元格。
    - "710-750"      -> (710, 750)  区间（最高分段）
    - "690"          -> (690, 690)  单分
    - "535(特招线)"  -> (535, 535)  带批注（特招线/本科线等）
    - 含非数字        -> (None, None)
    """
    if cell is None:
        return None, None
    s = str(cell).strip()
    m = re.match(r"^(\d+)\s*[-–~]\s*(\d+)$", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"^(\d+)", s)          # 兼容 "535(特招线)" 这类带批注单元格
    if m:
        v = int(m.group(1))
        return v, v
    return None, None


def now_batch(prefix: str) -> str:
    """生成采集批次号。"""
    return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{prefix}"


# ---------------------------------------------------------------------------
# 批次名 / 科类 归一化（多个官方源命名不一致，入库前必须统一口径）
# ---------------------------------------------------------------------------
# 源站存在「普通本科批 / 本科批」「高职高专批 / 普通高职（专科）批 / 专科批」
# 等同一批次的不同写法；若不统一，同一事实会在库里产生两行。
_BATCH_ALIASES = {
    "本科批": "普通本科批",
    "普通本科批": "普通本科批",
    "本科一批": "本科一批",
    "本科二批": "本科二批",
    "特殊类型": "特殊类型",
    "特殊类型招生": "特殊类型",
    "特殊类型招生批": "特殊类型",
    "高职高专批": "高职高专批",
    "高职（专科）批": "高职高专批",
    "普通高职（专科）批": "高职高专批",
    "专科批": "高职高专批",
    "本科提前批": "本科提前批",
    "提前批": "本科提前批",
    "国家专项本科批": "国家专项本科批",
    "地方专项本科批": "地方专项本科批",
}


def normalize_batch(batch: str) -> str:
    """把各源不一致的批次名归一到统一口径（未命中则原样返回并去空白）。"""
    if not batch:
        return ""
    b = batch.strip().replace(" ", "")
    return _BATCH_ALIASES.get(b, b)


# 科类别名：理工/物理 归一为物理类，文史/历史 归一为历史类（老高考源偶有混用）
_SUBJECT_ALIASES = {
    "文科": "文科", "文史": "文科",
    "理科": "理科", "理工": "理科",
    "历史类": "历史类", "历史": "历史类",
    "物理类": "物理类", "物理": "物理类",
    "综合": "综合", "综合改革": "综合",
}


def normalize_subject(subject: str) -> str | None:
    """科类归一；无法识别返回 None。"""
    if not subject:
        return None
    s = subject.strip()
    if s in _SUBJECT_ALIASES:
        return _SUBJECT_ALIASES[s]
    for key, val in _SUBJECT_ALIASES.items():
        if key in s:
            return val
    return None
