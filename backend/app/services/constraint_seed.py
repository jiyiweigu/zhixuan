"""报考约束规则的最小演示种子（供 ② 打通链路；正式数据由 ③ 号按 7.6 入库）。

用途：在 ③ 号真实数据到位前，让 6.2.6–6.2.9 与「志愿表风险体检」全链路可跑通，
并覆盖验收口径点名的场景（色弱→医学类被拦、未填体检不得判通过、规则缺失→3001）。

数据规模（v1.1 只做 P0 两省本科批，与《执行计划》第 1 节一致）：

- 省份模板：河南 2026 本科批 48 组 / 河南 2026 提前批 64「专业+院校」/ 江西 2026 本科批 45 组
- 专业：14 个代表性专业，覆盖物化绑定、必选政治、不限三种选科形态
- 选科要求：随专业写入（含 all / any 两种逻辑）
- 身体条件：色觉 / 视力 / 乙肝 / 身高 / 听力，覆盖 reject 与 not_suitable 两级

**幂等**：按唯一键判断已存在即跳过；真实数据入库后同键记录会被覆盖或并存（按 year 区分）。

**诚实性（契约 8.1 / 8.7）**：本模块**不写入** ``rule_dataset_status``，也不写
``major_tuition`` / ``admission_requirement``。于是接口的 ``data_status`` 由
``app/services/constraints.py`` 按"表里是否真的有记录"如实推导：

- 省份模板 / 选科 / 身体条件有记录 → ``available``；
- 学费与章程要求无记录 → 校验接口整体降级为 ``partial``，8.6 把这两个规则集
  列入 ``missing_rule_sets``，学费只给 ``major.tuition`` 的演示值并显式标注
  "演示值，非官方收费标准"。

真实规则由 ③ 号按 7.6 / 8.7 导入后再由管理端把状态推进到 ``available``。

运行时执行：``cd backend && .venv/Scripts/python.exe -m app.services.constraint_seed``
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base_data import Major
from app.models.constants import (
    BATCH_CODE_EARLY,
    BATCH_CODE_UG,
    EXAM_TYPE_NORMAL,
    province_code_of,
)
from app.models.constraints import (
    PhysicalRestriction,
    ProvinceExamRule,
    SubjectRequirement,
)
from app.models.source import Source

# 官方来源（演示用真实机构与真实站点，年份为规则年份）
SOURCE_HAEEA = {
    "source_name": "河南省教育考试院",
    "source_url": "https://www.haeea.cn/",
    "year": 2026,
    "source_type": "official",
}
SOURCE_JXEEA = {
    "source_name": "江西省教育考试院",
    "source_url": "http://www.jxeea.cn/",
    "year": 2026,
    "source_type": "official",
}
SOURCE_MOE_PHYSICAL = {
    "source_name": "《普通高等学校招生体检工作指导意见》",
    "source_url": "http://www.moe.gov.cn/",
    "year": 2026,
    "source_type": "official",
}

# 专业：name, category, first_subject, secondary, logic, tuition, ownership
MAJORS: tuple[tuple[str, str, str, list[str], str, int, str], ...] = (
    ("临床医学", "医学类", "物理", ["化学"], "all", 5800, "公办"),
    ("口腔医学", "医学类", "物理", ["化学"], "all", 5800, "公办"),
    ("计算机科学与技术", "计算机类", "物理", ["化学"], "all", 5800, "公办"),
    ("软件工程", "计算机类", "物理", ["化学"], "all", 5800, "公办"),
    ("化学工程与工艺", "化工与制药类", "物理", ["化学"], "all", 5500, "公办"),
    ("飞行技术", "交通运输类", "物理", ["化学"], "any", 5800, "公办"),
    ("航海技术", "交通运输类", "物理", [], "all", 5800, "公办"),
    ("法学", "法学类", "不限", [], "all", 5200, "公办"),
    ("汉语言文学", "中国语言文学类", "不限", [], "all", 5000, "公办"),
    ("公安学类", "公安学类", "不限", ["政治"], "all", 5000, "公办"),
    ("学前教育", "教育学类", "不限", [], "all", 4800, "公办"),
    ("动画", "戏剧与影视学类", "不限", [], "all", 12000, "民办"),
    ("美术学", "美术学类", "不限", [], "all", 12000, "民办"),
    ("计算机科学与技术(中外合作)", "计算机类", "物理", ["化学"], "all", 58000, "中外合作"),
)

# 体检限制：condition, threshold, major_category, level, detail
PHYSICAL_RULES: tuple[tuple[str, str, str, str, str], ...] = (
    ("色弱", "不限", "医学类", "reject",
     "色弱不能录取医学类各专业（依据《普通高等学校招生体检工作指导意见》第二条第一款）"),
    ("色弱", "不限", "化工与制药类", "not_suitable",
     "色弱不宜就读化工与制药类等专业（合格不宜，非不予录取）"),
    ("色盲", "不限", "美术学类", "reject",
     "色盲不能录取美术学类各专业"),
    ("色盲", "不限", "戏剧与影视学类", "reject",
     "色盲不能录取动画、戏剧影视美术设计等专业"),
    ("裸眼视力", "<5.0", "交通运输类", "reject",
     "裸眼视力任何一眼低于 5.0 者，不宜录取飞行技术、航海技术等专业"),
    ("乙肝", "携带", "教育学类", "reject",
     "乙肝表面抗原携带者不能录取学前教育等专业"),
    ("身高", "<170", "公安学类", "reject",
     "男性身高低于 170cm 不宜报考公安类院校（女生 160cm）"),
    ("听力", "异常", "医学类", "not_suitable",
     "听力异常不宜就读医学类（合格不宜）"),
)

# 省份模板：province, province_code, year, batch, batch_code, exam_type, mode,
#            volunteer_count, majors_per_group, has_adjust, admit_method, ratio,
#            tie_rule, mutex_groups, collect_count, source
#
# batch_code 取值与数据侧 data/dictionaries/province-exam-rule.json 同源
# （河南「普通本科批」/江西「本科批次」经 batch_code 归一后不再区分）。
PROVINCE_RULES: tuple[dict[str, Any], ...] = (
    {
        "province": "河南", "province_code": "41", "year": 2026,
        "batch": "本科批", "batch_code": BATCH_CODE_UG, "exam_type": EXAM_TYPE_NORMAL,
        "mode": "group",
        "volunteer_count": 48, "majors_per_group": 6, "has_adjust": True,
        "admit_method": "parallel", "ratio": "1:1",
        "tie_rule": "总分相同依次比较语文、数学、外语单科成绩",
        "mutex_groups": [], "collect_count": None, "_source": SOURCE_HAEEA,
    },
    {
        "province": "河南", "province_code": "41", "year": 2026,
        "batch": "提前批", "batch_code": BATCH_CODE_EARLY, "exam_type": EXAM_TYPE_NORMAL,
        "mode": "major_school",
        "volunteer_count": 64, "majors_per_group": None, "has_adjust": False,
        "admit_method": "parallel", "ratio": "1:1",
        "tie_rule": "总分相同依次比较语文、数学、外语单科成绩",
        "mutex_groups": ["提前批各类之间互不兼报", "艺术类与体育类不能兼报"],
        "collect_count": None, "_source": SOURCE_HAEEA,
    },
    {
        "province": "江西", "province_code": "36", "year": 2026,
        "batch": "本科批", "batch_code": BATCH_CODE_UG, "exam_type": EXAM_TYPE_NORMAL,
        "mode": "group",
        "volunteer_count": 45, "majors_per_group": 6, "has_adjust": True,
        "admit_method": "parallel", "ratio": "1:1",
        "tie_rule": "总分相同依次比较语文、数学、外语单科成绩",
        "mutex_groups": [], "collect_count": None, "_source": SOURCE_JXEEA,
    },
)


def _ensure_source(db: Session, citation: dict[str, Any]) -> Source:
    existing = db.scalar(
        select(Source).where(
            Source.source_name == citation["source_name"],
            Source.source_url == citation["source_url"],
            Source.year == citation["year"],
        )
    )
    if existing is not None:
        return existing
    source = Source(**citation)
    db.add(source)
    db.flush()
    return source


def _ensure_majors(db: Session, source: Source) -> dict[str, Major]:
    """写入/取回演示专业（含学费、办学性质等 v1.1 字段）。"""
    result: dict[str, Major] = {}
    for name, category, first_subject, secondary, logic, tuition, ownership in MAJORS:
        row = db.scalar(select(Major).where(Major.name == name, Major.category == category))
        if row is None:
            row = Major(
                name=name, category=category, tuition=tuition, ownership=ownership,
                degree="学士", first_class="", duration="四年",
            )
            db.add(row)
            db.flush()
        else:
            row.tuition = tuition
            row.ownership = ownership
        result[name] = row
    return result


def _ensure_requirements(db: Session, source: Source, majors: dict[str, Major], province: str, year: int) -> int:
    created = 0
    for name, category, first_subject, secondary, logic, _tuition, _ownership in MAJORS:
        major = majors.get(name)
        if major is None:
            continue
        exists = db.scalar(
            select(SubjectRequirement).where(
                SubjectRequirement.province == province,
                SubjectRequirement.year == year,
                SubjectRequirement.major_id == major.id,
            )
        )
        if exists is not None:
            continue
        db.add(
            SubjectRequirement(
                province_code=province_code_of(province),
                province=province, year=year, batch="本科批",
                major_id=major.id, first_subject=first_subject,
                secondary_subjects=list(secondary), logic=logic, source_id=source.id,
            )
        )
        created += 1
    return created


def _ensure_physical(db: Session, source: Source, province: str, year: int) -> int:
    created = 0
    for condition, threshold, category, level, detail in PHYSICAL_RULES:
        exists = db.scalar(
            select(PhysicalRestriction).where(
                PhysicalRestriction.condition == condition,
                PhysicalRestriction.major_category == category,
                PhysicalRestriction.year == year,
                PhysicalRestriction.province == province,
            )
        )
        if exists is not None:
            continue
        db.add(
            PhysicalRestriction(
                condition=condition, threshold=threshold, major_category=category,
                level=level, detail=detail,
                province_code=province_code_of(province), province=province, year=year,
                source_id=source.id,
            )
        )
        created += 1
    return created


def seed_demo(db: Session) -> dict[str, int]:
    """幂等写入演示规则数据，返回各表新增条数。"""
    haeea = _ensure_source(db, SOURCE_HAEEA)
    jxeea = _ensure_source(db, SOURCE_JXEEA)
    moe = _ensure_source(db, SOURCE_MOE_PHYSICAL)

    majors = _ensure_majors(db, haeea)

    province_created = 0
    for item in PROVINCE_RULES:
        payload = dict(item)
        source = _ensure_source(db, payload.pop("_source"))
        exists = db.scalar(
            select(ProvinceExamRule).where(
                ProvinceExamRule.province == payload["province"],
                ProvinceExamRule.year == payload["year"],
                ProvinceExamRule.batch == payload["batch"],
            )
        )
        if exists is not None:
            continue
        db.add(ProvinceExamRule(source_id=source.id, **payload))
        province_created += 1

    req_created = _ensure_requirements(db, haeea, majors, "河南", 2026)
    req_created += _ensure_requirements(db, jxeea, majors, "江西", 2026)
    phys_created = _ensure_physical(db, moe, "河南", 2026)
    phys_created += _ensure_physical(db, moe, "江西", 2026)

    db.commit()
    return {
        "majors": len(majors),
        "province_rules": province_created,
        "subject_requirements": req_created,
        "physical_restrictions": phys_created,
    }


def main() -> int:
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        stats = seed_demo(db)
    print("演示规则数据已写入：", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
