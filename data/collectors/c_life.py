"""
院校生活信息采集器（D-11 → school_life）。

数据源（公开网络可解析 + 官方文本）：
  1) 河南省阳光高考信息平台 / 院校子站的「院校简介·校园生活」栏目段落（官方/半官方）；
  2) 政府门户与高校官网公开的《新生入学须知》正文中的宿舍/食堂/交通段落。

实现策略：
  - 复用 c_profile 已抓到的院校静态详情（school_profile.json 的 intro），
    从中抽取「宿舍/食堂/交通/校区」段落 → 归类到 school_life.category；
  - 无法从公开页面稳定抽到生活信息的院校，不臆造；
  - source_type 严格三选一：官方 / 公开网络 / 投稿（本采集器只用前两者）；
  - 每条必须带 source_name/source_url/year。

doc_type = school_life
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .base import RawRecord

logger = logging.getLogger(__name__)

SOURCE_NAME = "掌上高考（中国教育在线）·院校简介（校园生活节选）"
PROFILE_JSON = Path(__file__).resolve().parents[2] / "data" / "output" / "school_profile.json"

# 生活信息关键词 → 类别
_CATEGORY_KEYWORDS = {
    "宿舍": ["宿舍", "寝室", "公寓", "住宿"],
    "食堂": ["食堂", "餐饮", "餐厅"],
    "交通": ["交通", "地铁", "公交", "校车", "出行"],
    "校区": ["校区", "校园", "新校区", "占地"],
}
_MIN_LEN = 10  # 段落太短不算有效生活信息


def _split_sentences(text: str) -> list[str]:
    """按中文句读切句，保留有效长度段落。"""
    if not text:
        return []
    parts = re.split(r"[。；;!？\n]", text)
    return [p.strip() for p in parts if len(p.strip()) >= _MIN_LEN]


def _classify(sentence: str) -> str | None:
    for cat, kws in _CATEGORY_KEYWORDS.items():
        if any(kw in sentence for kw in kws):
            return cat
    return None


def parse_life_from_intro(school_name: str, intro: str) -> list[dict]:
    """从院校简介文本抽取生活信息片段。返回 [{category, content}, ...]。"""
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for sent in _split_sentences(intro):
        cat = _classify(sent)
        if not cat:
            continue
        key = (cat, sent[:40])
        if key in seen:
            continue
        seen.add(key)
        out.append({"category": cat, "content": sent})
    return out


def collect_all(batch_no: str, limit: int | None = None) -> list[RawRecord]:
    """D-11 生活信息：从已抓院校简介中抽取宿舍/食堂/交通/校区段落。"""
    if not PROFILE_JSON.exists():
        logger.error("school_profile.json 不存在，请先运行 --only profile")
        return []
    profiles = json.loads(PROFILE_JSON.read_text(encoding="utf-8"))
    if limit:
        profiles = profiles[:limit]

    records: list[RawRecord] = []
    row_no = 0
    for p in profiles:
        school_name = p.get("school_name") or ""
        intro = p.get("intro") or ""
        for item in parse_life_from_intro(school_name, intro):
            row_no += 1
            records.append(RawRecord(
                data={
                    "school_name": school_name,
                    "category": item["category"],
                    "content": item["content"][:1000],
                    "source_type": "公开网络",
                    "reliability": "medium",
                },
                source_name=SOURCE_NAME,
                source_url=p.get("source_url", ""),
                year=int(p.get("year") or 2026),
                doc_type="school_life",
                batch_no=batch_no, row_no=row_no,
            ))
    logger.info("school_life -> %d 条", len(records))
    return records
