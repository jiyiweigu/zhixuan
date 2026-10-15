"""院校画像 / 生活信息 / 招生章程要点三个导入器的专项测试。

覆盖（与 ③ 的数据口径一一对应）：
- ``school_profile``：一校一行、JSON 列形状规范（``campus_list`` 只收 ``{name,address,city}``、
  ``master_phd_points`` 只收 ``{master,phd}``）、**空值不覆盖既有值**、未知 school_id 跳过；
- ``school_life``：业务键 ``(school_id, category, content)``、``source_type`` 中文归一、
  ``reliability`` 不在词表则跳过、来源三要素缺一不入库；
- ``enrollment_rule``：业务键 ``(school_id, year)``、四字段全空的行跳过（不落空记录）；
- 三者重复执行都必须零新增零更新。

无需 pytest，直接运行：
    cd backend && .venv\\Scripts\\python.exe test_school_extras.py
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

_WORK = Path(tempfile.mkdtemp(prefix="zhixuan_school_extras_test_"))
os.environ["ZHIXUAN_DATABASE_URL"] = f"sqlite:///{(_WORK / 'extras.db').as_posix()}"
os.environ["ZHIXUAN_SECRET_KEY"] = "test-secret-key-school-extras-at-least-32-bytes"
os.environ["ZHIXUAN_ENV"] = "test"

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal, create_all  # noqa: E402
from app.models.base_data import EnrollmentRule, School  # noqa: E402
from app.models.school_profile import SchoolLife, SchoolProfile  # noqa: E402
from app.models.source import Source  # noqa: E402
from app.services.importers import SourceRegistry  # noqa: E402
from app.services.importers.enrollment_rules import import_enrollment_rules  # noqa: E402
from app.services.importers.school_life import import_school_life  # noqa: E402
from app.services.importers.school_profiles import import_school_profiles  # noqa: E402

logging.getLogger("zhixuan").setLevel(logging.CRITICAL)

CASES: list[tuple[str, Callable[[], None]]] = []


def case(title: str) -> Callable:
    def decorator(func: Callable[[], None]) -> Callable[[], None]:
        CASES.append((title, func))
        return func

    return decorator


def _write(name: str, payload: dict) -> Path:
    path = _WORK / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


SRC_ROW = {
    "source_name": "天津体育学院官网·学校简介",
    "source_url": "https://www.tjus.edu.cn/xxgk/index.htm",
    "year": 2026,
}

PROFILE_PATH = _write(
    "school_profile_rows.json",
    {
        "meta": {"target_table": "school_profile"},
        "records": [
            {
                "school_id": 3,
                "school_name": "天津体育学院",
                "tuition_range": "4400-5800",
                "accommodation_fee": "",
                "campus_list": [
                    {"name": "河西校区", "address": "", "city": ""},
                    {"address": "无名称的脏元素"},
                    "不是对象",
                ],
                "established_year": 1958,
                "master_phd_points": {"master": 6, "phd": 1},
                "first_class_major_count": 11,
                "faculty_count": 600,
                "student_faculty_ratio": "",
                **SRC_ROW,
            },
            # 未知 school_id：必须跳过
            {"school_id": 9999, "tuition_range": "1-2", **SRC_ROW},
        ],
    },
)

LIFE_PATH = _write(
    "school_life_rows.json",
    {
        "meta": {"target_table": "school_life"},
        "records": [
            {
                "school_id": 3,
                "category": "校园环境",
                "content": "占地面积 3000 亩",
                "source_type": "官方",
                "reliability": "official",
                **SRC_ROW,
            },
            # reliability 不在跨层词表 → 跳过
            {
                "school_id": 3,
                "category": "图书馆",
                "content": "馆藏 100 万册",
                "source_type": "官方",
                "reliability": "半官方",
                **SRC_ROW,
            },
            # 来源三要素缺失 → 跳过
            {"school_id": 3, "category": "食堂", "content": "三个食堂", "reliability": "official"},
        ],
    },
)

RULE_PATH = _write(
    "enrollment_rule_rows.json",
    {
        "meta": {"target_table": "enrollment_rule"},
        "records": [
            {
                "school_id": 3,
                "year": 2025,
                "content": "",
                "subject_req": "物理类",
                "health_req": "【适用范围】仅部分专业（3 个）色盲色弱不可报",
                "foreign_lang_req": "",
                **SRC_ROW,
            },
            {"school_id": 3, "year": 2024, "content": "", "subject_req": "", "health_req": "",
             "foreign_lang_req": "", **SRC_ROW},  # 四字段全空 → 跳过
        ],
    },
)


create_all()
with SessionLocal() as _db:
    _db.add(Source(source_name="占位来源", source_url="https://example.invalid/", year=2025))
    _db.add_all(
        [
            School(id=3, name="天津体育学院", code="10071", province="天津", level="本科"),
            School(id=1085, name="三亚学院", code="13892", province="海南", level="本科"),
        ]
    )
    _db.commit()


def _registry(db) -> SourceRegistry:
    reg = SourceRegistry(db)
    reg.load_registry(_WORK / "not-exists.json")  # 行内自带三要素，无需登记表
    return reg


def _run_all_three():
    with SessionLocal() as db:
        reg = _registry(db)
        reports = (
            import_school_profiles(db, PROFILE_PATH, reg),
            import_school_life(db, LIFE_PATH, reg),
            import_enrollment_rules(db, RULE_PATH, reg),
        )
        db.commit()
        return reports


FIRST = _run_all_three()
SECOND = _run_all_three()


@case("画像：建行 1 条、未知 school_id 跳过、JSON 形状脏元素被丢弃")
def _() -> None:
    report = FIRST[0]
    assert report.read == 2 and report.created == 1, report.describe()
    assert report.skip_reasons.get("unknown_school_id") == 1, report.describe()
    with SessionLocal() as db:
        row = db.scalar(select(SchoolProfile).where(SchoolProfile.school_id == 3))
    assert row.tuition_range == "4400-5800"
    assert row.established_year == 1958 and row.faculty_count == 600
    assert row.master_phd_points == {"master": 6, "phd": 1}
    assert row.campus_list == [{"name": "河西校区", "address": "", "city": ""}], row.campus_list
    assert not row.accommodation_fee, "住宿费本表留空，不得填占位"
    assert report.notes and any("campus_list 中形状不符" in note for note in report.notes)


@case("画像：空值不覆盖库内既有值（重跑不会抹掉已补数据）")
def _() -> None:
    with SessionLocal() as db:
        row = db.scalar(select(SchoolProfile).where(SchoolProfile.school_id == 3))
        row.first_class_major_count = 11  # 库内既有值
        row.student_faculty_ratio = "16:1"  # 该字段在文件里是空串
        db.commit()
    _run_all_three()
    with SessionLocal() as db:
        row = db.scalar(select(SchoolProfile).where(SchoolProfile.school_id == 3))
    assert row.student_faculty_ratio == "16:1", "空值把既有值抹掉了"


@case("生活信息：source_type 中文归一、reliability 与来源不合规的行跳过")
def _() -> None:
    report = FIRST[1]
    assert report.read == 3 and report.created == 1, report.describe()
    assert report.skip_reasons.get("reliability_not_in_vocabulary") == 1, report.describe()
    assert report.skip_reasons.get("unresolvable_source") == 1, report.describe()
    with SessionLocal() as db:
        row = db.scalar(select(SchoolLife))
    assert row.source_type == "official", row.source_type
    assert row.reliability == "official"
    assert row.year == 2026


@case("招生章程：四字段全空的行跳过，体检要求原样保留「仅部分专业」限定")
def _() -> None:
    report = FIRST[2]
    assert report.read == 2 and report.created == 1, report.describe()
    assert report.skip_reasons.get("empty_rule_row") == 1, report.describe()
    with SessionLocal() as db:
        row = db.scalar(select(EnrollmentRule))
    assert "仅部分专业" in row.health_req, "限定语必须保留，不得改写成全校统一要求"
    assert row.subject_req == "物理类"


@case("三个导入器重复执行零新增零更新（幂等）")
def _() -> None:
    for report in SECOND:
        assert report.created == 0 and report.updated == 0, report.describe()
    assert SECOND[0].unchanged == 1, SECOND[0].describe()
    assert SECOND[1].unchanged == 1, SECOND[1].describe()
    assert SECOND[2].unchanged == 1, SECOND[2].describe()


def main() -> int:
    failures: list[tuple[str, str]] = []
    for title, fn in CASES:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failures.append((title, f"{type(exc).__name__}: {exc}"))
    for title, message in failures:
        print(f"FAIL  {title}\n      {message}")
    total = len(CASES)
    print(f"\n画像/生活/章程导入用例：{total - len(failures)}/{total} 通过")
    if failures:
        return 1
    print("school extras importer tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
