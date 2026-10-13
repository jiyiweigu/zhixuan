"""
三大专项报考资格条件采集器（D-13 → pathway_eligibility）+ 关键时间节点（D-15）。

规则条文整理自官方政策文件（来源三要素逐条登记）：
  - 《河南省2025年普通高校招生考试和录取工作实施方案》（河南省教育厅，2025-01）
  - 《河南省2025年普通高等学校招生工作规定》（河南省教育考试院，2025-04）
  - 教育部高校专项/地方专项实施文件（阳光高考平台）

rule_type 枚举对齐 schema：户籍|学籍|区域|成绩|其他
params 为结构化参数（喂给规则引擎），如 {"household":"农村","years":3}
"""
from __future__ import annotations

import logging
from pathlib import Path

from .base import RawRecord

logger = logging.getLogger(__name__)

SRC_PLAN_2025 = "河南省教育厅《河南省2025年普通高校招生考试和录取工作实施方案》"
URL_PLAN_2025 = "http://m.jyt.henan.gov.cn/2025/01-24/3117467.html"
SRC_REG_2025 = "河南省教育考试院《河南省2025年普通高等学校招生工作规定》"
URL_REG_2025 = "https://gaokao.haedu.cn/501/553/2025/0428/137929.html"
SRC_CHSI = "河南省教育考试院《河南省实施国家专项计划和高校专项计划县域名单》"
URL_CHSI = "https://www.haeea.cn/a/202504/43485_edf25549.shtml"

# (pathway_name, rule_type, rule_desc, params, year, source_name, source_url)
RULES: list[tuple[str, str, str, dict, int, str, str]] = [
    # ---- 国家专项计划（38 县）----
    ("国家专项计划", "户籍",
     "本人具有实施区域当地连续3年以上户籍，其父亲或母亲或法定监护人具有当地户籍",
     {"household": "农村", "years": 3, "guardian": True}, 2025, SRC_PLAN_2025, URL_PLAN_2025),
    ("国家专项计划", "学籍",
     "本人具有户籍所在县高中连续3年学籍并实际就读",
     {"school_years": 3, "actual_study": True}, 2025, SRC_PLAN_2025, URL_PLAN_2025),
    ("国家专项计划", "区域",
     "考生户籍在河南省国家专项计划实施区域（38个县）内",
     {"county_list": "pathway_region:国家专项计划"}, 2025, SRC_PLAN_2025, URL_PLAN_2025),
    ("国家专项计划", "成绩",
     "符合当年河南省普通高校招生统一考试报名条件，高考成绩达到相应批次录取控制分数线",
     {"batch_line_required": True}, 2025, SRC_PLAN_2025, URL_PLAN_2025),
    # ---- 地方专项计划（实施区域=河南省农村地区，不划分具体县）----
    ("地方专项计划", "户籍",
     "考生本人及父亲或母亲或法定监护人户籍地在河南省农村，本人具有当地连续3年以上户籍",
     {"household": "农村", "years": 3}, 2025, SRC_PLAN_2025, URL_PLAN_2025),
    ("地方专项计划", "学籍",
     "考生具有河南省普通高中连续3年学籍并实际就读",
     {"school_years": 3, "actual_study": True}, 2025, SRC_PLAN_2025, URL_PLAN_2025),
    ("地方专项计划", "区域",
     "考生户籍地为河南省农村地区（官方不划分具体实施县名单，以农村户籍为准）",
     {"scope": "全省农村", "household": "农村"}, 2025,
     SRC_PLAN_2025, URL_PLAN_2025),
    # ---- 高校专项计划 ----
    ("高校专项计划", "户籍",
     "考生本人及父亲或母亲或法定监护人户籍地在实施区域的农村，本人具有当地连续3年以上户籍",
     {"household": "农村", "years": 3}, 2025, SRC_CHSI, URL_CHSI),
    ("高校专项计划", "学籍",
     "考生具有户籍所在县高中连续3年学籍并实际就读",
     {"school_years": 3, "actual_study": True}, 2025, SRC_CHSI, URL_CHSI),
    ("高校专项计划", "区域",
     "考生户籍在河南省高校专项计划实施区域县（市、区）内",
     {"county_list": "pathway_region:高校专项计划"}, 2025, SRC_CHSI, URL_CHSI),
    ("高校专项计划", "其他",
     "考生须在教育部阳光高考平台完成报名申请，并按高校要求提交材料，通过高校资格审核",
     {"apply_channel": "阳光高考平台", "review": "高校审核"}, 2025, SRC_CHSI, URL_CHSI),
    # ---- 资格申报通用 ----
    ("国家专项计划", "其他",
     "考生须在规定时间登录河南省普通高校招生考生服务平台完成专项计划资格申报",
     {"apply_channel": "考生服务平台", "deadline": "高考报名时同步申报"}, 2025,
     SRC_REG_2025, URL_REG_2025),
    ("地方专项计划", "其他",
     "填报地方专项计划志愿的考生须已通过资格审核，志愿设在本科批内",
     {"batch": "本科批", "audit_required": True}, 2025, SRC_REG_2025, URL_REG_2025),
]

# D-15 关键时间节点（apply_time 原样文本）
TIMELINE: list[tuple[str, str, int, str, str]] = [
    ("国家专项计划", "4月底前：完成专项计划资格申报；6月25日：公布成绩与分数线；"
     "6月26日-28日：填报本科提前批、国家专项本科批志愿", 2025, SRC_REG_2025, URL_REG_2025),
    ("地方专项计划", "6月30日-7月2日：填报本科批志愿（含地方专项）；随本科批平行志愿投档录取",
     2025, SRC_REG_2025, URL_REG_2025),
    ("高校专项计划", "4月25日前：在阳光高考平台完成报名；5月底前：高校完成审核并公示；"
     "高考后出分前：部分高校组织考核；6月30日-7月2日：填报志愿", 2025, SRC_CHSI, URL_CHSI),
]


def collect_all(batch_no: str) -> list[RawRecord]:
    """专项资格规则 + 时间节点 -> pathway_eligibility。"""
    records: list[RawRecord] = []
    row_no = 0
    import json as _json
    for pathway_name, rule_type, rule_desc, params, year, src, url in RULES:
        row_no += 1
        records.append(RawRecord(
            data={
                "pathway_name": pathway_name, "province": "河南",
                "rule_type": rule_type, "rule_desc": rule_desc,
                "params": _json.dumps(params, ensure_ascii=False),
            },
            source_name=src, source_url=url, year=year,
            doc_type="pathway_eligibility", batch_no=batch_no, row_no=row_no,
        ))
    for pathway_name, apply_time, year, src, url in TIMELINE:
        row_no += 1
        records.append(RawRecord(
            data={
                "pathway_name": pathway_name, "apply_time": apply_time,
            },
            source_name=src, source_url=url, year=year,
            doc_type="pathway_time", batch_no=batch_no, row_no=row_no,
        ))
    logger.info("pathway_eligibility -> %d rules + %d timeline",
                len(RULES), len(TIMELINE))
    return records
