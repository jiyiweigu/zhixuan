"""
升学途径字典采集器（pathway）+ 专业库采集（major，D-6）。

途径字典：26 类升学途径，来自 seeds/pathways.json（人工整理，对齐产品书 M2-1）。
专业库：掌上高考（中国教育在线）专业库静态 JSON 逐条枚举
    https://static-data.gaokao.cn/www/2.0/special/{id}/info.json
  - 含 专业代码/名称/门类/学位/学制/简介，本科高职均有（过滤高职码）
  - 失败回退 seeds 内置常见专业种子
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import httpx

from ..collectors.base import DEFAULT_HEADERS, RawRecord

logger = logging.getLogger(__name__)

SOURCE_PATHWAY = "教育部阳光高考平台·升学途径"
SOURCE_PATHWAY_URL = "https://gaokao.chsi.com.cn/"
PATHWAYS_PATH = Path(__file__).resolve().parents[1] / "seeds" / "pathways.json"

SOURCE_MAJOR = "教育部《普通高等学校本科专业目录》"
SOURCE_MAJOR_URL = "http://www.moe.gov.cn/"

# 专业库静态源
SOURCE_SPECIAL = "掌上高考（中国教育在线）·专业库静态数据"
SPECIAL_BASE = "https://static-data.gaokao.cn/www/2.0/special/{sid}/info.json"
SPECIAL_MAX_ID = 1400        # 枚举上界（1401+ 实测无本科专业）
SPECIAL_MISS_STOP = 60       # 连续无效 ID 达到即提前停止
SPECIAL_SLEEP = 0.15


def collect_pathways(batch_no: str) -> list[RawRecord]:
    """加载途径字典种子数据。"""
    if not PATHWAYS_PATH.exists():
        logger.error("pathways seed not found: %s", PATHWAYS_PATH)
        return []
    data = json.loads(PATHWAYS_PATH.read_text(encoding="utf-8"))
    records: list[RawRecord] = []
    for i, p in enumerate(data, start=1):
        records.append(RawRecord(
            data={
                "name": p["name"],
                "category": p.get("category", ""),
                "batch": p.get("batch", ""),
                "target_group": p.get("target_group", ""),
                "apply_time": p.get("apply_time", ""),
                "description": p.get("description", ""),
                "priority": p.get("priority", "P2"),
                "data_status": p.get("data_status", "schema_only"),
            },
            source_name=SOURCE_PATHWAY,
            source_url=SOURCE_PATHWAY_URL,
            year=2026,
            doc_type="pathway",
            batch_no=batch_no,
            row_no=i,
        ))
    logger.info("pathways -> %d rows", len(records))
    return records


def collect_majors(batch_no: str) -> list[RawRecord]:
    """
    专业库采集（D-6）：枚举掌上高考专业库静态 JSON（本科为主，
    过滤高职高专代码 4/5/6 开头），失败回退种子数据。
    """
    records = _collect_majors_online(batch_no)
    if not records:
        logger.warning("专业目录在线抓取为空，回退种子数据")
        records = _collect_majors_seed(batch_no)
    logger.info("majors -> %d rows", len(records))
    return records


def _first(v) -> str:
    if isinstance(v, list):
        return str(v[0]) if v else ""
    return str(v) if v is not None else ""


def _collect_majors_online(batch_no: str) -> list[RawRecord]:
    """枚举 static-data.gaokao.cn 专业详情静态 JSON。"""
    records: list[RawRecord] = []
    seen_codes: set[str] = set()
    miss_streak = 0
    for sid in range(1, SPECIAL_MAX_ID + 1):
        url = SPECIAL_BASE.format(sid=sid)
        try:
            r = httpx.get(url, headers=DEFAULT_HEADERS, timeout=15)
            d = r.json()
        except Exception as e:
            logger.debug("  special/%s fetch skip: %s", sid, e)
            miss_streak += 1
            if miss_streak >= SPECIAL_MISS_STOP:
                logger.info("  连续 %d 个无效 ID，提前结束（已采集 %d）",
                            SPECIAL_MISS_STOP, len(records))
                break
            continue
        time.sleep(SPECIAL_SLEEP)
        if str(d.get("code")) != "0000" or not isinstance(d.get("data"), dict):
            miss_streak += 1
            if miss_streak >= SPECIAL_MISS_STOP:
                logger.info("  连续 %d 个无效 ID，提前结束（已采集 %d）",
                            SPECIAL_MISS_STOP, len(records))
                break
            continue
        miss_streak = 0
        m = d["data"]
        code = str(m.get("code") or "").strip().upper()
        name = str(m.get("name") or "").strip()
        # 过滤高职高专（专业码 4/5/6 开头）与「专业类」类目码（如 0703 化学类）
        if not name or len(code) < 6 or not re.match(r"^[0-3]", code):
            continue
        if code in seen_codes:
            continue
        seen_codes.add(code)
        level1 = str(m.get("level1_name") or "").strip()
        records.append(RawRecord(
            data={
                "name": name,
                "code": code,
                "category": level1,
                "degree": _first(m.get("degree")),
                "intro": re.sub(r"\s+", " ", _first(m.get("is_what")))[:500],
            },
            source_name=SOURCE_SPECIAL,
            source_url=url,
            year=2026,
            doc_type="major",
            batch_no=batch_no,
            row_no=len(records) + 1,
        ))
    logger.info("  special 库枚举完成：%d 个本科专业", len(records))
    return records


MAJOR_SEED = [
    {"name": "计算机科学与技术", "code": "080901", "category": "工学/计算机类", "degree": "工学学士"},
    {"name": "软件工程", "code": "080902", "category": "工学/计算机类", "degree": "工学学士"},
    {"name": "人工智能", "code": "080717T", "category": "工学/电子信息类", "degree": "工学学士"},
    {"name": "数据科学与大数据技术", "code": "080910T", "category": "工学/计算机类", "degree": "工学学士"},
    {"name": "电子信息工程", "code": "080701", "category": "工学/电子信息类", "degree": "工学学士"},
    {"name": "通信工程", "code": "080703", "category": "工学/电子信息类", "degree": "工学学士"},
    {"name": "自动化", "code": "080801", "category": "工学/自动化类", "degree": "工学学士"},
    {"name": "机械工程", "code": "080201", "category": "工学/机械类", "degree": "工学学士"},
    {"name": "土木工程", "code": "081001", "category": "工学/土木类", "degree": "工学学士"},
    {"name": "临床医学", "code": "100201K", "category": "医学/临床医学类", "degree": "医学学士"},
    {"name": "口腔医学", "code": "100301K", "category": "医学/口腔医学类", "degree": "医学学士"},
    {"name": "药学", "code": "100701", "category": "医学/药学类", "degree": "理学学士"},
    {"name": "数学与应用数学", "code": "070101", "category": "理学/数学类", "degree": "理学学士"},
    {"name": "物理学", "code": "070201", "category": "理学/物理学类", "degree": "理学学士"},
    {"name": "化学", "code": "070301", "category": "理学/化学类", "degree": "理学学士"},
    {"name": "汉语言文学", "code": "050101", "category": "文学/中国语言文学类", "degree": "文学学士"},
    {"name": "英语", "code": "050201", "category": "文学/外国语言文学类", "degree": "文学学士"},
    {"name": "法学", "code": "030101K", "category": "法学/法学类", "degree": "法学学士"},
    {"name": "经济学", "code": "020101", "category": "经济学/经济学类", "degree": "经济学学士"},
    {"name": "金融学", "code": "020301K", "category": "经济学/金融学类", "degree": "经济学学士"},
    {"name": "工商管理", "code": "120201K", "category": "管理学/工商管理类", "degree": "管理学学士"},
    {"name": "会计学", "code": "120203K", "category": "管理学/工商管理类", "degree": "管理学学士"},
    {"name": "行政管理", "code": "120402", "category": "管理学/公共管理类", "degree": "管理学学士"},
    {"name": "教育学", "code": "040101", "category": "教育学/教育学类", "degree": "教育学学士"},
    {"name": "汉语言文学(师范)", "code": "050101", "category": "文学/中国语言文学类", "degree": "文学学士"},
    {"name": "数学与应用数学(师范)", "code": "070101", "category": "理学/数学类", "degree": "理学学士"},
    {"name": "英语(师范)", "code": "050201", "category": "文学/外国语言文学类", "degree": "文学学士"},
    {"name": "物理学(师范)", "code": "070201", "category": "理学/物理学类", "degree": "理学学士"},
    {"name": "化学(师范)", "code": "070301", "category": "理学/化学类", "degree": "理学学士"},
    {"name": "生物科学", "code": "071001", "category": "理学/生物科学类", "degree": "理学学士"},
]


def _collect_majors_seed(batch_no: str) -> list[RawRecord]:
    """专业库种子数据（在线源不可用时的兜底）。"""
    records: list[RawRecord] = []
    for i, m in enumerate(MAJOR_SEED, start=1):
        records.append(RawRecord(
            data={
                "name": m["name"],
                "code": m["code"],
                "category": m["category"],
                "degree": m["degree"],
                "intro": "",
            },
            source_name=SOURCE_MAJOR,
            source_url=SOURCE_MAJOR_URL,
            year=2026,
            doc_type="major",
            batch_no=batch_no,
            row_no=i,
        ))
    logger.info("majors(seed) -> %d rows", len(records))
    return records
