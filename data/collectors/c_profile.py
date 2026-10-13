"""
院校画像采集器（D-8 → school_profile）+ 院校库富化（D-5 intro/website）。

数据源：掌上高考（中国教育在线）院校详情静态 JSON
    https://static-data.gaokao.cn/www/2.0/school/{school_id}/info.json
  - robots 允许；CDN 静态文件，稳定
  - 字段：简介 content、官网 school_site/site、建校 create_date、
    硕士点 num_master、博士点 num_doctor 等
  - 学费/住宿费该源未提供，留空（来源缺失如实记录）
  - 注：原 api.eol.cn/gkcx 动态接口已返回 code=1064（接口版本下线），弃用
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import httpx

from .base import DEFAULT_HEADERS, RawRecord

logger = logging.getLogger(__name__)

SOURCE_NAME = "掌上高考（中国教育在线）·院校库静态数据"
SCHOOL_JSON = Path(__file__).resolve().parents[2] / "data" / "output" / "school.json"

# eol school_id 映射（采集院校库时保存于 school.json 的 eol_school_id）
BATCH_SLEEP = 0.3


def _school_detail(school_id: int) -> dict:
    """院校详情：static-data.gaokao.cn 静态 JSON。"""
    url = f"https://static-data.gaokao.cn/www/2.0/school/{school_id}/info.json"
    r = httpx.get(url, headers=DEFAULT_HEADERS, timeout=20)
    r.raise_for_status()
    time.sleep(BATCH_SLEEP)
    d = r.json()
    if str(d.get("code")) != "0000":
        logger.warning("  school/%s info.json code=%s", school_id, d.get("code"))
        return {}
    return d.get("data") or {}


def _first(v) -> str:
    if isinstance(v, list):
        return str(v[0]) if v else ""
    return str(v) if v is not None else ""


def collect_all(batch_no: str, limit: int | None = None) -> list[RawRecord]:
    """院校画像：优先省级重点院校（有子站/分数数据的），字段缺失留空。"""
    if not SCHOOL_JSON.exists():
        logger.error("school.json 不存在，请先运行 --only school")
        return []
    data = json.loads(SCHOOL_JSON.read_text(encoding="utf-8"))
    # 排序：985/211 优先，其余按代码
    data.sort(key=lambda s: (not s.get("is_985"), not s.get("is_211"), s.get("code", "")))
    if limit:
        data = data[:limit]

    records: list[RawRecord] = []
    row_no = 0
    for s in data:
        sid = s.get("eol_school_id")
        code = s.get("code", "")
        name = s.get("name", "")
        if not sid:
            continue
        try:
            d = _school_detail(int(sid))
        except Exception as e:
            logger.warning("  profile %s failed: %s", name, e)
            continue
        if not d:
            continue
        intro = re.sub(r"\s+", " ", _first(d.get("content")) or _first(d.get("remark")))
        fy = d.get("create_date")
        try:
            fy_int = int(re.sub(r"\D", "", str(fy))[:4]) if fy else None
            if fy_int and not (1850 <= fy_int <= 2030):
                fy_int = None
        except Exception:
            fy_int = None
        row_no += 1
        records.append(RawRecord(
            data={
                "school_code": code,
                "school_name": name,
                "website": _first(d.get("school_site")) or _first(d.get("site")) or "",
                "intro": intro[:2000],
                "established_year": fy_int,
                "tuition_range": _first(d.get("coop_money")) or "",
                "accommodation_fee": "",
                "faculty_count": None,
                "master_points": _first(d.get("num_master")),
                "phd_points": _first(d.get("num_doctor")),
                "source_note": "掌上高考院校库静态数据（static-data.gaokao.cn，公开数据）；学费字段为中外合作学费参考，住宿费源未提供",
            },
            source_name=SOURCE_NAME,
            source_url=f"https://static-data.gaokao.cn/www/2.0/school/{sid}/info.json",
            year=2026,
            doc_type="school_profile",
            batch_no=batch_no,
            row_no=row_no,
        ))
    logger.info("school_profile -> %d 条", len(records))
    return records
