"""③ 数据产出物 → 数据库 导入层测试（tasks.md 2.x 消费侧）。

覆盖点（每条都有对应的验收含义）：
- 冷库导入的逐数据集计数与「行数守恒」（created+updated+unchanged+skipped == read）；
- **幂等**：同一份数据第二次执行新增 / 更新必须为 0；
- **来源三要素红线**：来源缺失的行必须跳过并计入报告，绝不静默入库；
- 院校业务键取 **name** 而非 code：国标代码共用的独立招生实体不得被丢弃；
- 跨层词表归一：``pending`` → ``schema_only``、``河南省`` → ``河南``、``410000`` → ``41``、
  ``category_group`` → ``exam_type``；
- 口径歧义与数据侧缺口必须**显式跳过并上报**，不猜不拆：
  ``艺术类 / 体育类`` 一行两类、``general-batch`` 外键缺失、占位骨架；
- ``province_exam_rule`` 的 ``data_status`` 同步进 ``rule_dataset_status``（闸门 1 的可用性来源）；
- 新增列 ``score_segment.batch`` 真的落库（③ 口径：批次不可合并）；
- 迁移 0008 在 develop 上的其余新增列同样必须被消费：``school.is_985`` / ``is_211`` /
  ``dual_class``（缺列重导不得清空）、``score_segment.same_score_count``
  （``segment_count`` 同口径兜底、缺省留 NULL 不推算）；
- ``school_major_score``：可空列（``school_id`` / ``major_id``）、身份列
  （``major_code`` / ``group_code`` / ``major_name`` / ``exam_system``）、
  **位置 id 防护**（未知 ``school_id`` 跳过上报而不是降级成 NULL）、
  同键多行的序数幂等。

数据来源是 ③ 随仓库分发的小样本包（``data/samples/``），
来源登记表另取真实表 ``data/sources/source-table.json``（非样本包，规模会增长），
正是为「② 建表导入联调」准备的，因此本测试不需要下载数据本体。

⚠️ 院校样本包只有 10 所，而录取分样本引用了院校库 id 243（安徽财经大学），
两者不自洽——共享夹具里因此会有 8 行按设计跳过（正是位置 id 防护的实证）；
需要一个「院校齐全」的专门夹具来验证 12 行零丢失。

纯脚本，无 pytest 依赖：
    cd backend && .venv\\Scripts\\python.exe test_importers.py
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections import Counter
from collections.abc import Callable
from pathlib import Path

# 环境变量必须在导入 app.* 之前设置：settings 在首次导入时读取一次
_WORK = Path(tempfile.mkdtemp(prefix="zhixuan_import_test_"))
os.environ["ZHIXUAN_DATABASE_URL"] = f"sqlite:///{(_WORK / 'import.db').as_posix()}"
os.environ["ZHIXUAN_SECRET_KEY"] = "test-secret-key-import-suite-at-least-32-bytes"
os.environ["ZHIXUAN_ENV"] = "test"

from sqlalchemy import delete, func, select  # noqa: E402

from app.db.session import SessionLocal, create_all  # noqa: E402
from app.models.base_data import Major, School, SchoolMajorScore, ScoreSegment  # noqa: E402
from app.models.constraints import ProvinceExamRule, RuleDatasetStatus  # noqa: E402
from app.models.pathway import Pathway, PathwayEligibility, PathwayRegion  # noqa: E402
from app.models.source import Source  # noqa: E402
from app.services.importers import SourceRegistry  # noqa: E402
from app.services.importers.__main__ import run_all  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA = REPO_ROOT / "data"
SAMPLES = DATA / "samples"

create_all()

# --------------------------------------------------------------------------- #
# 夹具：把真实字典 + 样本包拼成一个「数据根」，形状与仓库 data/ 一致
# --------------------------------------------------------------------------- #
ROOT = _WORK / "data_root"
(ROOT / "sources").mkdir(parents=True, exist_ok=True)
(ROOT / "dictionaries").mkdir(parents=True, exist_ok=True)
(ROOT / "schools").mkdir(parents=True, exist_ok=True)
(ROOT / "score_segment").mkdir(parents=True, exist_ok=True)
(ROOT / "school_major_score").mkdir(parents=True, exist_ok=True)
(ROOT / "majors").mkdir(parents=True, exist_ok=True)

shutil.copy(DATA / "sources" / "source-table.json", ROOT / "sources" / "source-table.json")
for name in (
    "pathways-26.json",
    "pathway-regions.json",
    "pathway-eligibility.json",
    "province-exam-rule.json",
):
    shutil.copy(DATA / "dictionaries" / name, ROOT / "dictionaries" / name)
shutil.copy(SAMPLES / "school.json", ROOT / "schools" / "schools_merged.json")
shutil.copy(SAMPLES / "score_segment.json", ROOT / "score_segment" / "score_segment_sample.json")
shutil.copy(
    SAMPLES / "school_major_score.json",
    ROOT / "school_major_score" / "school_major_score_sample.json",
)
# 专业库（845 专业 + 93 专业类）随仓库分发，是录取分专业挂接的前置
shutil.copy(DATA / "majors" / "majors.json", ROOT / "majors" / "majors.json")

# 样本包的既定规模。
# ⚠️ SAMPLE_SOURCES 例外：`data/sources/source-table.json` 是**真实来源登记表**（非样本包），
#    会随 ③ 新增来源而增长；写死曾导致一次假失败（③ 在 PR #8 把来源从 15 加到 17）。
#    故从文件读取 —— 断言仍是「读多少就建多少」，但不再与登记表规模耦合。
SAMPLE_SCHOOLS = 10
SAMPLE_SEGMENTS = 12
SAMPLE_SOURCES = len(
    json.loads((DATA / "sources" / "source-table.json").read_text(encoding="utf-8"))["sources"]
)
SAMPLE_PATHWAYS = 26
SAMPLE_REGIONS = 91
SAMPLE_RULES = 11
SAMPLE_EXAM_RULES = 7
SAMPLE_MAJOR_SCORES = 12
SAMPLE_MAJORS = 845
SAMPLE_MAJOR_CLASSES = 93

CASES: list[tuple[str, Callable[[], None]]] = []


def case(title: str) -> Callable:
    def decorator(func: Callable[[], None]) -> Callable[[], None]:
        CASES.append((title, func))
        return func

    return decorator


# --------------------------------------------------------------------------- #
# 第一次全量导入（各用例只读它的结果）
# --------------------------------------------------------------------------- #
with SessionLocal() as _db:
    FIRST = run_all(_db, ROOT)
    _db.commit()
FIRST_BY_NAME = {report.dataset: report for report in FIRST}

with SessionLocal() as _db:
    SECOND = run_all(_db, ROOT)
    _db.commit()
SECOND_BY_NAME = {report.dataset: report for report in SECOND}


# --------------------------------------------------------------------------- #
# 用例
# --------------------------------------------------------------------------- #
@case("每个数据集的行数都被完全解释（created+updated+unchanged+skipped == read）")
def test_row_accounting() -> None:
    for report in FIRST:
        assert report.accounted == report.read, (
            report.dataset,
            report.describe(),
        )


@case(
    f"冷库首次导入：来源 {SAMPLE_SOURCES} / 途径 {SAMPLE_PATHWAYS} / 区域 {SAMPLE_REGIONS}"
    f" / 院校 {SAMPLE_SCHOOLS} / 分段 {SAMPLE_SEGMENTS}"
)
def test_first_run_counts() -> None:
    assert FIRST_BY_NAME["source"].created == SAMPLE_SOURCES
    assert FIRST_BY_NAME["pathway"].created == SAMPLE_PATHWAYS
    assert FIRST_BY_NAME["pathway_region"].created == SAMPLE_REGIONS
    assert FIRST_BY_NAME["school"].created == SAMPLE_SCHOOLS
    assert FIRST_BY_NAME["score_segment"].created == SAMPLE_SEGMENTS


@case("院校库显式采用 ③ 的 id：北京大学 51 / 清华大学 55（下游录取分按此 id 引用）")
def test_school_ids_from_data() -> None:
    with SessionLocal() as db:
        assert db.get(School, 51) is not None and db.get(School, 51).name == "北京大学"
        assert db.get(School, 55) is not None and db.get(School, 55).name == "清华大学"
        # 注意：不能断言自增顺序——显式 id 的意义正是让顺序不再影响归属
        ids = set(db.scalars(select(School.id)).all())
    assert {51, 55} <= ids


@case("幂等：第二次执行所有数据集新增与更新均为 0")
def test_idempotent() -> None:
    for report in SECOND:
        assert report.created == 0, (report.dataset, report.describe())
        assert report.updated == 0, (report.dataset, report.describe())


@case("幂等：第二次执行各行全部落在 unchanged，不产生假跳过")
def test_idempotent_unchanged() -> None:
    for dataset in ("source", "pathway", "pathway_region", "school", "score_segment"):
        report = SECOND_BY_NAME[dataset]
        assert report.unchanged == report.read, (dataset, report.describe())


@case("来源三要素红线：缺来源的行跳过并计入报告，不静默入库")
def test_missing_source_is_skipped() -> None:
    from app.services.importers.sources import import_sources

    broken = _WORK / "broken" / "sources"
    broken.mkdir(parents=True, exist_ok=True)
    payload = {
        "sources": [
            {
                "id": "SRC-BROKEN",
                "source_name": "缺链接的来源",
                "source_url": "",
                "year": 2026,
            }
        ]
    }
    target = broken / "source-table.json"
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with SessionLocal() as db:
        report = import_sources(db, target)
    assert report.read == 1
    assert report.created == 0
    assert report.skipped == 1
    assert report.skip_reasons == {"missing_source_triplet": 1}


@case("口径歧义显式跳过：pathway_eligibility 的 general-batch 外键缺失")
def test_eligibility_fk_missing_skipped() -> None:
    report = FIRST_BY_NAME["pathway_eligibility"]
    assert report.created == SAMPLE_RULES - 1
    assert report.skip_reasons == {"pathway_fk_missing": 1}


@case("口径歧义显式跳过：province_exam_rule 的「艺术类 / 体育类」一行两类")
def test_exam_type_ambiguity_skipped() -> None:
    report = FIRST_BY_NAME["province_exam_rule"]
    assert report.created == SAMPLE_EXAM_RULES - 1
    assert report.skip_reasons == {"exam_type_not_in_vocabulary": 1}


@case("跨层词表归一：pathway.data_status 的 pending 收敛为 schema_only")
def test_data_status_normalized() -> None:
    with SessionLocal() as db:
        statuses = set(db.scalars(select(Pathway.data_status)).all())
    assert statuses <= {"available", "partial", "schema_only", "unavailable"}
    assert "schema_only" in statuses


@case("fail：pathway.data_status 不允许出现数据侧自造值 pending")
def test_data_status_no_pending() -> None:
    with SessionLocal() as db:
        count = db.scalar(
            select(func.count()).select_from(Pathway).where(Pathway.data_status == "pending")
        )
    assert count == 0


@case("跨层词表归一：省名 河南省 → 河南；省码 410000 → 41")
def test_province_normalized() -> None:
    with SessionLocal() as db:
        provinces = set(db.scalars(select(PathwayRegion.province)).all())
        codes = set(db.scalars(select(ProvinceExamRule.province_code)).all())
    assert provinces == {"河南"}
    assert codes <= {"41", "36"}


@case("跨层词表归一：category_group 映射为 exam_type，且只落在契约枚举内")
def test_exam_type_normalized() -> None:
    with SessionLocal() as db:
        types = set(db.scalars(select(ProvinceExamRule.exam_type)).all())
    assert types <= {"普通", "艺术", "体育"}
    assert "普通" in types


@case("江西 2026 普通本科模板导入后保留唯一键和来源关联")
def test_jiangxi_2026_rule_source() -> None:
    with SessionLocal() as db:
        rows = list(db.scalars(select(ProvinceExamRule).where(
            ProvinceExamRule.province_code == "36",
            ProvinceExamRule.year == 2026,
            ProvinceExamRule.batch_code == "undergraduate_regular",
            ProvinceExamRule.exam_type == "普通",
        )).all())
        assert len(rows) == 1, rows
        source = db.get(Source, rows[0].source_id)
        status = db.scalar(select(RuleDatasetStatus).where(
            RuleDatasetStatus.province_code == "36",
            RuleDatasetStatus.year == 2026,
            RuleDatasetStatus.batch_code == "undergraduate_regular",
            RuleDatasetStatus.exam_type == "普通",
            RuleDatasetStatus.dataset == "province_exam_rule",
        ))
    assert source is not None and source.source_name == "江西省教育考试院"
    assert source.source_url.startswith("http") and source.year == 2026
    assert status is not None and status.status == "available"


@case("闸门 1 可用性：province_exam_rule 的 data_status 同步进 rule_dataset_status")
def test_rule_dataset_status() -> None:
    with SessionLocal() as db:
        rows = db.scalars(
            select(RuleDatasetStatus).where(RuleDatasetStatus.dataset == "province_exam_rule")
        ).all()
    assert rows, "rule_dataset_status 未写入 province_exam_rule 状态"
    statuses = {row.status for row in rows}
    assert statuses <= {"available", "partial", "schema_only", "unavailable"}
    # 2024 旧制那条是 schema_only：数值未核实，不得用于志愿计算
    assert any(row.status == "schema_only" for row in rows)


@case("院校业务键取 name：国标代码共用的独立招生实体不被丢弃")
def test_school_business_key_is_name() -> None:
    with SessionLocal() as db:
        total = db.scalar(select(func.count()).select_from(School))
        names = db.scalar(select(func.count(func.distinct(School.name))))
    assert total == SAMPLE_SCHOOLS
    assert names == total, "按 name 导入时名称必须唯一"


@case("新增列 score_segment.batch 落库（③ 口径：老高考批次不可合并）")
def test_score_segment_batch_persisted() -> None:
    with SessionLocal() as db:
        rows = db.scalars(select(ScoreSegment.batch)).all()
    assert rows, "score_segment 未导入"
    assert any(row for row in rows), "batch 列全为空，说明批次信息被丢弃"


@case("新增列 school.is_985 / is_211 / dual_class 落库，且缺列重导不清空")
def test_school_tiers_persisted() -> None:
    """迁移 0008 加的三列必须由导入器消费（队长 2026-10-14 评审意见）。

    三阶段断言：
    1. 合并数据集带层次列 → 落库为 True/True/双一流；
    2. 换一份**没有**层次列的院校库重导（徐的原始格式）→ 已落库的标记不得被清空；
    3. 再导一次带层次列的文件 → 幂等（created=0 / updated=0）。
    """
    from app.services.importers.schools import import_schools

    folder = _WORK / "tiers" / "schools"
    folder.mkdir(parents=True, exist_ok=True)
    base = {
        "province": "河南",
        "level": "本科",
        "source_name": "河南省阳光高考信息平台（招生计划查询系统）",
        "source_url": "https://zsjh.haedu.cn/qwerasd/school",
        "year": 2026,
    }
    with_tiers = folder / "with_tiers.json"
    with_tiers.write_text(
        json.dumps(
            {
                "records": [
                    {"id": 9001, "name": "层次测试大学甲", "is_985": True,
                     "is_211": True, "dual_class": "双一流", **base},
                    {"id": 9002, "name": "层次测试大学乙", "is_985": False,
                     "is_211": False, "dual_class": "", **base},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    without_tiers = folder / "without_tiers.json"
    without_tiers.write_text(
        json.dumps(
            {
                "schools": [
                    {"id": 9001, "name": "层次测试大学甲", **base},
                    {"id": 9002, "name": "层次测试大学乙", **base},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with SessionLocal() as db:
        registry = SourceRegistry(db)
        registry.load_registry(ROOT / "sources" / "source-table.json")
        first = import_schools(db, with_tiers, registry)
        db.commit()

        tiers = db.get(School, 9001)
        plain = db.get(School, 9002)
        assert tiers is not None and plain is not None
        assert tiers.is_985 is True and tiers.is_211 is True and tiers.dual_class == "双一流"
        assert plain.is_985 is False and plain.is_211 is False and plain.dual_class == ""

        # 换原始格式（无层次列）重导：不得把已落库的标记清空
        second = import_schools(db, without_tiers, registry)
        db.commit()
        db.refresh(tiers)
        assert first.created == 2, first.describe()
        assert tiers.is_985 is True and tiers.dual_class == "双一流", "缺列重导把层次标记清空了"
        assert second.created == 0 and second.updated == 0, second.describe()

        # 再导带层次列的文件：幂等
        third = import_schools(db, with_tiers, registry)
        db.commit()
        assert third.created == 0 and third.updated == 0, third.describe()


@case("新增列 score_segment.same_score_count 落库（segment_count 同口径兜底，缺省不推算）")
def test_score_segment_same_score_count() -> None:
    """迁移 0008 加的 same_score_count 必须由导入器消费，否则库内恒为空。

    三种字段形态都要覆盖：合并数据集 ``same_score_count``、③ 原始文件
    ``segment_count``、两者都无（留 NULL，不按位次差值倒推）。
    """
    from app.services.importers.score_segment import import_score_segments

    folder = _WORK / "same_count" / "score_segment"
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "source_name": "河南省教育考试院（经河南省阳光高考信息平台发布）",
            "source_url": "https://gaokao.haedu.cn/501/552/2026/0625/155639.html",
            "year": 2027,
        },
        "segments": [
            {"province": "河南", "year": 2027, "subject_type": "历史类", "batch": "本科批",
             "score": 700, "cumulative_rank": 5, "same_score_count": 3},
            {"province": "河南", "year": 2027, "subject_type": "历史类", "batch": "本科批",
             "score": 699, "cumulative_rank": 12, "segment_count": 7},
            {"province": "河南", "year": 2027, "subject_type": "历史类", "batch": "本科批",
             "score": 698, "cumulative_rank": 20},
        ],
    }
    (folder / "score_segment_2027.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    with SessionLocal() as db:
        registry = SourceRegistry(db)
        registry.load_registry(ROOT / "sources" / "source-table.json")
        report = import_score_segments(db, folder, registry)
        db.commit()
        rows = {
            row.score: row.same_score_count
            for row in db.scalars(
                select(ScoreSegment).where(ScoreSegment.year == 2027)
            ).all()
        }
    assert report.created == 3, report.describe()
    assert rows[700] == 3, "same_score_count 字段未落库"
    assert rows[699] == 7, "segment_count 同口径兜底失败"
    assert rows[698] is None, "无该字段时应留 NULL，不得按位次差值倒推"


@case("T4 覆盖快照统计与 2026 分母缺口对账")
def test_admission_coverage_snapshot() -> None:
    # data/raw/ 数据本体不入库（.gitignore）：本机有 T4 完整快照（9.9MB）时做逐桶对账；
    # CI / 队员机器上降级为校验**已入库**的审计报告口径（报告含快照 SHA-256 留档）。
    full_path = DATA / "raw" / "subject-requirement.full.json"
    if full_path.exists():
        full = json.loads(full_path.read_text(encoding="utf-8"))
        rows = full.get("rows", [])
        assert len(rows) == 17492
        counts = Counter(
            (row.get("province_code"), int(row.get("year") or 0), row.get("status"), row.get("target_type"))
            for row in rows
        )
        assert sum(v for (province, year, status, _), v in counts.items() if province == "41" and year == 2025 and status == "ok") == 9809
        assert sum(v for (province, year, status, _), v in counts.items() if province == "36" and year == 2024 and status == "ok") == 7683
        assert not [row for row in rows if row.get("province_code") in {"41", "36"} and row.get("year") == 2026]
    else:
        print("    [skip] 本机无 data/raw/subject-requirement.full.json（数据本体不入库），仅校验审计报告")
    report = (DATA / "reports" / "admission-gate-coverage-2026.md").read_text(encoding="utf-8")
    assert "不可计算（缺少 2026 招生目标清单）" in report
    assert "不可计算（分母缺失）" in report


@case("来源登记：每条规则行的 source_id 都能指回 source 表")
def test_sources_present() -> None:
    with SessionLocal() as db:
        source_ids = set(db.scalars(select(Source.id)).all())
        used = set(db.scalars(select(ProvinceExamRule.source_id)).all())
        used |= set(db.scalars(select(PathwayEligibility.source_id)).all())
        used |= set(db.scalars(select(PathwayRegion.source_id)).all())
        used |= set(db.scalars(select(ScoreSegment.source_id)).all())
    assert used <= source_ids, used - source_ids


@case("省份志愿模式唯一键 (province_code, year, batch_code, exam_type) 无重复")
def test_province_exam_rule_unique() -> None:
    with SessionLocal() as db:
        keys = db.execute(
            select(
                ProvinceExamRule.province_code,
                ProvinceExamRule.year,
                ProvinceExamRule.batch_code,
                ProvinceExamRule.exam_type,
            )
        ).all()
    assert len(keys) == len(set(keys))


@case("数据文件缺失时优雅退出：missing_file 置位且不抛异常")
def test_missing_file_graceful() -> None:
    from app.services.importers.schools import import_schools

    with SessionLocal() as db:
        registry = SourceRegistry(db)
        report = import_schools(db, _WORK / "not-exists" / "schools_merged.json", registry)
    assert report.read == 0
    assert report.missing_file is not None


@case("数据集级溯源回退：行内无来源、meta 有三要素时仍能落库")
def test_meta_level_source_fallback() -> None:
    from app.services.importers.score_segment import import_score_segments

    folder = _WORK / "meta_only" / "score_segment"
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "source_name": "河南省教育考试院（经河南省阳光高考信息平台发布）",
            "source_url": "https://gaokao.haedu.cn/501/552/2026/0625/155639.html",
            "year": 2026,
        },
        "segments": [
            {"province": "河南", "year": 2026, "subject_type": "历史类", "score": 686,
             "cumulative_rank": 7}
        ],
    }
    (folder / "score_segment_2026_meta.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    with SessionLocal() as db:
        registry = SourceRegistry(db)
        registry.load_registry(ROOT / "sources" / "source-table.json")
        report = import_score_segments(db, folder, registry)
        db.commit()
        row = db.scalar(
            select(ScoreSegment).where(
                ScoreSegment.year == 2026, ScoreSegment.subject_type == "历史类"
            )
        )
    assert report.created == 1, report.describe()
    assert row is not None and row.cumulative_rank == 7


@case("录取分：行数完全解释（12 = 入库 + 跳过），没有静默丢弃")
def test_major_score_accounting() -> None:
    report = FIRST_BY_NAME["school_major_score"]
    assert report.read == SAMPLE_MAJOR_SCORES, report.describe()
    assert report.accounted == report.read, report.describe()


@case("录取分：位置 id 防护——院校样本未覆盖的 school_id 跳过上报，绝不降级成 NULL")
def test_major_score_positional_id_guard() -> None:
    with SessionLocal() as db:
        known = set(db.scalars(select(School.id)).all())
    rows = json.loads((SAMPLES / "school_major_score.json").read_text(encoding="utf-8"))["scores"]
    expected_unknown = sum(
        1 for row in rows if row.get("school_id") is not None and row["school_id"] not in known
    )
    assert expected_unknown > 0, "夹具失效：院校样本恰好覆盖了全部 school_id，本用例失去意义"

    report = FIRST_BY_NAME["school_major_score"]
    assert report.skip_reasons == {"unknown_school_id": expected_unknown}, report.describe()
    # 未挂上的行留在库里的是 NULL，而不是被改写成别的院校 id
    with SessionLocal() as db:
        stray = db.scalar(
            select(func.count())
            .select_from(SchoolMajorScore)
            .where(SchoolMajorScore.school_id.notin_(known))
        )
    assert stray == 0


@case("录取分：school_id 为空的行必须入库（③ §五-2：客观缺失，不得拒绝）")
def test_major_score_null_school_kept() -> None:
    with SessionLocal() as db:
        nulls = db.scalar(
            select(func.count())
            .select_from(SchoolMajorScore)
            .where(SchoolMajorScore.school_id.is_(None))
        )
    assert nulls == 2, f"样本有 2 行 school_id 空（院校改名），实际入库 {nulls} 行"


@case("录取分：2024 两省 subject_type 整列缺失的行入库且科类留空")
def test_major_score_empty_subject_type_kept() -> None:
    with SessionLocal() as db:
        blanks = db.scalar(
            select(func.count())
            .select_from(SchoolMajorScore)
            .where(SchoolMajorScore.subject_type == "")
        )
    assert blanks == 2, f"样本有 2 行 subject_type 空（2024 整列缺失），实际 {blanks} 行"


@case("录取分：身份列落库——major_code/group_code/major_name/exam_system 不被丢弃")
def test_major_score_identity_columns() -> None:
    with SessionLocal() as db:
        rows = db.scalars(select(SchoolMajorScore)).all()
    assert rows, "录取分未导入"
    codes = {row.major_code for row in rows}
    assert {"10", "11", "12", "14"} & codes, codes
    assert any(row.major_name for row in rows), "major_name 全空，专业身份丢失"
    assert any(row.group_code for row in rows), "group_code 全空，专业组身份丢失"
    assert {row.exam_system for row in rows} <= {"文理科", "3+1+2"}
    assert "3+1+2" in {row.exam_system for row in rows}


@case("录取分：二次执行幂等——新增为 0，且已入库行数不变")
def test_major_score_idempotent() -> None:
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(SchoolMajorScore))
    report = SECOND_BY_NAME["school_major_score"]
    assert report.created == 0, report.describe()
    assert report.updated == 0, report.describe()
    with SessionLocal() as db:
        after = db.scalar(select(func.count()).select_from(SchoolMajorScore))
    assert after == before, (before, after)


@case("录取分：plan_count 不被 ③ 的 admit_count 污染（§2.4 不混填）")
def test_major_score_plan_count_not_polluted() -> None:
    with SessionLocal() as db:
        rows = db.scalars(select(SchoolMajorScore)).all()
    # ③ 的产物只有 admit_count，没有 plan_count；本表不得私自搬运
    assert all(row.plan_count is None for row in rows), [
        (row.major_name, row.plan_count) for row in rows if row.plan_count is not None
    ]


@case("录取分：院校齐全时 12 行零丢失、零跳过，且二次执行全落幂等")
def test_major_score_full_fixture() -> None:
    from app.services.importers.school_major_score import import_school_major_scores

    # 专门夹具：把录取分样本引用的三所院校补齐（id 取真实值）
    with SessionLocal() as db:
        db.execute(delete(SchoolMajorScore))
        for sid, name, province in ((51, "北京大学", "北京"), (55, "清华大学", "北京"),
                                    (243, "安徽财经大学", "安徽")):
            if db.get(School, sid) is None:
                db.add(School(id=sid, name=name, province=province, level="本科"))
        db.commit()

        registry = SourceRegistry(db)
        registry.load_registry(ROOT / "sources" / "source-table.json")
        first = import_school_major_scores(db, SAMPLES, registry)
        db.commit()
        total_first = db.scalar(select(func.count()).select_from(SchoolMajorScore))

        second = import_school_major_scores(db, SAMPLES, registry)
        db.commit()
        total_second = db.scalar(select(func.count()).select_from(SchoolMajorScore))

    assert first.created == SAMPLE_MAJOR_SCORES, first.describe()
    assert first.skipped == 0, first.describe()
    assert total_first == SAMPLE_MAJOR_SCORES
    assert second.created == 0 and second.updated == 0, second.describe()
    assert second.unchanged == SAMPLE_MAJOR_SCORES, second.describe()
    assert total_second == total_first

    # 同键多行（同校同年同批次同专业组、同分数）必须两行都在，按 major_code 区分
    with SessionLocal() as db:
        same_key = db.scalars(
            select(SchoolMajorScore).where(
                SchoolMajorScore.school_id == 243,
                SchoolMajorScore.year == 2025,
                SchoolMajorScore.batch == "本科批",
                SchoolMajorScore.subject_type == "物理类",
                SchoolMajorScore.min_score == 560,
            )
        ).all()
        null_rows = db.scalar(
            select(func.count())
            .select_from(SchoolMajorScore)
            .where(SchoolMajorScore.school_id.is_(None))
        )
        blank_rows = db.scalar(
            select(func.count())
            .select_from(SchoolMajorScore)
            .where(SchoolMajorScore.subject_type == "")
        )
    assert len(same_key) == 2, f"应保留 2 行（公共管理类 / 国际商务），实际 {len(same_key)}"
    assert {row.major_code for row in same_key} == {"14", "12"}
    assert null_rows == 2, "院校改名未挂上的 2 行必须保留为 NULL"
    assert blank_rows == 2, "2024 科类缺失的 2 行必须保留为空科类"


@case("录取分：来源解析——每行 source_id 都指回 source 表")
def test_major_score_sources_present() -> None:
    with SessionLocal() as db:
        source_ids = set(db.scalars(select(Source.id)).all())
        used = set(db.scalars(select(SchoolMajorScore.source_id)).all())
    assert used, "录取分未导入"
    assert used <= source_ids, used - source_ids


@case(f"专业库：导入 {SAMPLE_MAJORS} 专业 + {SAMPLE_MAJOR_CLASSES} 专业类，零跳过且幂等")
def test_majors_imported() -> None:
    report = FIRST_BY_NAME["major"]
    assert report.read == SAMPLE_MAJORS + SAMPLE_MAJOR_CLASSES, report.describe()
    assert report.created == SAMPLE_MAJORS + SAMPLE_MAJOR_CLASSES, report.describe()
    assert report.skipped == 0, report.describe()
    # 第二次执行必须零新增（幂等）
    again = SECOND_BY_NAME["major"]
    assert again.created == 0 and again.updated == 0, again.describe()
    assert again.unchanged == SAMPLE_MAJORS + SAMPLE_MAJOR_CLASSES, again.describe()

    with SessionLocal() as db:
        total = db.scalar(select(func.count()).select_from(Major))
        classes = db.scalar(
            select(func.count()).select_from(Major).where(Major.is_category.is_(True))
        )
        # category 存学科门类；专业类与专业不重名，代码唯一
        sample = db.scalar(select(Major).where(Major.code == "0101"))
    assert total == SAMPLE_MAJORS + SAMPLE_MAJOR_CLASSES, total
    assert classes == SAMPLE_MAJOR_CLASSES, classes
    assert sample is not None and sample.name == "哲学类" and sample.is_category is True


@case("录取分专业挂接：只处理已入库行、未匹配不猜、二次执行零写入")
def test_major_links() -> None:
    landed = FIRST_BY_NAME["school_major_score"].created
    report = FIRST_BY_NAME["school_major_score.major_id"]
    # 挂接只处理**已入库**的行（样本 12 行里 8 行因院校 id 不存在被跳过）
    assert report.read == landed, (report.describe(), landed)
    assert report.created == 0, report.describe()
    assert report.skipped == report.skip_reasons.get("unmatched_major_name", 0), report.describe()
    assert report.updated + report.skipped == report.read, report.describe()
    # 匹配口径与行级语义（只填空值 / 未命中留 NULL）见 test_major_links.py
    again = SECOND_BY_NAME["school_major_score.major_id"]
    assert again.updated == 0, again.describe()
    assert again.unchanged == report.updated, (again.describe(), report.describe())
    assert again.skipped == report.skipped, again.describe()


@case("专业库（合并数据集格式）：records + 显式 id 落库，下游 major_id 引用不错位")
def test_majors_merged_format() -> None:
    """合并数据集的主源形态：行自带 id，必须显式落 id（见 importers/majors.py docstring）。"""
    from app.services.importers.majors import import_majors

    folder = _WORK / "merged_major"
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "source_name": "教育部《普通高等学校本科专业目录（2025年）》",
            "source_url": (
                "https://www.moe.gov.cn/srcsite/A08/moe_1034/s4930/202504/"
                "W020250422312780837078.pdf"
            ),
            "year": 2025,
        },
        "records": [
            {"id": 9101, "name": "合并格式专业甲", "code": "998001T", "category": "工学",
             "first_class": "机械类", "degree": "", "intro": "", "is_category": False},
            {"id": 9102, "name": "合并格式专业类乙", "code": "9980", "category": "工学",
             "first_class": "", "degree": "", "intro": "", "is_category": True},
        ],
    }
    target = folder / "major.json"
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with SessionLocal() as db:
        registry = SourceRegistry(db)
        registry.load_registry(ROOT / "sources" / "source-table.json")
        report = import_majors(db, target, registry)
        db.commit()
        row_a = db.get(Major, 9101)
        row_b = db.get(Major, 9102)

    assert report.read == 2 and report.created == 2, report.describe()
    # 显式 id 生效：按合并数据集分配的 id 能原样取到
    assert row_a is not None and row_a.name == "合并格式专业甲", report.describe()
    assert row_b is not None and row_b.is_category is True, report.describe()

    # 二次装载幂等（code 命中更新分支，且不重置 id）
    with SessionLocal() as db:
        registry = SourceRegistry(db)
        registry.load_registry(ROOT / "sources" / "source-table.json")
        again = import_majors(db, target, registry)
        db.commit()
    assert again.created == 0 and again.updated == 0, again.describe()
    assert again.unchanged == 2, again.describe()

    # 清理本用例构造的行（保持既有用例的全局计数断言语义）
    with SessionLocal() as db:
        for code in ("998001T", "9980"):
            row = db.scalar(select(Major).where(Major.code == code))
            if row is not None:
                db.delete(row)
        db.commit()


def main() -> int:
    failures: list[tuple[str, str]] = []
    for title, fn in CASES:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - 测试汇总需要捕获全部异常
            failures.append((title, f"{type(exc).__name__}: {exc}"))

    for title, message in failures:
        print(f"FAIL  {title}\n      {message}")

    total = len(CASES)
    print(f"\n导入层用例：{total - len(failures)}/{total} 通过")
    if failures:
        return 1
    print("importer tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
