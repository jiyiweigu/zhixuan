"""
三大专项实施区域县名单采集器（pathway_region）。

数据源：河南省教育考试院《河南省实施国家专项计划和高校专项计划县域名单》
（https://www.haeea.cn/a/202504/43485_edf25549.shtml）。
数据整理为 seeds/pathway_regions.json，含：
  - 国家专项计划：38 县（26 原集中连片特困县 + 12 原国家级扶贫开发重点县）
  - 高校专项计划：53 县（38 国家专项县 + 15 原省定扶贫开发重点县）
  - 地方专项计划：实施区域为**河南省农村地区**，官方不划分具体县名单
    （户籍在河南农村即可），故 counties 为空、以 scope 字段记录口径。

注意：不要把 53 县名单挂到"地方专项"下——这是常见误读。地方专项的判定
依据是"农村户籍"而非"县名单"。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from ..collectors.base import RawRecord

logger = logging.getLogger(__name__)

SOURCE_NAME = "河南省教育厅（专项计划实施区域名单）"
SOURCE_URL = "https://jyt.henan.gov.cn/"
SEEDS_PATH = Path(__file__).resolve().parents[1] / "seeds" / "pathway_regions.json"


def collect_regions(batch_no: str) -> list[RawRecord]:
    """加载三大专项县名单种子数据。"""
    if not SEEDS_PATH.exists():
        logger.error("pathway_regions seed not found: %s", SEEDS_PATH)
        return []
    data = json.loads(SEEDS_PATH.read_text(encoding="utf-8"))
    records: list[RawRecord] = []
    row_no = 0
    for pathway_name, info in data.items():
        if pathway_name.startswith("_"):     # 跳过 _meta 元信息
            continue
        province = info.get("province", "河南")
        for county in info.get("counties", []):
            row_no += 1
            records.append(RawRecord(
                data={
                    "pathway_name": pathway_name,
                    "province": province,
                    "county_name": county["county_name"],
                    "county_code": county.get("county_code", ""),
                },
                source_name=SOURCE_NAME,
                source_url=SOURCE_URL,
                year=2026,
                doc_type="pathway_region",
                batch_no=batch_no,
                row_no=row_no,
            ))
    logger.info("pathway regions -> %d rows", len(records))
    return records
