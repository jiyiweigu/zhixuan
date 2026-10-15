"""志愿方案候选数据源测试（库内真实录取分 → 候选）。

覆盖 tasks.md 6.3 的数据源接入口径：
- 只取普通本科批（batch_code 归一为 undergraduate_regular）；未归一的行被跳过并计数；
- 科类必须精确匹配，不跨考试制度；
- 同校取院校最低录取分（投档线口径）并记录取到该分数的专业名；
- 来源三要素缺一不入候选；
- 库内无匹配数据时回落演示候选，且 data_status / data_note 如实标注；
- build_plan 走真实库时 data_status=available、candidate_source=db。

无需 pytest，直接运行：
    cd backend && .venv\\Scripts\\python.exe test_candidates.py
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

_WORK = Path(tempfile.mkdtemp(prefix="zhixuan_candidates_test_"))
os.environ["ZHIXUAN_DATABASE_URL"] = f"sqlite:///{(_WORK / 'cand.db').as_posix()}"
os.environ["ZHIXUAN_SECRET_KEY"] = "test-secret-key-candidates-suite-at-least-32-bytes"
os.environ["ZHIXUAN_ENV"] = "test"

from app.db.session import SessionLocal, create_all  # noqa: E402
from app.models.base_data import School, SchoolMajorScore  # noqa: E402
from app.models.source import Source  # noqa: E402
from app.services import candidates as candidates_service  # noqa: E402
from app.services.plans import build_plan  # noqa: E402

logging.getLogger("zhixuan").setLevel(logging.CRITICAL)

CASES: list[tuple[str, Callable[[], None]]] = []


def case(title: str) -> Callable:
    def decorator(func: Callable[[], None]) -> Callable[[], None]:
        CASES.append((title, func))
        return func

    return decorator


def _seed(db) -> None:
    """三所院校：985 一所、普通两所；含未归一批次、科类不匹配、缺来源三类脏数据。"""
    src = Source(
        source_name="河南省教育考试院",
        source_url="https://www.haeea.cn/",
        year=2025,
    )
    # 来源登记不完整（缺链接）→ 引用它的行必须被跳过
    src_bad = Source(source_name="内部整理（缺链接）", source_url="", year=2025)
    db.add_all([src, src_bad])
    db.flush()
    a = School(id=1, name="甲大学", code="10001", province="河南", city="郑州",
               is_985=True, is_211=True, dual_class="双一流")
    b = School(id=2, name="乙学院", code="10002", province="河南", city="开封")
    c = School(id=3, name="丙大学", code="10003", province="河南", city="洛阳")
    db.add_all([a, b, c])
    db.flush()
    db.add_all(
        [
            # 甲：两条物理类本科批（取最低 600）+ 一条历史类（应被科类过滤）
            SchoolMajorScore(school_id=1, province="河南", year=2025, batch="本科批",
                             subject_type="物理类", major_code="01", major_name="计算机类",
                             min_score=620, source_id=src.id),
            SchoolMajorScore(school_id=1, province="河南", year=2025, batch="本科批",
                             subject_type="物理类", major_code="02", major_name="材料类",
                             min_score=600, source_id=src.id),
            SchoolMajorScore(school_id=1, province="河南", year=2025, batch="本科批",
                             subject_type="历史类", major_code="03", major_name="法学",
                             min_score=590, source_id=src.id),
            # 乙：老高考批次未归一 → 必须跳过
            SchoolMajorScore(school_id=2, province="河南", year=2022, batch="本科一批",
                             subject_type="物理类", major_code="04", major_name="土木类",
                             min_score=580, source_id=src.id),
            # 丙：来源三要素不全（缺链接）→ 必须跳过
            SchoolMajorScore(school_id=3, province="河南", year=2025, batch="本科批",
                             subject_type="物理类", major_code="05", major_name="化学类",
                             min_score=570, source_id=src_bad.id),
        ]
    )
    db.commit()


create_all()
with SessionLocal() as _db:
    _seed(_db)


def _query(**kwargs):
    with SessionLocal() as db:
        return candidates_service.db_candidates(db, **kwargs)


@case("01 只取普通本科批：未归一批次被跳过并计数")
def _() -> None:
    items, meta = _query(province="河南", subject_type="物理类")
    names = {item["name"] for item in items}
    assert names == {"甲大学"}, names
    assert meta["skipped"].get("batch_not_unified", 0) >= 1, meta["skipped"]


@case("02 不跨考试制度：科类精确匹配")
def _() -> None:
    items, _ = _query(province="河南", subject_type="物理类")
    assert [item["major"] for item in items] == ["材料类"], items
    items_hist, _ = _query(province="河南", subject_type="历史类")
    assert [item["major"] for item in items_hist] == ["法学"], items_hist


@case("03 同校取院校最低录取分并记录对应专业与位次")
def _() -> None:
    items, meta = _query(province="河南", subject_type="物理类")
    assert items[0]["min_score"] == 600, items[0]
    assert items[0]["major"] == "材料类"
    assert items[0]["admission_year"] == 2025
    assert items[0]["batch"] == "本科批"
    assert meta["years"] == [2022, 2025], meta["years"]


@case("04 候选带来源三要素与院校层次")
def _() -> None:
    items, _ = _query(province="河南", subject_type="物理类")
    item = items[0]
    assert item["source_name"] == "河南省教育考试院"
    assert item["source_url"].startswith("https://")
    assert item["year"] == 2025
    assert item["is_985"] is True and item["dual_class"] == "双一流"


@case("05 缺来源的行不入候选")
def _() -> None:
    items, meta = _query(province="河南", subject_type="物理类")
    assert all(item["name"] != "丙大学" for item in items)
    assert meta["skipped"].get("citation_missing", 0) == 1, meta["skipped"]


@case("06 库内无匹配数据返回空并说明原因")
def _() -> None:
    items, meta = _query(province="上海", subject_type="物理类")
    assert items == ()
    assert meta["notes"], meta
    items2, meta2 = _query(province="河南", subject_type="")
    assert items2 == ()
    assert any("科类" in note for note in meta2["notes"]), meta2["notes"]


@case("07 build_plan 用库内真实候选：data_status=available、带层次依据")
def _() -> None:
    with SessionLocal() as db:
        result = build_plan(
            {"profile": {"province": "河南", "score": 600, "subject_type": "物理类"}},
            db=db,
        )
    assert result["candidate_source"] == "db", result["data_status"]
    assert result["data_status"] == "available"
    assert any("真实录取分" in result["data_note"] for _ in [0]), result["data_note"]
    assert result["items"], result
    for item in result["items"]:
        assert item["name"] == "甲大学"
        assert any("985" in reason for reason in item["reasons"]), item["reasons"]


@case("08 build_plan 库内无数据时回落演示并标注 schema_only")
def _() -> None:
    with SessionLocal() as db:
        result = build_plan(
            {"profile": {"province": "上海", "score": 600, "subject_type": "物理类"}},
            db=db,
        )
    assert result["candidate_source"] == "demo", result["candidate_source"]
    assert result["data_status"] == "schema_only"
    assert "演示数据" in result["data_note"]


@case("09 未传 db 时行为不变（测试与管理端注入路径）")
def _() -> None:
    from app.core import dataset

    result = build_plan(
        {"profile": {"province": "河南", "score": 600, "subject_type": "物理类"}},
        candidates=tuple(dataset.load_candidates()),
    )
    assert result["candidate_source"] == "injected"
    assert result["data_status"] == "schema_only"


def main() -> int:
    failures: list[tuple[str, str]] = []
    for title, fn in CASES:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - 汇总需要捕获全部异常
            failures.append((title, f"{type(exc).__name__}: {exc}"))
    for title, message in failures:
        print(f"FAIL  {title}\n      {message}")
    total = len(CASES)
    print(f"\n候选数据源用例：{total - len(failures)}/{total} 通过")
    if failures:
        return 1
    print("candidate source tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
