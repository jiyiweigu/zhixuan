"""建立用户表与考生档案表（tasks.md 3.1、3.4、3.5）

Revision ID: 0001_users_profiles
Revises:
Create Date: 2026-10-11

说明：
- 本迁移是数据库基线，覆盖账号与档案两张表；
- 口令只存 password_hash（PBKDF2 加盐哈希），结构中不存在明文字段；
- 其余事实表（院校 / 专业 / 录取分 / 一分一段 / 知识库 / 问答日志 / 审核任务等，
  tasks.md 1.4 与 design.md 第十二章）将在后续迁移中随数据工程进度补齐；
  向量列（pgvector）将在知识库切片表落地时一并加入。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_users_profiles"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=64), nullable=False, comment="用户 ID，形如 u_xxxx"),
        sa.Column("username", sa.String(length=50), nullable=False, comment="登录用户名，唯一"),
        sa.Column(
            "password_hash",
            sa.String(length=255),
            nullable=False,
            comment="PBKDF2 加盐哈希，禁止存放明文",
        ),
        sa.Column("status", sa.String(length=16), nullable=False, comment="active / deleted"),
        sa.Column(
            "is_admin",
            sa.Boolean(),
            nullable=False,
            comment="管理端鉴权预留（tasks.md 8.1）",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(
        op.f("ix_users_username"), "users", ["username"], unique=True
    )

    op.create_table(
        "profiles",
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("province", sa.String(length=20), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("subject_type", sa.String(length=20), nullable=False),
        sa.Column("household_type", sa.String(length=8), nullable=False),
        sa.Column("household_county", sa.String(length=50), nullable=False),
        sa.Column("enrollment_county", sa.String(length=50), nullable=False),
        sa.Column("household_years", sa.Integer(), nullable=False),
        sa.Column("enrollment_years", sa.Integer(), nullable=False),
        sa.Column("parent_household_local", sa.Boolean(), nullable=True),
        sa.Column("special_marks", sa.JSON(), nullable=False),
        sa.Column("preferences", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_profiles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_profiles")),
    )


def downgrade() -> None:
    op.drop_table("profiles")
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_table("users")
