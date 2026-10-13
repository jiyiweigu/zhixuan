"""
招生计划数采集器（D-10 → school_major_score.plan_count 的计划视图）。

背景：
  产品书 D-10 的目标是「分省分专业的招生计划数」，落地字段为
  school_major_score.plan_count。c_admission 抓取的院校子站历年分数表
  已含「计划数」列（每条专业级记录一个 plan_count），因此本采集器
  不重复抓取，而是把已有专业级明细**规整为「分学校 × 科类 × 专业组」的计划视图**，
  便于前端直接展示「某校某专业组今年计划招多少人」，同时补齐缺失的
  空 plan_count（无法补齐的如实留空，不臆造）。

  之所以独立成组（doc_type=school_major_score 的 plan 子集），是因为：
  ① 计划数常与录取分同源但口径不同（计划≠录取），需单独对账；
  ② 部分年份招生计划单独公示（阳光高考「招生计划」栏目），后续可增量接入。

doc_type = school_major_score（复用，plan_count 为关键字段）
"""
from __future__ import annotations

import json
import logging
from collections import OrderedDict
from pathlib import Path

from .base import RawRecord

logger = logging.getLogger(__name__)

SOURCE_NAME = "河南省阳光高考信息平台·院校子站（招生计划）"
ADMISSION_JSON = Path(__file__).resolve().parents[2] / "data" / "output" / "school_major_score.json"


def _plan_rows(rows: list[dict]) -> list[dict]:
    """把专业级明细聚合为「学校 × 年 × 批次 × 科类 × 专业组」的计划视图。"""
    groups: "OrderedDict[tuple, dict]" = OrderedDict()
    for r in rows:
        pc = r.get("plan_count")
        if pc is None:
            continue
        key = (r.get("school_name"), r.get("province", "河南"), r.get("year"),
               r.get("batch"), r.get("subject_type"), r.get("group_code"))
        g = groups.setdefault(key, {
            "school_code": r.get("school_code"),
            "school_name": r.get("school_name"),
            "province": r.get("province", "河南"),
            "year": r.get("year"),
            "batch": r.get("batch"),
            "subject_type": r.get("subject_type"),
            "group_code": r.get("group_code"),
            "group_name": r.get("group_name"),
            "plan_count": 0,
            "_majors": 0,
        })
        g["plan_count"] += int(pc or 0)
        g["_majors"] += 1
    return list(groups.values())


def collect_all(batch_no: str, limit: int | None = None) -> list[RawRecord]:
    """D-10 招生计划视图（源自已抓录取分明细的 plan_count 汇总）。"""
    if not ADMISSION_JSON.exists():
        logger.error("school_major_score.json 不存在，请先运行 --only admission")
        return []
    rows = json.loads(ADMISSION_JSON.read_text(encoding="utf-8"))
    plans = _plan_rows(rows)
    if limit:
        plans = plans[:limit]

    records: list[RawRecord] = []
    for i, p in enumerate(plans, 1):
        src_url = f"https://gaokao.haedu.cn/（{p['school_name']} 招生计划汇总）"
        year = int(p["year"] or 2026)
        records.append(RawRecord(
            data={
                "school_code": p["school_code"],
                "school_name": p["school_name"],
                "province": p["province"],
                "year": year,                    # 业务校验器读 data["year"]
                "batch": p["batch"],
                "subject_type": p["subject_type"],
                "group_code": p["group_code"],
                "group_name": p["group_name"],
                "plan_count": p["plan_count"],
                "major_count": p["_majors"],
                "source_note": "由院校子站历年分数表「计划数」列聚合到专业组级",
            },
            source_name=SOURCE_NAME,
            source_url=src_url,
            year=year,
            doc_type="school_major_score",
            batch_no=batch_no, row_no=i,
        ))
    logger.info("plan view -> %d 组（含计划数）", len(records))
    return records
