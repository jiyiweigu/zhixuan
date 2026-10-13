"""
院校库采集器（school）+ 专业库采集器（major）。

数据源：中国教育在线 · 掌上高考 API（api.eol.cn/gkcx）
  - robots.txt 允许
  - 结构化 JSON，字段规范
  - 来源类型：公开网络，可靠性 high

字段映射（对齐 db/schema.sql 的 school 表）：
  name        -> name
  code_enroll -> code（取前 5 位国标码）
  province_name -> province
  city_name   -> city
  level_name  -> level（本科/专科）
  type_name   -> type（综合类/理工类/师范类...）
  nature_name -> ownership（公办/民办）
  school_id   -> eol_school_id（外部关联，用于录取分采集）
"""
from __future__ import annotations

import logging
import time

import httpx

from .base import RawRecord, DEFAULT_HEADERS, SLEEP_SECONDS

logger = logging.getLogger(__name__)

SOURCE_NAME = "中国教育在线·掌上高考"
PROVINCE_ID = "41"  # 河南省

API_URL = "https://api.eol.cn/gkcx/api/"
API_PARAMS = {
    "access_token": "",
    "uri": "apidata/api/gk/school/lists",
    "signsafe": "",
    "province_id": PROVINCE_ID,
}

LEVEL_MAP = {"本科": "本科", "专科": "专科", "本科/专科": "本科"}
OWNERSHIP_MAP = {"公办": "公办", "民办": "民办", "中外合作办学": "中外合作办学"}


def _api_get(page: int, size: int = 100) -> dict:
    params = dict(API_PARAMS)
    params.update({"page": str(page), "size": str(size)})
    r = httpx.get(API_URL, params=params, headers=DEFAULT_HEADERS, timeout=20)
    r.raise_for_status()
    time.sleep(SLEEP_SECONDS)
    return r.json()


def _extract_code(code_enroll: str) -> str:
    """国标院校代码取前 5 位。"""
    if not code_enroll:
        return ""
    digits = "".join(ch for ch in code_enroll if ch.isdigit())
    return digits[:5] if digits else ""


def collect_schools(batch_no: str) -> list[RawRecord]:
    """采集河南全部院校。"""
    logger.info("collect schools from eol API (province_id=%s)", PROVINCE_ID)
    records: list[RawRecord] = []
    page = 1
    total = None
    while True:
        data = _api_get(page)
        items = data.get("data", {}).get("item", [])
        if total is None:
            total = int(data.get("data", {}).get("numFound", 0))
            logger.info("  total schools: %d", total)
        if not items:
            break
        for item in items:
            rec = RawRecord(
                data={
                    "name": item.get("name", ""),
                    "code": _extract_code(item.get("code_enroll", "")),
                    "province": item.get("province_name", "河南"),
                    "city": item.get("city_name", ""),
                    "level": item.get("level_name", ""),
                    "type": item.get("type_name", ""),
                    "ownership": item.get("nature_name", ""),
                    "website": "",
                    "intro": "",
                    "eol_school_id": item.get("school_id"),
                    "dual_class": item.get("dual_class_name", ""),
                    "is_211": item.get("f211") == "1",
                    "is_985": item.get("f985") == "1",
                },
                source_name=SOURCE_NAME,
                source_url=f"https://www.gaokao.cn/school/{item.get('school_id')}",
                year=2026,
                doc_type="school",
                batch_no=batch_no,
            )
            records.append(rec)
        if len(records) >= total:
            break
        page += 1
    logger.info("  collected %d schools", len(records))
    return records


def collect_school_detail(school_id: int) -> dict | None:
    """（可选）采集单校详情：官网、简介。供后续富化。"""
    params = dict(API_PARAMS)
    params.pop("province_id", None)
    params.update({"uri": "apidata/api/gk/school/info", "school_id": str(school_id)})
    try:
        r = httpx.get(API_URL, params=params, headers=DEFAULT_HEADERS, timeout=20)
        r.raise_for_status()
        time.sleep(SLEEP_SECONDS)
        d = r.json()
        return d.get("data", {})
    except Exception as e:
        logger.warning("school detail %d failed: %s", school_id, e)
        return None
