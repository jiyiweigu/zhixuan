"""
学科评估采集器（D-9 → discipline_eval）。

数据源（可解析的静态公开数据）：
  1) 教育部学位与研究生教育发展中心公布的第四轮学科评估结果（公开汇总）
     —— 以离线种子 files seeds/discipline_eval.json 落盘的结构化汇总为准
        （该结果是历史静态快照，官方仅以图片/PDF 公示，故以核实后的结构化种子承载，
         每条仍带 source_name/source_url/year，满足来源三要素铁律）；
  2) 掌上高考院校详情静态 JSON（static-data.gaokao.cn）中的「重点学科」字段，
     作为在线增量来源：https://static-data.gaokao.cn/www/2.0/school/{id}/info.json

设计：
  - 在线源为「公开网络」，种子源为「教育部学位中心（公开汇总）」；
  - 两源合并后按 (school_name, discipline_name, round) 去重，在线优先可信度标注；
  - 无数据即如实为空，不臆造。

doc_type = discipline_eval（与 db/schema.sql 的 discipline_eval 表对应）
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx

from .base import DEFAULT_HEADERS, RawRecord

logger = logging.getLogger(__name__)

SOURCE_NAME_SEED = "教育部学位与研究生教育发展中心·学科评估（公开汇总）"
SOURCE_NAME_ONLINE = "掌上高考（中国教育在线）·院校重点学科"
SEED_PATH = Path(__file__).resolve().parents[1] / "seeds" / "discipline_eval.json"
SCHOOL_JSON = Path(__file__).resolve().parents[2] / "data" / "output" / "school.json"
BATCH_SLEEP = 0.3

ROUND = "第四轮"
SEED_YEAR = 2017  # 第四轮学科评估公布年份

# 学科评估等级（合法枚举，用于清洗侧校验）
VALID_GRADES = {
    "A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-",
}


def _load_schools() -> list[dict]:
    if not SCHOOL_JSON.exists():
        return []
    return json.loads(SCHOOL_JSON.read_text(encoding="utf-8"))


def _school_site(school_id: int) -> dict:
    """在线增量：返回 {'school_name':..., 'subjects':[(学科, 等级)]}，失败返回 {}。"""
    url = f"https://static-data.gaokao.cn/www/2.0/school/{school_id}/info.json"
    try:
        r = httpx.get(url, headers=DEFAULT_HEADERS, timeout=20)
        r.raise_for_status()
        time.sleep(BATCH_SLEEP)
        d = r.json()
    except Exception as e:                              # noqa: BLE001
        logger.warning("  discipline school/%s info.json failed: %s", school_id, e)
        return {}
    if str(d.get("code")) != "0000":
        return {}
    data = d.get("data") or {}
    subjects: list[tuple[str, str]] = []
    # info.json 的学科字段形态不一，做宽松解析：key 含 "spe"/"subject"/"discipline"
    for key in ("special", "specialty", "spe", "subjects", "discipline"):
        val = data.get(key)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    nm = item.get("name") or item.get("special_name") or ""
                    gr = item.get("grade") or item.get("level") or ""
                    if nm:
                        subjects.append((str(nm), str(gr)))
    return {"school_name": data.get("name") or "", "subjects": subjects}


def collect_all(batch_no: str, limit: int | None = None) -> list[RawRecord]:
    """D-9 学科评估：种子 + 在线增量，合并去重。"""
    records: list[RawRecord] = []
    seen: set[tuple[str, str, str]] = set()
    row_no = 0

    # 1) 离线种子（权威结构化的第四轮结果）
    if SEED_PATH.exists():
        seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
        for item in seed:
            key = (item["school_name"], item["discipline_name"],
                   item.get("round", ROUND))
            if key in seen:
                continue
            seen.add(key)
            row_no += 1
            records.append(RawRecord(
                data={
                    "school_name": item["school_name"],
                    "discipline_name": item["discipline_name"],
                    "grade": item.get("grade", ""),
                    "round": item.get("round", ROUND),
                    "source_note": "教育部学位中心第四轮学科评估公开汇总（结构化种子）",
                },
                source_name=SOURCE_NAME_SEED,
                source_url=item.get("source_url",
                                    "http://www.cdgdc.edu.cn/xwyyjsjyxx/xkpgjg/"),
                year=item.get("year", SEED_YEAR),
                doc_type="discipline_eval",
                batch_no=batch_no, row_no=row_no,
            ))
        logger.info("discipline_eval seed -> %d 条", len(records))

    # 2) 在线增量：掌上高考院校静态数据的重点学科
    schools = _load_schools()
    if limit:
        schools = schools[:limit]
    for s in schools:
        sid = s.get("eol_school_id")
        if not sid:
            continue
        detail = _school_site(int(sid))
        for nm, gr in (detail.get("subjects") or []):
            key = (s.get("name", ""), nm, ROUND)
            if key in seen:
                continue
            seen.add(key)
            row_no += 1
            records.append(RawRecord(
                data={
                    "school_name": s.get("name", ""),
                    "discipline_name": nm,
                    "grade": gr if gr in VALID_GRADES else "",
                    "round": ROUND,
                    "source_note": "掌上高考院校库重点学科字段",
                },
                source_name=SOURCE_NAME_ONLINE,
                source_url=f"https://static-data.gaokao.cn/www/2.0/school/{sid}/info.json",
                year=2026,
                doc_type="discipline_eval",
                batch_no=batch_no, row_no=row_no,
            ))

    logger.info("discipline_eval -> %d 条（种子+在线）", len(records))
    return records
