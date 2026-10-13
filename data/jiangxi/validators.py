"""
江西采集 · 校验与去重层（数据可靠性的最后一道闸）。

对齐项目铁律：
  1. 来源三要素（source_name / source_url / year）缺一 → 拒收
  2. 业务规则校验（分数 0–750、位次 >0、科类合法、必填字段）
  3. 业务主键去重（同一事实只保留一条）
拒收记录写入 output/reject_report.json，可回溯 reject_reason。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from . import config

logger = logging.getLogger("jx.validators")

VALID_SUBJECTS = config.VALID_SUBJECTS
VALID_RULE_TYPES = {"户籍", "学籍", "区域", "成绩", "其他"}


@dataclass
class Record:
    """一条采集结果（带来源三要素）。"""
    data: dict
    source_name: str
    source_url: str
    year: int
    doc_type: str
    row_no: int = 0


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


# ---------------------------------------------------------------------------
# 业务校验器
# ---------------------------------------------------------------------------
def _v_source(rec: Record) -> str | None:
    if not rec.source_name or not rec.source_name.strip():
        return "缺少 source_name"
    if not rec.source_url or not rec.source_url.strip():
        return "缺少 source_url"
    if not rec.year or not (2000 <= rec.year <= 2100):
        return f"year 非法: {rec.year}"
    return None


def _v_batch_line(d: dict) -> str | None:
    if not d.get("batch"):
        return "batch 为空"
    if d.get("subject_type") not in VALID_SUBJECTS:
        return f"subject_type 非法: {d.get('subject_type')}"
    s = d.get("score")
    if not isinstance(s, int) or not (0 <= s <= 750):
        return f"score 越界: {s}"
    return None


def _v_segment(d: dict) -> str | None:
    s = d.get("score")
    if s is None or not (0 <= s <= 750):
        return f"score 越界: {s}"
    cum = d.get("cumulative_rank")
    if cum is None or cum <= 0:
        return f"cumulative_rank 非法: {cum}"
    if d.get("subject_type") not in VALID_SUBJECTS:
        return f"subject_type 非法: {d.get('subject_type')}"
    return None


def _v_stat(d: dict) -> str | None:
    if not d.get("total_registered"):
        return "total_registered 为空"
    return None


def _v_schedule(d: dict) -> str | None:
    if not d.get("stage"):
        return "stage 为空"
    if not (d.get("start_time") or d.get("end_time")):
        return "缺 start_time/end_time"
    return None


def _v_knowledge_doc(d: dict) -> str | None:
    if not d.get("title"):
        return "knowledge_doc 缺 title"
    if len(d.get("content") or "") < 50:
        return "knowledge_doc content < 50 字"
    return None


def _v_region(d: dict) -> str | None:
    if not d.get("pathway_name"):
        return "缺 pathway_name"
    # 地方专项为「全省农村地区，官方不划分县名单」，允许以 scope 代替县名
    if not d.get("county_name") and not d.get("scope"):
        return "缺 county_name/scope"
    return None


def _v_eligibility(d: dict) -> str | None:
    if not d.get("pathway_name"):
        return "缺 pathway_name"
    if not d.get("rule_desc"):
        return "缺 rule_desc"
    if d.get("rule_type") not in VALID_RULE_TYPES:
        return f"rule_type 非法: {d.get('rule_type')}"
    return None


def _v_pathway(d: dict) -> str | None:
    return None if d.get("name") else "缺 pathway name"


def _v_pathway_score(d: dict) -> str | None:
    if not d.get("pathway_name") or not d.get("school_name") or not d.get("year"):
        return "pathway_score 缺 pathway_name/school_name/year"
    ms = d.get("min_score")
    if ms is None:
        return "pathway_score 缺 min_score"
    if not (0 <= float(ms) <= 750):
        return f"min_score 越界: {ms}"
    return None


def _v_school(d: dict) -> str | None:
    return None if d.get("name") else "school name 为空"


def _v_school_major_score(d: dict) -> str | None:
    if not d.get("school_name"):
        return "缺 school_name"
    if d.get("subject_type") not in VALID_SUBJECTS:
        return f"subject_type 非法: {d.get('subject_type')}"
    ms = d.get("min_score")
    if ms is not None and not (0 <= float(ms) <= 750):
        return f"min_score 越界: {ms}"
    return None


def _v_major(d: dict) -> str | None:
    return None if d.get("name") else "major name 为空"


def _v_enrollment_rule(d: dict) -> str | None:
    if not d.get("school_name") or not d.get("year"):
        return "enrollment_rule 缺 school_name/year"
    if len(d.get("content") or "") < 100:
        return "enrollment_rule content < 100 字"
    return None


def _v_school_profile(d: dict) -> str | None:
    if not d.get("school_name"):
        return "缺 school_name"
    if not (d.get("intro") or d.get("website")):
        return "缺 intro/website"
    return None


def _v_discipline(d: dict) -> str | None:
    if not d.get("school_name") or not d.get("discipline_name") or not d.get("round"):
        return "discipline_eval 缺 school_name/discipline_name/round"
    return None


def _v_school_life(d: dict) -> str | None:
    if not d.get("school_name") or not d.get("category"):
        return "school_life 缺 school_name/category"
    if d.get("source_type") not in {"官方", "公开网络", "投稿"}:
        return "school_life source_type 非法"
    return None


def _v_supplement(d: dict) -> str | None:
    if not d.get("batch") or not d.get("school_name"):
        return "supplement 缺 batch/school_name"
    return None


def _v_group_admission(d: dict) -> str | None:
    if not d.get("school_name") or not d.get("year"):
        return "group_admission 缺 school_name/year"
    if d.get("subject_type") not in VALID_SUBJECTS:
        return f"group_admission subject_type 非法: {d.get('subject_type')}"
    if d.get("min_score") is None and d.get("filing_score") is None:
        return "group_admission 缺 min_score/filing_score"
    return None


def _v_subject_requirement(d: dict) -> str | None:
    if not d.get("school_name") or not d.get("subject_req"):
        return "subject_requirement 缺 school_name/subject_req"
    return None


def _v_school_plan(d: dict) -> str | None:
    if not d.get("school_name") or not d.get("major_name"):
        return "school_plan 缺 school_name/major_name"
    return None


def _v_plan_total(d: dict) -> str | None:
    if not d.get("year") or d.get("plan_total") is None:
        return "enroll_plan_total 缺 year/plan_total"
    return None


_VALIDATORS = {
    "batch_score_line": _v_batch_line,
    "score_segment": _v_segment,
    "province_stat": _v_stat,
    "schedule": _v_schedule,
    "knowledge_doc": _v_knowledge_doc,
    "pathway_region": _v_region,
    "pathway_eligibility": _v_eligibility,
    "pathway": _v_pathway,
    "pathway_score": _v_pathway_score,
    "school": _v_school,
    "school_major_score": _v_school_major_score,
    "group_admission": _v_group_admission,
    "subject_requirement": _v_subject_requirement,
    "major": _v_major,
    "enrollment_rule": _v_enrollment_rule,
    "school_profile": _v_school_profile,
    "discipline_eval": _v_discipline,
    "school_life": _v_school_life,
    "supplement": _v_supplement,
    "school_plan": _v_school_plan,
    "enroll_plan_total": _v_plan_total,
}


# ---------------------------------------------------------------------------
# 业务主键（去重依据，与 db/schema.sql 唯一键对齐）
# ---------------------------------------------------------------------------
def dedup_key(doc_type: str, row: dict) -> str:
    if doc_type == "batch_score_line":
        return f"bsl|{row.get('province')}|{row.get('year')}|{row.get('batch')}|{row.get('subject_type')}"
    if doc_type == "score_segment":
        return f"seg|{row.get('province')}|{row.get('year')}|{row.get('subject_type')}|{row.get('score')}"
    if doc_type == "province_stat":
        return f"stat|{row.get('year')}|{row.get('metric')}"
    if doc_type == "schedule":
        return f"sch|{row.get('year')}|{row.get('stage')}"
    if doc_type == "knowledge_doc":
        return f"doc|{row.get('title')}|{row.get('source_url')}"
    if doc_type == "pathway_region":
        return f"pr|{row.get('pathway_name')}|{row.get('county_code') or row.get('county_name')}"
    if doc_type == "pathway_eligibility":
        return f"pe|{row.get('pathway_name')}|{row.get('rule_type')}|{str(row.get('rule_desc'))[:30]}"
    if doc_type == "pathway":
        return f"pw|{row.get('name')}"
    if doc_type == "pathway_score":
        return (f"ps|{row.get('pathway_name')}|{row.get('school_name')}|{row.get('year')}|"
                f"{row.get('subject_type')}|{row.get('group_code')}")
    if doc_type == "school":
        return f"school|{row.get('code') or row.get('name')}"
    if doc_type == "school_major_score":
        return (f"sms|{row.get('school_name')}|{row.get('year')}|{row.get('batch')}|"
                f"{row.get('subject_type')}|{row.get('group_code')}|{row.get('major_name', '')}")
    if doc_type == "group_admission":
        return (f"ga|{row.get('school_name')}|{row.get('year')}|{row.get('batch')}|"
                f"{row.get('subject_type')}|{row.get('group_code')}|{row.get('admission_type', '')}")
    if doc_type == "subject_requirement":
        return (f"sr|{row.get('school_name')}|{row.get('year')}|{row.get('subject_type')}|"
                f"{row.get('group_name')}")
    if doc_type == "school_plan":
        return (f"sp2|{row.get('year')}|{row.get('batch')}|{row.get('round')}|"
                f"{row.get('subject_type')}|{row.get('school_name')}|{row.get('group_code')}|"
                f"{row.get('major_code') or row.get('major_name')}")
    if doc_type == "major":
        return f"major|{row.get('code') or row.get('name')}"
    if doc_type == "enrollment_rule":
        return f"rule|{row.get('school_name')}|{row.get('year')}"
    if doc_type == "school_profile":
        return f"sp|{row.get('school_name')}"
    if doc_type == "discipline_eval":
        return f"de|{row.get('school_name')}|{row.get('discipline_name')}|{row.get('round')}"
    if doc_type == "school_life":
        return f"sl|{row.get('school_name')}|{row.get('category')}|{str(row.get('content'))[:30]}"
    if doc_type == "supplement":
        return (f"sup|{row.get('year')}|{row.get('batch')}|{row.get('round')}|"
                f"{row.get('subject_type')}|{row.get('school_name')}|{row.get('group_code')}|"
                f"{row.get('major_code') or row.get('major_name')}")
    return f"{doc_type}|{row}"


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def clean(records: list[Record]) -> CleanResult:
    """来源三要素 → 业务校验 → 去重 → 输出。"""
    res = CleanResult()
    seen: set[str] = set()
    for rec in records:
        err = _v_source(rec)
        if err:
            res.rejected.append(_reject(rec, err))
            continue
        validator = _VALIDATORS.get(rec.doc_type)
        if validator:
            err = validator(rec.data)
            if err:
                res.rejected.append(_reject(rec, err))
                continue
        row = dict(rec.data)
        row["source_name"] = rec.source_name
        row["source_url"] = rec.source_url
        row["year"] = rec.year
        row["doc_type"] = rec.doc_type
        key = dedup_key(rec.doc_type, row)
        if key in seen:
            res.rejected.append(_reject(rec, f"重复记录（主键={key[:60]}）"))
            continue
        seen.add(key)
        res.valid.append(row)
    logger.info("clean: valid=%d rejected=%d", res.valid_count, res.rejected_count)
    return res


def _reject(rec: Record, reason: str) -> dict:
    return {
        "doc_type": rec.doc_type,
        "source_name": rec.source_name,
        "source_url": rec.source_url,
        "year": rec.year,
        "row_no": rec.row_no,
        "raw": rec.data,
        "reject_reason": reason,
    }
