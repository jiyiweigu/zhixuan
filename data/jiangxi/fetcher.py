"""
江西采集 · HTTP 抓取层。

职责：
1. 统一的浏览器请求头（config.HEADERS）
2. 遵守 robots.txt（Disallow 路径不抓）
3. 单站限速 >= 2s（含随机抖动），失败指数退避重试 3 次
4. 原始响应按 源域名/日期/hash 落盘，保证可复现、可追溯
5. 支持 PDF 下载（省考试院部分文件为 PDF）
"""
from __future__ import annotations

import hashlib
import logging
import random
import ssl
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from . import config


def _make_ssl_context():
    """
    自建 SSL 上下文：使用系统 CA（ssl.create_default_context + load_default_certs）。
    不依赖 certifi（避免部分精简/受损的 Python 运行时在 certifi.where() 处异常），
    同时保持证书校验开启。
    """
    try:
        ctx = ssl.create_default_context()
        try:
            ctx.load_default_certs()
        except Exception:  # noqa: BLE001
            pass
        return ctx
    except Exception as e:  # noqa: BLE001
        logger.warning("自建 SSL 上下文失败，回退 httpx 默认：%s", e)
        return True

logger = logging.getLogger("jx.fetcher")

# 解析器：优先 lxml，缺失回退内置
try:  # pragma: no cover
    import lxml  # noqa: F401
    _PARSER = "lxml"
except ImportError:  # pragma: no cover
    _PARSER = "html.parser"


class RobotsCache:
    """robots.txt 规则缓存（按域名）。"""

    def __init__(self, client: httpx.Client) -> None:
        self._cache: dict[str, list[str]] = {}
        self._client = client

    def _load(self, domain: str) -> list[str]:
        if domain in self._cache:
            return self._cache[domain]
        disallow: list[str] = []
        for scheme in ("https", "http"):
            try:
                r = self._client.get(f"{scheme}://{domain}/robots.txt",
                                     headers=config.HEADERS, timeout=15)
                if r.status_code == 200:
                    for line in r.text.splitlines():
                        line = line.strip()
                        if line.lower().startswith("disallow:"):
                            path = line.split(":", 1)[1].strip()
                            if path:
                                disallow.append(path)
                    break
            except Exception as e:  # noqa: BLE001
                logger.debug("robots.txt 获取失败 %s：%s", domain, e)
        self._cache[domain] = disallow
        return disallow

    def allowed(self, url: str) -> bool:
        domain = urlparse(url).netloc
        path = urlparse(url).path or "/"
        for rule in self._load(domain):
            if rule == "/":
                return False
            if rule.endswith("*") and path.startswith(rule[:-1]):
                return False
            if not rule.endswith("*") and path.startswith(rule):
                return False
        return True


class Fetcher:
    """带限速/重试/robots/落盘的 HTTP 客户端。"""

    def __init__(self, *, sleep: float = config.SLEEP_SECONDS,
                 retries: int = config.RETRY_TIMES, timeout: float = config.TIMEOUT,
                 respect_robots: bool = True, raw_dir: Path | None = None,
                 cache: bool = True) -> None:
        self.sleep = sleep
        self.retries = retries
        self.timeout = timeout
        self.respect_robots = respect_robots
        self.raw_dir = raw_dir or config.RAW_DIR
        self.cache = cache  # 当日已落盘的原始响应可直接复用（减少重复请求）
        self._client = httpx.Client(headers=config.HEADERS, timeout=timeout,
                                    follow_redirects=True,
                                    verify=_make_ssl_context())
        self.robots = RobotsCache(self._client)
        self.stats = {"ok": 0, "fail": 0, "blocked": 0}

    # -- 生命周期 -----------------------------------------------------------
    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- 核心抓取 -----------------------------------------------------------
    def get(self, url: str, *, referer: str | None = None,
            headers: dict | None = None, params: dict | None = None,
            allow_robots_block: bool = False) -> httpx.Response | None:
        """GET 一个 URL，失败返回 None（不抛异常，避免中断整条流水线）。"""
        if self.respect_robots and not allow_robots_block and not self.robots.allowed(url):
            logger.warning("robots.txt 禁止抓取，跳过：%s", url)
            self.stats["blocked"] += 1
            return None

        h = dict(config.HEADERS)
        if headers:
            h.update(headers)
        if referer:
            h["Referer"] = referer

        last_exc: Exception | None = None
        for i in range(self.retries):
            try:
                r = self._client.get(url, headers=h, params=params)
                r.raise_for_status()
                # 限速 + 随机抖动
                time.sleep(self.sleep + random.uniform(0, 0.5))
                self.stats["ok"] += 1
                return r
            except Exception as e:  # noqa: BLE001
                last_exc = e
                wait = self.sleep * (i + 1) * config.BACKOFF_BASE
                logger.warning("fetch 失败 (%d/%d) %s：%s；%.1fs 后重试",
                               i + 1, self.retries, url, e, wait)
                time.sleep(wait)
        logger.error("fetch 最终失败：%s（%s）", url, last_exc)
        self.stats["fail"] += 1
        return None

    def get_soup(self, url: str, *, referer: str | None = None) -> BeautifulSoup | None:
        """抓取并解析为 BeautifulSoup，同时落盘原始 HTML。"""
        p = self._cache_path(url, "html")
        if self.cache and p.exists() and p.stat().st_size > 0:
            text = p.read_text(encoding="utf-8", errors="ignore")
            logger.debug("命中本地缓存：%s", url)
        else:
            r = self.get(url, referer=referer)
            if r is None:
                return None
            self.save_raw(url, r.content, "html")
            # 政府站多为 UTF-8；若声明为 gb2312，httpx 会按声明解码
            try:
                text = r.text
            except Exception:  # noqa: BLE001
                text = r.content.decode("utf-8", errors="ignore")
        soup = BeautifulSoup(text, _PARSER)
        # 保留原始 HTML（未二次序列化），供解析内联 JSON 的 CMS 使用
        # （如 jxeea.cn 的 Hanweb：文章列表内嵌于 listData.articleList）。
        # 直接写 __dict__ 以绕过 bs4 Tag.__setattr__ 的受限赋值。
        try:
            soup.__dict__["_raw_html"] = text
        except Exception:  # noqa: BLE001
            pass
        return soup

    def get_html(self, url: str, *, referer: str | None = None) -> str:
        """抓取原始 HTML 文本（不解析），失败返回空串。"""
        p = self._cache_path(url, "html")
        if self.cache and p.exists() and p.stat().st_size > 0:
            return p.read_text(encoding="utf-8", errors="ignore")
        r = self.get(url, referer=referer)
        if r is None:
            return ""
        self.save_raw(url, r.content, "html")
        try:
            return r.text
        except Exception:  # noqa: BLE001
            return r.content.decode("utf-8", errors="ignore")

    def get_bytes(self, url: str, *, referer: str | None = None) -> bytes | None:
        """下载二进制（PDF 等）并落盘。"""
        ext = "pdf" if url.lower().endswith(".pdf") else "bin"
        p = self._cache_path(url, ext)
        if self.cache and p.exists() and p.stat().st_size > 0:
            logger.debug("命中本地缓存：%s", url)
            return p.read_bytes()
        r = self.get(url, referer=referer)
        if r is None:
            return None
        self.save_raw(url, r.content, ext)
        return r.content

    def _cache_path(self, url: str, kind: str) -> Path:
        day = datetime.now().strftime("%Y%m%d")
        h = hashlib.md5(url.encode("utf-8")).hexdigest()[:10]
        return self.raw_dir / kind / day / f"{h}.{kind}"

    # -- 落盘 ---------------------------------------------------------------
    def save_raw(self, url: str, content: bytes | str, kind: str = "html") -> Path:
        p = self._cache_path(url, kind)
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            p.write_text(content, encoding="utf-8")
        else:
            p.write_bytes(content)
        return p


# 便捷函数：一次性抓取（内部自建/关闭 Fetcher）
def fetch_soup(url: str, *, referer: str | None = None) -> BeautifulSoup | None:
    with Fetcher() as f:
        return f.get_soup(url, referer=referer)


def fetch_text(url: str, *, referer: str | None = None) -> str:
    with Fetcher() as f:
        r = f.get(url, referer=referer)
        return r.text if r is not None else ""
