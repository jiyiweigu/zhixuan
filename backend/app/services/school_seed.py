"""院校/专业演示数据入库（tasks.md 7.1、7.2 的本地种子）。

职责单一：把 ``app/data/schools/schools_demo.json`` 写入库表，供本地开发与测试使用。
真实数据由 ③ 号按 tasks.md 2.5 采集入库；两者写入同一批表，
因此服务层（app/services/schools.py、majors.py）不需要区分数据来源。

约束：
- **幂等**：按业务键去重（school/major 按 name，score 按五元组，profile 按 school_id，
  life 按 school+category+content，source 按三要素），重复执行只补新增，不产生重复行；
- **缺来源不入库**：来源校验在加载阶段完成（app/core/dataset.py），本模块不额外放宽；
- 只写入，不删除。需要清空重来请直接丢弃测试库或重建迁移。

手工执行（把演示数据灌进本地开发库）：
    cd backend && .venv/Scripts/python.exe -m app.services.school_seed
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import dataset
from app.models.base_data import Major, School, SchoolMajorScore
from app.models.school_profile import SchoolLife, SchoolProfile
from app.models.source import Source

TABLES = ("source", "school", "major", "score", "profile", "life")


def ensure_source(db: Session, citation: dict[str, Any]) -> Source:
    """按来源三要素取回或新建 source 行。"""
    existing = db.scalar(
        select(Source).where(
            Source.source_name == citation["source_name"],
            Source.source_url == citation["source_url"],
            Source.year == citation["year"],
        )
    )
    if existing is not None:
        return existing
    source = Source(
        source_name=str(citation["source_name"]),
        source_url=str(citation["source_url"]),
        year=int(citation["year"]),
        source_type=citation.get("source_type"),
    )
    db.add(source)
    db.flush()
    return source


def seed_demo(db: Session) -> dict[str, int]:
    """把演示数据集幂等写入库，返回各表新增行数。"""
    payload = dataset.load_schools_demo()
    created = {table: 0 for table in TABLES}

    # —— 来源 ——
    source_by_key: dict[str, Source] = {}
    for item in payload.get("sources") or []:
        before = db.scalar(select(Source.id).where(Source.source_name == item["source_name"]))
        source = ensure_source(db, item)
        source_by_key[str(item["key"])] = source
        if before is None:
            created["source"] += 1

    # —— 院校 ——
    school_by_key: dict[str, School] = {}
    for item in payload.get("schools") or []:
        school = db.scalar(select(School).where(School.name == item["name"]))
        if school is None:
            school = School(
                name=item["name"],
                code=item.get("code"),
                province=item.get("province") or "",
                city=item.get("city") or "",
                level=item.get("level") or "",
                type=item.get("type") or "",
                ownership=item.get("ownership") or "",
                website=item.get("website") or "",
                intro=item.get("intro") or "",
            )
            db.add(school)
            db.flush()
            created["school"] += 1
        school_by_key[str(item["key"])] = school

    # —— 专业 ——
    major_by_key: dict[str, Major] = {}
    for item in payload.get("majors") or []:
        major = db.scalar(select(Major).where(Major.name == item["name"]))
        if major is None:
            major = Major(
                name=item["name"],
                code=item.get("code"),
                category=item.get("category") or "",
                first_class=item.get("first_class") or "",
                degree=item.get("degree") or "",
            )
            db.add(major)
            db.flush()
            created["major"] += 1
        major_by_key[str(item["key"])] = major

    # —— 录取分 ——
    for item in payload.get("scores") or []:
        school = school_by_key[str(item["school"])]
        major = major_by_key[str(item["major"])]
        exists = db.scalar(
            select(SchoolMajorScore.id).where(
                SchoolMajorScore.school_id == school.id,
                SchoolMajorScore.major_id == major.id,
                SchoolMajorScore.province == item["province"],
                SchoolMajorScore.year == int(item["year"]),
                SchoolMajorScore.batch == (item.get("batch") or ""),
                SchoolMajorScore.subject_type == (item.get("subject_type") or ""),
            )
        )
        if exists is not None:
            continue
        db.add(
            SchoolMajorScore(
                school_id=school.id,
                major_id=major.id,
                province=item["province"],
                year=int(item["year"]),
                batch=item.get("batch") or "",
                subject_type=item.get("subject_type") or "",
                min_score=item.get("min_score"),
                min_rank=item.get("min_rank"),
                avg_score=item.get("avg_score"),
                plan_count=item.get("plan_count"),
                source_id=source_by_key[str(item["source"])].id,
            )
        )
        created["score"] += 1

    # —— 院校画像 ——
    for item in payload.get("profiles") or []:
        school = school_by_key[str(item["school"])]
        if db.scalar(select(SchoolProfile.id).where(SchoolProfile.school_id == school.id)):
            continue
        db.add(
            SchoolProfile(
                school_id=school.id,
                tuition_range=item.get("tuition_range") or "",
                accommodation_fee=item.get("accommodation_fee") or "",
                campus_list=list(item.get("campus_list") or []),
                established_year=item.get("established_year"),
                master_phd_points=item.get("master_phd_points") or None,
                first_class_major_count=item.get("first_class_major_count"),
                faculty_count=item.get("faculty_count"),
                student_faculty_ratio=item.get("student_faculty_ratio") or "",
                source_id=source_by_key[str(item["source"])].id,
            )
        )
        created["profile"] += 1

    # —— 生活信息 ——
    for item in payload.get("life") or []:
        school = school_by_key[str(item["school"])]
        content = item.get("content") or ""
        exists = db.scalar(
            select(SchoolLife.id).where(
                SchoolLife.school_id == school.id,
                SchoolLife.category == (item.get("category") or ""),
                SchoolLife.content == content,
            )
        )
        if exists is not None:
            continue
        db.add(
            SchoolLife(
                school_id=school.id,
                category=item.get("category") or "",
                content=content,
                source_type=item.get("source_type") or "",
                source_name=item["source_name"],
                source_url=item["source_url"],
                year=int(item["year"]),
                reliability=item["reliability"],
            )
        )
        created["life"] += 1

    db.commit()
    return created


def main() -> int:
    """命令行入口：把演示数据灌入 zhixuan 数据库。"""
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        created = seed_demo(db)
    print("演示院校数据入库完成：")
    for table in TABLES:
        print(f"  新增 {table}: {created[table]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
