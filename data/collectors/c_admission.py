"""
院校专业录取分 / 投档线采集器（school_major_score）。

数据源策略（多层兜底，确保数据可得）：
  1. 河南省阳光高考信息平台「院校子站·历年分数」（{code}.gaokao.haedu.cn）
     —— 服务端渲染，数据内嵌于页面 Vue 脚本（history_list），含：
        年份/批次/专业组代码/专业/计划数/最高最低平均分/选科要求
     —— 覆盖 2025 年新高考（院校专业组投档，group_code 关键）
  2. 种子数据 seeds/admission_scores.json —— 2023/2024 年官方公布投档线人工核验兜底

字段对齐 db/schema.sql 的 school_major_score 表：
  school_id, major_id(NULL), province, year, batch, subject_type,
  group_code, group_name, min_score, min_rank, plan_count, pathway_id(NULL)
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import httpx

from .base import RawRecord, DEFAULT_HEADERS, SLEEP_SECONDS, normalize_batch

logger = logging.getLogger(__name__)

SOURCE_NAME = "河南省阳光高考信息平台·院校子站（历年分数）"
BASE = "https://{code}.gaokao.haedu.cn"
SEEDS_PATH = Path(__file__).resolve().parents[1] / "seeds" / "admission_scores.json"
SCHOOL_JSON = Path(__file__).resolve().parents[2] / "data" / "output" / "school.json"

MAX_LIST_PAGES = 12        # 每校最多抓取的分页数
LIST_SLEEP = 1.2           # 子站限速（秒）


# ---------------------------------------------------------------------------
# 页面抓取
# ---------------------------------------------------------------------------
def _get(url: str) -> str:
    r = httpx.get(url, headers=DEFAULT_HEADERS, timeout=25, follow_redirects=True)
    r.encoding = r.encoding or "utf-8"
    r.raise_for_status()
    time.sleep(LIST_SLEEP)
    return r.text


def _get_cutoff_list_code(school_code: str) -> str | None:
    """从子站首页导航解析「历年分数」栏目码（各校不同，如 8382/2302）。"""
    try:
        html = _get(BASE.format(code=school_code) + "/")
    except Exception as e:
        logger.debug("subsite %s homepage failed: %s", school_code, e)
        return None
    m = re.search(
        rf"//{school_code}\.gaokao\.haedu\.cn/score/cutoff/list_(\d+)_1\.html", html
    )
    return m.group(1) if m else None


def _bracket_block(text: str, start: int, open_ch: str = "[", close_ch: str = "]") -> str:
    """从 start（指向 open_ch）起做括号配对，返回含括号的完整块。"""
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return ""


def _parse_history_list(html: str) -> list[dict]:
    """解析页面内嵌的 history_list: [...] 数据（Vue 内联，字段带 // 注释）。"""
    idx = html.find("history_list:")
    if idx < 0:
        return []
    block = _bracket_block(html, html.index("[", idx))
    if not block:
        return []
    rows: list[dict] = []
    for entry_src in re.findall(r"\{(.*?)\}", block, re.S):
        entry_src = re.sub(r"//[^\n]*", "", entry_src)          # 去注释
        pairs = re.findall(r"(\w+)\s*:\s*'([^']*)'", entry_src)  # 值均为单引号字符串
        if pairs:
            rows.append({k: v.strip() for k, v in pairs})
    return rows


def _normalize_subject(first_choice: str) -> str | None:
    t = (first_choice or "").strip()
    if "物理" in t or "理工" in t:
        return "物理类"
    if "历史" in t or "文史" in t:
        return "历史类"
    if "文科" in t:
        return "文科"
    if "理科" in t:
        return "理科"
    return None


def _to_int_or_none(s: str) -> int | None:
    s = (s or "").replace(",", "").strip()
    if not s or not re.fullmatch(r"\d+(\.\d+)?", s):
        return None
    return int(float(s))


def collect_school_cutoff(school_code: str, school_name_hint: str = "",
                          batch_no: str = "") -> list[RawRecord]:
    """采集单校「历年分数」（2025 专业组级明细）。"""
    list_code = _get_cutoff_list_code(school_code)
    if not list_code:
        logger.info("  %s 无 cutoff 栏目，跳过", school_code)
        return []

    records: list[RawRecord] = []
    row_no = 0
    seen_pages: set[int] = set()
    # 第 1 页 + 从分页链接发现后续页
    pending = [1]
    while pending:
        p = pending.pop(0)
        if p in seen_pages or p > MAX_LIST_PAGES:
            continue
        seen_pages.add(p)
        url = f"{BASE.format(code=school_code)}/score/cutoff/list_{list_code}_{p}.html"
        try:
            html = _get(url)
        except Exception as e:
            logger.warning("  %s page %d failed: %s", school_code, p, e)
            continue
        for href in re.findall(rf"list_{list_code}_(\d+)\.html", html):
            pending.append(int(href))
        entries = _parse_history_list(html)
        for e in entries:
            subject = _normalize_subject(e.get("first_choice", ""))
            min_score = _to_int_or_none(e.get("admission_score_min", ""))
            if not subject or min_score is None:
                continue
            row_no += 1
            group = e.get("major_group_code", "")
            records.append(RawRecord(
                data={
                    "school_code": school_code,
                    "school_name": e.get("school_name") or school_name_hint,
                    "province": "河南",
                    "year": int(e["year"]),
                    "batch": normalize_batch(e.get("batch") or "本科批"),
                    "subject_type": subject,
                    "group_code": group or None,
                    "group_name": f"专业组{group}" if group else None,
                    "major_code": e.get("major_enrollment_code") or None,
                    "major_name": e.get("major_name") or None,
                    "subject_require": e.get("major_optional_require") or None,
                    "min_score": min_score,
                    "max_score": _to_int_or_none(e.get("admission_score_max", "")),
                    "avg_score": e.get("admission_score_average") or None,
                    "min_rank": None,
                    "plan_count": _to_int_or_none(e.get("major_plan", "")),
                    "admission_num": _to_int_or_none(e.get("admission_num", "")),
                },
                source_name=SOURCE_NAME,
                source_url=url,
                year=int(e["year"]),
                doc_type="school_major_score",
                batch_no=batch_no,
                row_no=row_no,
            ))
    logger.info("  %s(%s): %d 条 (%d 页)", school_name_hint or school_code, school_code,
                len(records), len(seen_pages))
    return records


def load_school_codes(limit: int | None = None) -> list[tuple[str, str]]:
    """读取院校库（output/school.json）得到 (code, name)。"""
    codes: list[tuple[str, str]] = []
    if SCHOOL_JSON.exists():
        data = json.loads(SCHOOL_JSON.read_text(encoding="utf-8"))
        for s in data:
            code = (s.get("code") or "").strip()
            if re.fullmatch(r"\d{5}", code):
                codes.append((code, s.get("name", "")))
    codes = sorted(set(codes), key=lambda x: x[0])
    if limit:
        codes = codes[:limit]
    logger.info("院校子站采集目标：%d 所", len(codes))
    return codes


# ---------------------------------------------------------------------------
# 种子数据（2023/2024 官方公布投档线兜底）
# ---------------------------------------------------------------------------
SOURCE_NAME_HAEDU = "河南省教育考试院（平行投档分数线公布）"


def collect_from_seeds() -> list[RawRecord]:
    if not SEEDS_PATH.exists():
        logger.warning("admission seeds not found: %s", SEEDS_PATH)
        return []
    data = json.loads(SEEDS_PATH.read_text(encoding="utf-8"))
    records: list[RawRecord] = []
    for i, item in enumerate(data, start=1):
        rec = RawRecord(
            data={
                "school_name": item.get("school_name", ""),
                "school_code": item.get("school_code", ""),
                "province": "河南",
                "year": item["year"],
                "batch": item.get("batch", "普通本科批"),
                "subject_type": item["subject_type"],
                "group_code": item.get("group_code"),
                "group_name": item.get("group_name"),
                "major_name": item.get("major_name"),
                "min_score": item.get("min_score"),
                "min_rank": item.get("min_rank"),
                "avg_score": item.get("avg_score"),
                "plan_count": item.get("plan_count"),
            },
            source_name=item.get("source_name", SOURCE_NAME_HAEDU),
            source_url=item.get("source_url", "https://gaokao.haedu.cn/"),
            year=item["year"],
            doc_type="school_major_score",
            row_no=i,
        )
        records.append(rec)
    logger.info("admission seeds -> %d rows", len(records))
    return records


def collect_all(batch_no: str, limit: int | None = None,
                with_seeds: bool = True) -> list[RawRecord]:
    """录取分采集：子站在线明细 + 种子兜底。"""
    records: list[RawRecord] = []
    for code, name in load_school_codes(limit):
        try:
            records.extend(collect_school_cutoff(code, name, batch_no))
        except Exception as e:
            logger.error("cutoff %s failed: %s", code, e)
    if with_seeds:
        records.extend(collect_from_seeds())
    for r in records:
        if not r.batch_no:
            r.batch_no = batch_no
    return records
