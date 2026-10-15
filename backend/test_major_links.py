"""录取分 → 专业库挂接的专项测试（``school_major_score.major_id``）。

与 ``test_importers.py`` 的分工：那边验「导入报告的行数守恒与幂等」，
本文件用独立夹具验**行级语义**——只填空值、不覆盖既有、未命中留 NULL 不猜、
失效 id 被识别，以及「专业名被改名后仍能按名重新挂接」。

无需 pytest，直接运行：
    cd backend && .venv\\Scripts\\python.exe test_major_links.py
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

_WORK = Path(tempfile.mkdtemp(prefix="zhixuan_major_links_test_"))
os.environ["ZHIXUAN_DATABASE_URL"] = f"sqlite:///{(_WORK / 'links.db').as_posix()}"
os.environ["ZHIXUAN_SECRET_KEY"] = "test-secret-key-major-links-at-least-32-bytes"
os.environ["ZHIXUAN_ENV"] = "test"

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal, create_all  # noqa: E402
from app.models.base_data import Major, School, SchoolMajorScore  # noqa: E402
from app.models.source import Source  # noqa: E402
from app.services.importers.major_links import import_major_links  # noqa: E402

logging.getLogger("zhixuan").setLevel(logging.CRITICAL)

CASES: list[tuple[str, Callable[[], None]]] = []


def case(title: str) -> Callable:
    def decorator(func: Callable[[], None]) -> Callable[[], None]:
        CASES.append((title, func))
        return func

    return decorator


def _seed(db) -> None:
    src = Source(source_name="教育部（本科专业目录）", source_url="https://www.moe.gov.cn/", year=2025)
    db.add(src)
    db.flush()
    db.add_all(
        [
            School(id=1, name="甲大学", code="10001", province="河南", level="本科"),
            Major(id=1, name="临床医学", code="100201K", category="医学"),
            Major(id=2, name="计算机类", code="0809", category="工学", is_category=True),
            Major(id=3, name="中医学", code="100501K", category="医学"),
            Major(id=4, name="中西医临床医学", code="100601K", category="医学"),
        ]
    )
    db.flush()
    db.add_all(
        [
            # ① 精确可命中
            SchoolMajorScore(school_id=1, province="河南", year=2025, batch="本科批",
                             subject_type="物理类", major_name="临床医学", min_score=620, source_id=src.id),
            # ② 同校不同专业组下再次出现，仍应命中同一专业
            SchoolMajorScore(school_id=1, province="河南", year=2025, batch="本科批",
                             subject_type="物理类", group_code="01", major_name="临床医学",
                             min_score=618, source_id=src.id),
            # ③ 专业类：按类招生，命中「计算机类」
            SchoolMajorScore(school_id=1, province="河南", year=2025, batch="本科批",
                             subject_type="物理类", major_name="计算机类", min_score=600, source_id=src.id),
            # ④ 仅归一后可命中（全角括号 + 换行）
            SchoolMajorScore(school_id=1, province="河南", year=2025, batch="本科批",
                             subject_type="物理类", major_name="中西 医临床\n医学", min_score=590, source_id=src.id),
            # ⑤ 目录外（试验班）→ 必须保持 NULL
            SchoolMajorScore(school_id=1, province="河南", year=2025, batch="本科批",
                             subject_type="物理类", major_name="工科试验班", min_score=580, source_id=src.id),
            # ⑥ 已挂接但指向不存在的专业 → 计入 stale，不被静默改写
            SchoolMajorScore(school_id=1, province="河南", year=2025, batch="本科批",
                             subject_type="物理类", major_name="临床医学", min_score=575,
                             major_id=9999, source_id=src.id),
        ]
    )
    db.commit()


create_all()
with SessionLocal() as _db:
    _seed(_db)


def _run():
    with SessionLocal() as db:
        report = import_major_links(db)
        db.commit()
        return report


@case("精确与归一后可命中的行被挂到 major.id（专业类按类挂接）")
def _() -> None:
    report = _run()
    assert report.read == 6, report.describe()
    assert report.updated == 4, report.describe()
    with SessionLocal() as db:
        rows = {
            (row.major_name, row.min_score): row.major_id
            for row in db.scalars(select(SchoolMajorScore)).all()
        }
    assert rows[("临床医学", 620)] == 1
    assert rows[("临床医学", 618)] == 1
    assert rows[("计算机类", 600)] == 2  # 专业类行
    assert rows[("中西 医临床\n医学", 590)] == 4  # 归一后命中


@case("目录外的专业名保持 NULL，不猜不硬挂")
def _() -> None:
    with SessionLocal() as db:
        row = db.scalar(
            select(SchoolMajorScore).where(SchoolMajorScore.major_name == "工科试验班")
        )
        report = import_major_links(db)
        db.commit()
    assert row.major_id is None
    assert report.skip_reasons.get("unmatched_major_name") == 1, report.describe()


@case("已挂接但指向不存在的专业：记为 stale，不覆盖不猜测")
def _() -> None:
    with SessionLocal() as db:
        report = import_major_links(db)
        db.commit()
    assert report.skip_reasons.get("stale_major_id") == 1, report.describe()
    with SessionLocal() as db:
        row = db.scalar(
            select(SchoolMajorScore).where(SchoolMajorScore.major_id == 9999)
        )
    assert row is not None, "失效 id 被静默改写，未如实保留"


@case("幂等：重复执行零写入，已挂接行计入 unchanged")
def _() -> None:
    report = _run()
    assert report.updated == 0, report.describe()
    assert report.unchanged == 4, report.describe()  # 4 行已挂接（失效 id 单列 stale）
    assert report.skipped == 2, report.describe()  # stale 1 + 未匹配 1


@case("专业表为空时明确报缺失，不误判为全部未匹配")
def _() -> None:
    with SessionLocal() as db:
        db.query(Major).delete()
        db.commit()
        report = import_major_links(db)
        db.commit()
    assert report.missing_file, report.describe()
    assert report.read == 0, report.describe()


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
    print(f"\n专业挂接用例：{total - len(failures)}/{total} 通过")
    if failures:
        return 1
    print("major link tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
