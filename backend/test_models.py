"""数据库迁移与表结构测试（tasks.md 1.4 验收）。

验收条件原文：「迁移脚本可重复执行，表结构与第 7 章一致」。
本脚本用临时 SQLite 库实测两件事：

1. 幂等性 —— ``upgrade head`` 连续执行两次不报错；
2. 结构一致性 —— 22 张新表（第 7 章的 20 张 + 8.1 操作留痕表 + 8.3 索引任务表）的列、关键索引、
   外键与 CHECK 约束齐全，且 ``downgrade`` 能干净回滚到 0001。

无需 pytest，直接运行：
    cd backend && .venv\\Scripts\\python.exe test_models.py
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent

# 必须在导入 app.* 之前设定，app/core/config.py 在导入时读取一次环境变量
_TEMP_DIR = tempfile.mkdtemp(prefix="zhixuan-migrate-")
_DB_PATH = Path(_TEMP_DIR) / "migrate.db"
os.environ["ZHIXUAN_DATABASE_URL"] = f"sqlite:///{_DB_PATH.as_posix()}"
os.environ["ZHIXUAN_AUTO_CREATE_TABLES"] = "false"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, inspect, text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

BASE_TABLES = {"users", "profiles"}

# 产品书第 7 章「数据模型与数据字典」——新增 20 张表及其必需列
EXPECTED_COLUMNS: dict[str, set[str]] = {
    # 7.1 基础数据
    "source": {
        "id", "source_name", "source_url", "year", "source_type", "fetched_at",
        "created_at", "updated_at",
    },
    "school": {
        "id", "name", "code", "province", "city", "level", "type", "ownership",
        "website", "intro", "created_at", "updated_at",
    },
    "major": {
        "id", "name", "code", "category", "first_class", "degree",
        "created_at", "updated_at",
    },
    "school_major_score": {
        "id", "school_id", "major_id", "province", "year", "batch", "pathway_id",
        "subject_type", "min_score", "min_rank", "avg_score", "plan_count",
        "source_id", "created_at", "updated_at",
    },
    "score_segment": {
        "id", "province", "year", "subject_type", "score", "cumulative_rank",
        "source_id", "created_at", "updated_at",
    },
    "enrollment_rule": {
        "id", "school_id", "year", "content", "subject_req", "health_req",
        "foreign_lang_req", "source_id", "created_at", "updated_at",
    },
    "discipline_eval": {
        "id", "school_id", "discipline_name", "grade", "round", "source_id",
        "created_at", "updated_at",
    },
    # 7.2 升学途径
    "pathway": {
        "id", "name", "category", "batch", "target_group", "apply_time",
        "description", "priority", "data_status", "year", "source_id",
        "created_at", "updated_at",
    },
    "pathway_eligibility": {
        "id", "pathway_id", "province", "rule_type", "rule_desc", "params",
        "year", "source_id", "created_at", "updated_at",
    },
    "pathway_region": {
        "id", "pathway_id", "province", "county_name", "county_code", "year",
        "source_id", "created_at", "updated_at",
    },
    "pathway_score": {
        "id", "pathway_id", "school_id", "major_id", "province", "year",
        "min_score", "min_rank", "source_id", "created_at", "updated_at",
    },
    # 7.3 用户系统（users / profiles 已在 0001）
    "user_favorite": {"id", "user_id", "target_type", "target_id", "created_at"},
    "user_plan": {
        "id", "user_id", "name", "strategy", "items", "created_at", "updated_at",
    },
    # 7.4 院校画像
    "school_profile": {
        "id", "school_id", "tuition_range", "accommodation_fee", "campus_list",
        "established_year", "master_phd_points", "first_class_major_count",
        "faculty_count", "student_faculty_ratio", "source_id",
        "created_at", "updated_at",
    },
    "school_life": {
        "id", "school_id", "category", "content", "source_type", "source_name",
        "source_url", "year", "reliability", "created_at", "updated_at",
    },
    # 7.5 知识库与运营
    "knowledge_doc": {
        "id", "title", "source_name", "source_url", "year", "doc_type",
        "province", "pathway_id", "content", "created_at", "updated_at",
    },
    "knowledge_chunk": {
        "id", "doc_id", "content", "chunk_index", "embedding", "meta",
        "province", "pathway_id", "source_id", "created_at", "updated_at",
    },
    "qa_log": {
        "id", "user_id", "session_id", "question", "answer", "citations",
        "confidence", "needs_review", "degraded", "status", "created_at",
    },
    "review_task": {
        "id", "qa_log_id", "status", "trigger_reason", "reviewer", "comment",
        "corrected_answer", "created_at", "reviewed_at",
    },
    "admin_user": {"id", "username", "password_hash", "role", "created_at"},
    # 7.6 报考约束（v1.1 新增三张规则表，三表都必须带 year，见 7.6 与 app/models/constraints.py）
    "province_exam_rule": {
        "id", "province", "year", "batch", "mode", "volunteer_count",
        "majors_per_group", "has_adjust", "admit_method", "ratio", "tie_rule",
        "mutex_groups", "collect_count", "source_id", "created_at", "updated_at",
    },
    "subject_requirement": {
        "id", "province", "year", "batch", "school_id", "group_code", "major_id",
        "first_subject", "secondary_subjects", "logic", "source_id",
        "created_at", "updated_at",
    },
    "physical_restriction": {
        "id", "condition", "threshold", "major_category", "major_code", "level",
        "detail", "province", "year", "source_id", "created_at", "updated_at",
    },
    # 7.3 考生档案（0001 建立，0006 按产品书 6.1.4 统一字段名并补齐 v1.1 的 11 个字段）
    "profiles": {
        "user_id", "province", "exam_type", "first_subject", "second_subjects",
        "subject_type", "score", "rank", "household_type", "home_county",
        "home_county_code", "school_years", "enrollment_county", "household_years",
        "enrollment_years", "parent_household_local", "has_national_special",
        "has_local_special", "has_college_special", "preferred_cities",
        "preferred_majors", "tuition_budget", "color_vision", "vision_left",
        "vision_right", "height", "weight", "hepatitis_b", "hearing", "smell",
        "stutter", "batch_preference", "accept_adjustment", "special_marks",
        "preferences", "created_at", "updated_at",
    },
    # 8.1 管理端操作留痕（**第 7 章之外**，为 8.1 验收「操作记录含操作人/时间/动作」新增，
    # 见 app/models/audit.py 与 PR 描述；若队长要求改由结构化日志承载，删表即可）
    "admin_audit_log": {
        "id", "admin_id", "admin_username", "action", "target_type", "target_id",
        "detail", "client_ip", "created_at",
    },
    # 8.3 索引重建任务（**第 7 章之外**，产品书 6.6.4–6.6.5 未定义任务载体，
    # 见 app/models/knowledge.py 与 PR 描述）
    "index_task": {
        "id", "scope", "doc_ids", "incremental", "status", "total", "processed",
        "embedded", "pending_embedding", "failed_chunks", "message", "operator",
        "created_at", "started_at", "finished_at",
    },
}

EXPECTED_TABLES = set(EXPECTED_COLUMNS) | BASE_TABLES

# 第 7 章「关键索引」中明确点名的索引
EXPECTED_INDEXES: dict[str, set[str]] = {
    "school": {"ix_school_province", "ix_school_level", "ix_school_name"},
    "major": {"ix_major_category", "ix_major_name"},
    "school_major_score": {"ix_school_major_score_lookup"},
    "score_segment": {"ix_score_segment_lookup"},
    # 7.6 报考约束三表的关键索引
    "province_exam_rule": {"ix_province_exam_rule_lookup"},
    "subject_requirement": {"ix_subject_requirement_major", "ix_subject_requirement_school"},
    "physical_restriction": {"ix_physical_restriction_condition", "ix_physical_restriction_major"},
}

# 事实表的外键必须指向来源或上游实体
EXPECTED_FOREIGN_KEYS: dict[str, set[str]] = {
    "school_major_score": {"school.id", "major.id", "pathway.id", "source.id"},
    "pathway_eligibility": {"pathway.id", "source.id"},
    "knowledge_chunk": {"knowledge_doc.id", "source.id"},
    "review_task": {"qa_log.id"},
    "user_plan": {"users.id"},
    "qa_log": {"users.id"},
    "admin_audit_log": {"admin_user.id"},
    # 7.6 三表均为事实数据，来源外键非空
    "province_exam_rule": {"source.id"},
    "subject_requirement": {"major.id", "school.id", "source.id"},
    "physical_restriction": {"source.id"},
}


def alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


def test_idempotent_upgrade(cfg: Config) -> None:
    """1.4 验收：迁移脚本可重复执行。"""
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")  # 第二次应为空操作，不应报错


def test_all_tables_present() -> None:
    """表结构与第 7 章一致：20 张新表齐备（外加 8.1 留痕表与 8.3 索引任务表），且没有多余表。"""
    engine = create_engine(os.environ["ZHIXUAN_DATABASE_URL"])
    tables = set(inspect(engine).get_table_names())
    actual = tables - {"alembic_version"}

    missing = EXPECTED_TABLES - actual
    assert not missing, f"缺表：{sorted(missing)}"
    unexpected = actual - EXPECTED_TABLES
    assert not unexpected, f"出现第 7 章之外的表：{sorted(unexpected)}"


def test_columns_match_spec() -> None:
    """逐表核对第 7 章列出的字段是否齐全。"""
    engine = create_engine(os.environ["ZHIXUAN_DATABASE_URL"])
    insp = inspect(engine)
    problems: list[str] = []
    for table, expected in EXPECTED_COLUMNS.items():
        actual = {col["name"] for col in insp.get_columns(table)}
        missing = expected - actual
        if missing:
            problems.append(f"{table} 缺列 {sorted(missing)}")
    assert not problems, "；".join(problems)


def test_indexes_present() -> None:
    """第 7 章点名的关键索引必须存在。"""
    engine = create_engine(os.environ["ZHIXUAN_DATABASE_URL"])
    insp = inspect(engine)
    problems: list[str] = []
    for table, expected in EXPECTED_INDEXES.items():
        actual = {idx["name"] for idx in insp.get_indexes(table)}
        missing = expected - actual
        if missing:
            problems.append(f"{table} 缺索引 {sorted(missing)}")
    assert not problems, "；".join(problems)


def test_foreign_keys_present() -> None:
    """事实表的外键指向正确。"""
    engine = create_engine(os.environ["ZHIXUAN_DATABASE_URL"])
    insp = inspect(engine)
    problems: list[str] = []
    for table, expected in EXPECTED_FOREIGN_KEYS.items():
        actual = {
            f"{fk['referred_table']}.{fk['referred_columns'][0]}"
            for fk in insp.get_foreign_keys(table)
        }
        missing = expected - actual
        if missing:
            problems.append(f"{table} 缺外键 {sorted(missing)}")
    assert not problems, "；".join(problems)


def test_check_constraints_enforced() -> None:
    """年份 CHECK 是「缺来源不进库」（tasks.md 2.6）之外的第二道闸门。"""
    engine = create_engine(os.environ["ZHIXUAN_DATABASE_URL"])
    with engine.begin() as conn:
        try:
            conn.execute(
                text(
                    "INSERT INTO source (source_name, source_url, year, created_at, updated_at) "
                    "VALUES ('测试来源', 'https://example.com', 1800, '2026-01-01', '2026-01-01')"
                )
            )
        except IntegrityError:
            return
        raise AssertionError("年份 1800 应被 CHECK 约束拒绝，实际写入成功")


def test_downgrade_rolls_back(cfg: Config) -> None:
    """downgrade 能干净回滚到 0001，随后可再次升级。"""
    command.downgrade(cfg, "0001_users_profiles")
    engine = create_engine(os.environ["ZHIXUAN_DATABASE_URL"])
    tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
    assert tables == BASE_TABLES, f"回滚后应只剩 {sorted(BASE_TABLES)}，实际 {sorted(tables)}"
    command.upgrade(cfg, "head")  # 再升回来，证明迁移可反复执行


def main() -> None:
    cfg = alembic_config()
    test_idempotent_upgrade(cfg)
    test_all_tables_present()
    test_columns_match_spec()
    test_indexes_present()
    test_foreign_keys_present()
    test_check_constraints_enforced()
    test_downgrade_rolls_back(cfg)
    print(f"migration check passed（{len(EXPECTED_TABLES)} 张表，幂等 + 回滚均通过）")


if __name__ == "__main__":
    main()
