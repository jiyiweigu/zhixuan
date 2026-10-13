"""
招生章程采集器（D-7 → enrollment_rule + D-17 → knowledge_doc）。

数据源：河南省阳光高考信息平台「院校子站·招生政策-招生简章」
  https://{code}.gaokao.haedu.cn/policy/brochure/list_{col}_1.html
  - 列表页服务端渲染（静态 HTML 链接）
  - 文章正文在 #contentContainer（纯文本，实测可用）

产出：
  - enrollment_rule：学校/年份/全文 + 选科/体检/外语要求正则抽取
  - knowledge_doc（doc_type=章程）：全文供 RAG 问答溯源
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import httpx

from .base import RawRecord, DEFAULT_HEADERS, save_raw, parse_html

logger = logging.getLogger(__name__)

SOURCE_NAME = "河南省阳光高考信息平台·院校子站（招生章程）"
BASE = "https://{code}.gaokao.haedu.cn"
LIST_SLEEP = 1.2
MAX_SCHOOLS = 200
MAX_ARTICLES_PER_SCHOOL = 3          # 每校最多采的章程篇数（按年份倒序）
TARGET_YEARS = {2023, 2024, 2025}

# 学校清单（与 c_admission 共用 output/school.json）
SCHOOL_JSON = Path(__file__).resolve().parents[2] / "data" / "output" / "school.json"


def _get(url: str) -> str:
    r = httpx.get(url, headers=DEFAULT_HEADERS, timeout=25, follow_redirects=True)
    r.encoding = r.encoding or "utf-8"
    r.raise_for_status()
    time.sleep(LIST_SLEEP)
    return r.text


def _brochure_list_url(school_code: str) -> str | None:
    """从子站首页导航解析「招生简章」栏目码。"""
    try:
        html = _get(BASE.format(code=school_code) + "/")
    except Exception:
        return None
    m = re.search(
        rf"//{school_code}\.gaokao\.haedu\.cn/policy/brochure/list_(\d+)_1\.html",
        html,
    )
    return m.group(1) if m else None


def _list_articles(school_code: str, col: str) -> list[tuple[str, str]]:
    """章程列表：[(title, url)]，含分页（最多 3 页）。"""
    arts: list[tuple[str, str]] = []
    seen: set[str] = set()
    for p in range(1, 4):
        url = f"{BASE.format(code=school_code)}/policy/brochure/list_{col}_{p}.html"
        try:
            html = _get(url)
        except Exception:
            break
        for u, t in re.findall(
            r'href="([^"]+/policy/brochure/\d{4}/\d{4}/\d+\.html)"[^>]*>\s*(?:<[^>]+>\s*)*([^<]{4,80})',
            html,
        ):
            t = t.strip()
            if u.startswith("//"):
                u = "https:" + u
            if t not in seen and "章程" in t or "简章" in t:
                seen.add(u)
                arts.append((t, u))
        if f"list_{col}_{p + 1}.html" not in html:
            break
    return arts


def _extract_year(title: str) -> int | None:
    m = re.search(r"(20\d{2})年", title)
    return int(m.group(1)) if m else None


def _extract_article(url: str) -> str:
    """章程正文：#contentContainer 纯文本。"""
    html = _get(url)
    soup = parse_html(html)
    cc = soup.find(id="contentContainer")
    if cc:
        return cc.get_text("\n", strip=True)
    return ""


def _pick_fields(content: str) -> dict:
    """从章程全文抽取 选科/体检/外语 要求要点（正则要点句）。"""
    def grab(pats: list[str], window: int = 60) -> str:
        for pat in pats:
            m = re.search(pat, content)
            if m:
                s = max(0, m.start() - 10)
                return content[s:m.start() + window].replace("\n", " ").strip()
        return ""

    return {
        "subject_req": grab([r"选考科目要求", r"选科要求", r"思想政治[^。]{0,30}必选"]),
        "health_req": grab([r"体检[^。]{0,40}", r"《普通高等学校招生体检工作指导意见"]),
        "foreign_lang_req": grab([r"(英语|外语)[^.。]{0,40}语种", r"只招英语", r"外语语种"]),
    }


def collect_all(batch_no: str, limit: int | None = MAX_SCHOOLS) -> list[RawRecord]:
    """采集各校招生章程（2023–2025 优先）。"""
    import json
    codes: list[tuple[str, str]] = []
    if SCHOOL_JSON.exists():
        data = json.loads(SCHOOL_JSON.read_text(encoding="utf-8"))
        for s in data:
            code = (s.get("code") or "").strip()
            if re.fullmatch(r"\d{5}", code):
                codes.append((code, s.get("name", "")))
    codes = sorted(set(codes), key=lambda x: x[0])[:limit]
    logger.info("章程采集目标：%d 所院校", len(codes))

    records: list[RawRecord] = []
    row_no = 0
    ok_schools = 0
    for code, name in codes:
        try:
            col = _brochure_list_url(code)
            if not col:
                continue
            arts = _list_articles(code, col)
            # 只保留本科招生章程，年份倒序，限量
            picked = []
            for t, u in arts:
                y = _extract_year(t)
                if y in TARGET_YEARS and re.search(r"本科招生章程|招生章程", t):
                    picked.append((y, t, u))
            picked.sort(key=lambda x: x[0], reverse=True)
            for y, t, u in picked[:MAX_ARTICLES_PER_SCHOOL]:
                content = _extract_article(u)
                if len(content) < 100:
                    continue
                ok_schools += 1
                fields = _pick_fields(content)
                row_no += 1
                records.append(RawRecord(
                    data={
                        "school_code": code, "school_name": name,
                        "year": y, "title": t, "content": content, **fields,
                    },
                    source_name=f"{name}招生章程（河南省阳光高考信息平台转载）",
                    source_url=u, year=y,
                    doc_type="enrollment_rule", batch_no=batch_no, row_no=row_no,
                ))
                # D-17：章程全文 -> knowledge_doc
                row_no += 1
                records.append(RawRecord(
                    data={
                        "title": t, "doc_category": "章程", "province": "河南",
                        "pathway_name": "", "content": content,
                        "char_count": len(content),
                    },
                    source_name=SOURCE_NAME, source_url=u, year=y,
                    doc_type="knowledge_doc", batch_no=batch_no, row_no=row_no,
                ))
                save_raw(u, content, "txt")
                logger.info("  章程 %s %d: %d 字", name, y, len(content))
        except Exception as e:
            logger.warning("  章程 %s failed: %s", code, e)
    logger.info("enrollment_rule -> %d 条（覆盖 %d 校次）", len(records) // 2, ok_schools)
    return records
