"""
清洗与校验模块。

对齐《开发产品书_智选志愿》铁律：
  - 所有事实表必须含 source_name / source_url / year，缺一拒收
  - 科类枚举：文科|理科|历史类|物理类|综合
  - 分数范围：0–750
  - 年份范围：2000–2100
  - 去重：按业务主键

输出：清洗后的记录列表 + 拒收报告（reject_reason）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..collectors.base import RawRecord

logger = logging.getLogger(__name__)

VALID_SUBJECTS = {"文科", "理科", "历史类", "物理类", "综合"}
VALID_PRIORITIES = {"P0", "P1", "P2"}
VALID_DATA_STATUS = {"available", "schema_only"}


@dataclass
class CleanResult:
    valid: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)

    @property
    def valid_count(self) -> int:
        return len(self.valid)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)


def _check_source_triplet(rec: RawRecord) -> str | None:
    """校验来源三要素。返回缺失字段名或 None。"""
    if not rec.source_name or not rec.source_name.strip():
        return "缺少 source_name"
    if not rec.source_url or not rec.source_url.strip():
        return "缺少 source_url"
    if not rec.year or rec.year < 2000 or rec.year > 2100:
        return f"year 非法: {rec.year}"
    return None


def _validate_score_segment(data: dict) -> str | None:
    score = data.get("score")
    cum = data.get("cumulative_rank")
    if score is None or not (0 <= score <= 750):
        return f"score 越界: {score}"
    if cum is None or cum <= 0:
        return f"cumulative_rank 非法: {cum}"
    if data.get("subject_type") not in VALID_SUBJECTS:
        return f"subject_type 非法: {data.get('subject_type')}"
    return None


def _validate_school(data: dict) -> str | None:
    if not data.get("name"):
        return "school name 为空"
    return None


def _validate_school_major_score(data: dict) -> str | None:
    ms = data.get("min_score")
    if ms is not None and not (0 <= ms <= 750):
        return f"min_score 越界: {ms}"
    if data.get("subject_type") not in VALID_SUBJECTS:
        return f"subject_type 非法: {data.get('subject_type')}"
    if not data.get("year"):
        return "year 为空"
    return None


_DOC_VALIDATORS = {
    "score_segment": _validate_score_segment,
    "school": _validate_school,
    "school_major_score": _validate_school_major_score,
    "pathway": lambda d: None if d.get("name") else "pathway name 为空",
    "pathway_region": lambda d: None if d.get("county_name") else "county_name 为空",
    "major": lambda d: None if d.get("name") else "major name 为空",
    "knowledge_doc": lambda d: (
        None if (d.get("title") and len(d.get("content") or "") >= 50)
        else "knowledge_doc 需 title 且 content>=50 字"
    ),
    "knowledge_chunk": lambda d: (
        None if (d.get("doc_title") and len(d.get("content") or "") >= 20)
        else "knowledge_chunk 需 doc_title 且 content>=20 字"
    ),
    "batch_score_line": lambda d: (
        None if (d.get("batch") and d.get("subject_type") in VALID_SUBJECTS
                 and isinstance(d.get("score"), int) and 0 <= d["score"] <= 750)
        else "batch_score_line 字段非法"
    ),
    "pathway_time": lambda d: (
        None if (d.get("pathway_name") and d.get("apply_time"))
        else "pathway_time 需 pathway_name + apply_time"
    ),
    "enrollment_rule": lambda d: (
        None if (d.get("school_name") and d.get("year")
                 and len(d.get("content") or "") >= 100)
        else "enrollment_rule 需 school_name/year/content>=100 字"
    ),
    "pathway_eligibility": lambda d: (
        None if (d.get("pathway_name") and d.get("rule_desc")
                 and d.get("rule_type") in {"户籍", "学籍", "区域", "成绩", "其他"})
        else "pathway_eligibility 字段非法"
    ),
    "school_profile": lambda d: (
        None if d.get("school_name") and (d.get("intro") or d.get("website"))
        else "school_profile 需 school_name + intro/website"
    ),
    # D-4 专项计划录取分：必须能定位「哪条途径 × 哪所学校 × 哪一年 × 多少分」
    "pathway_score": lambda d: _validate_pathway_score(d),
    # D-9 学科评估：学校 + 学科 + 等级/轮次
    "discipline_eval": lambda d: (
        None if (d.get("school_name") and d.get("discipline_name")
                 and d.get("round"))
        else "discipline_eval 需 school_name + discipline_name + round"
    ),
    # D-11 生活信息：学校 + 类别 + 正文 + 来源类型合法
    "school_life": lambda d: (
        None if (d.get("school_name") and d.get("category")
                 and len(d.get("content") or "") >= 10
                 and d.get("source_type") in {"官方", "公开网络", "投稿"})
        else "school_life 需 school_name/category/content>=10/source_type"
    ),
}


def _validate_pathway_score(data: dict) -> str | None:
    if not data.get("pathway_name"):
        return "pathway_score 缺 pathway_name"
    if not data.get("school_name"):
        return "pathway_score 缺 school_name"
    if not data.get("year"):
        return "pathway_score 缺 year"
    ms = data.get("min_score")
    if ms is None:
        return "pathway_score 缺 min_score"
    if not (0 <= float(ms) <= 750):
        return f"pathway_score min_score 越界: {ms}"
    subj = data.get("subject_type")
    if subj is not None and subj not in VALID_SUBJECTS:
        return f"pathway_score subject_type 非法: {subj}"
    xms = data.get("max_score")
    if xms is not None and not (0 <= float(xms) <= 750):
        return f"pathway_score max_score 越界: {xms}"
    return None


def clean_records(records: list[RawRecord]) -> CleanResult:
    """
    清洗 + 校验全部记录。
    流程：来源三要素 → 业务字段校验 → 去重 → 输出。
    """
    result = CleanResult()
    seen_keys: dict[str, str] = {}  # dedup key -> source_url

    for rec in records:
        # 1. 来源三要素
        src_err = _check_source_triplet(rec)
        if src_err:
            result.rejected.append(_reject(rec, src_err))
            continue

        # 2. 业务字段校验
        validator = _DOC_VALIDATORS.get(rec.doc_type)
        if validator:
            biz_err = validator(rec.data)
            if biz_err:
                result.rejected.append(_reject(rec, biz_err))
                continue

        # 3. 构造输出行（带来源三要素）
        #    注意：doc_type 统一为**管道类型**（score_segment / knowledge_doc ...），
        #    供文件命名与入库分发；文档自身的语义类型放 doc_category，避免被覆盖。
        row = dict(rec.data)
        row["source_name"] = rec.source_name
        row["source_url"] = rec.source_url
        row["year"] = rec.year
        row["doc_type"] = rec.doc_type

        # 4. 去重（按业务主键）
        key = _dedup_key(rec.doc_type, row)
        if key in seen_keys:
            result.rejected.append(_reject(rec, f"重复记录 (主键={key[:60]})"))
            continue
        seen_keys[key] = rec.source_url
        result.valid.append(row)

    logger.info(
        "clean: valid=%d rejected=%d (total=%d)",
        result.valid_count, result.rejected_count, len(records),
    )
    return result


def _dedup_key(doc_type: str, row: dict) -> str:
    """按业务主键构造去重键。"""
    if doc_type == "score_segment":
        return f"{row['province']}|{row['year']}|{row['subject_type']}|{row['score']}"
    if doc_type == "school":
        return f"school|{row.get('code') or row['name']}"
    if doc_type == "school_major_score":
        return (
            f"{row.get('school_name')}|{row['year']}|{row['batch']}|"
            f"{row['subject_type']}|{row.get('group_code')}|{row.get('major_name','')}"
        )
    if doc_type == "pathway":
        return f"pathway|{row['name']}"
    if doc_type == "pathway_region":
        return f"{row['pathway_name']}|{row['county_code'] or row['county_name']}"
    if doc_type == "major":
        return f"major|{row.get('code') or row['name']}"
    if doc_type == "knowledge_doc":
        return f"doc|{row.get('title')}|{row.get('source_url', '')}"
    if doc_type == "knowledge_chunk":
        return f"chunk|{row.get('doc_title')}|{row.get('chunk_index')}"
    if doc_type == "batch_score_line":
        return (f"bsl|{row.get('province', '河南')}|{row['year']}|"
                f"{row['batch']}|{row['subject_type']}")
    if doc_type == "pathway_time":
        return f"pt|{row.get('pathway_name')}"
    if doc_type == "enrollment_rule":
        return f"rule|{row.get('school_name')}|{row.get('year')}"
    if doc_type == "pathway_eligibility":
        return f"pe|{row.get('pathway_name')}|{row.get('rule_type')}|{row.get('rule_desc', '')[:30]}"
    if doc_type == "school_profile":
        return f"sp|{row.get('school_name')}"
    if doc_type == "pathway_score":
        return (f"ps|{row.get('pathway_name')}|{row.get('school_name')}|"
                f"{row.get('year')}|{row.get('subject_type')}|{row.get('group_code')}")
    if doc_type == "discipline_eval":
        return (f"de|{row.get('school_name')}|{row.get('discipline_name')}|"
                f"{row.get('round')}")
    if doc_type == "school_life":
        return (f"sl|{row.get('school_name')}|{row.get('category')}|"
                f"{row.get('content', '')[:30]}")
    return f"{doc_type}|{row}"


def _reject(rec: RawRecord, reason: str) -> dict:
    return {
        "doc_type": rec.doc_type,
        "source_name": rec.source_name,
        "source_url": rec.source_url,
        "year": rec.year,
        "row_no": rec.row_no,
        "raw": rec.data,
        "reject_reason": reason,
    }
