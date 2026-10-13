"""报考约束：新增三张规则表 + 考生档案补齐 v1.1 字段

依据《开发产品书_智选志愿》v1.1：
- 7.6 新增 province_exam_rule / subject_requirement / physical_restriction（三表都带 year）
- 6.1.4 / 7.3 考生档案（profiles）扩 11 个字段并统一字段名
  （household_county → home_county，与前端 types/api.d.ts 的 Profile 对齐）

三张规则表的查询索引按 7.6 建：
- province_exam_rule  (province, year, batch) 唯一
- subject_requirement (province, year, major_id) / (school_id, year)
- physical_restriction (condition) / (major_category, major_code)

注：SQLite 下 profiles 的列重命名与新增由 batch 模式重建表完成。

Revision ID: 0006_constraint_tables
Revises: 0005_index_task
Create Date: 2026-10-12 20:20:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0006_constraint_tables'
down_revision = '0005_index_task'
branch_labels = None
depends_on = None

# 年份区间与 app/core/dataset.py、app/models/constants.py 口径一致（迁移不 import app 代码）
_YEAR_CHECK = "year BETWEEN 2000 AND 2100"


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1) 三张规则表（产品书 7.6）
    # ------------------------------------------------------------------ #
    op.create_table(
        'province_exam_rule',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('province', sa.String(length=20), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('batch', sa.String(length=32), nullable=False),
        sa.Column('mode', sa.String(length=16), nullable=False),
        sa.Column('volunteer_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('majors_per_group', sa.Integer(), nullable=True),
        sa.Column('has_adjust', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('admit_method', sa.String(length=16), nullable=False, server_default='parallel'),
        sa.Column('ratio', sa.String(length=32), nullable=False, server_default='1:1'),
        sa.Column('tie_rule', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('mutex_groups', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('collect_count', sa.Integer(), nullable=True),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint(_YEAR_CHECK, name=op.f('ck_province_exam_rule_year_range')),
        sa.CheckConstraint(
            "mode IN ('group', 'major_school', 'school_major')",
            name=op.f('ck_province_exam_rule_mode_values'),
        ),
        sa.ForeignKeyConstraint(['source_id'], ['source.id'], name=op.f('fk_province_exam_rule_source_id')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_province_exam_rule')),
    )
    op.create_index(
        'ix_province_exam_rule_lookup', 'province_exam_rule',
        ['province', 'year', 'batch'], unique=True,
    )

    op.create_table(
        'subject_requirement',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('province', sa.String(length=20), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('batch', sa.String(length=32), nullable=False, server_default=''),
        sa.Column('school_id', sa.Integer(), nullable=True),
        sa.Column('group_code', sa.String(length=32), nullable=True),
        sa.Column('major_id', sa.Integer(), nullable=True),
        sa.Column('first_subject', sa.String(length=16), nullable=False, server_default=''),
        sa.Column('secondary_subjects', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('logic', sa.String(length=8), nullable=False, server_default='all'),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint(_YEAR_CHECK, name=op.f('ck_subject_requirement_year_range')),
        sa.CheckConstraint("logic IN ('all', 'any')", name=op.f('ck_subject_requirement_logic_values')),
        sa.ForeignKeyConstraint(['major_id'], ['major.id'], name=op.f('fk_subject_requirement_major_id')),
        sa.ForeignKeyConstraint(['school_id'], ['school.id'], name=op.f('fk_subject_requirement_school_id')),
        sa.ForeignKeyConstraint(['source_id'], ['source.id'], name=op.f('fk_subject_requirement_source_id')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_subject_requirement')),
    )
    op.create_index(
        'ix_subject_requirement_major', 'subject_requirement',
        ['province', 'year', 'major_id'], unique=False,
    )
    op.create_index(
        'ix_subject_requirement_school', 'subject_requirement',
        ['school_id', 'year'], unique=False,
    )

    op.create_table(
        'physical_restriction',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('condition', sa.String(length=64), nullable=False),
        sa.Column('threshold', sa.String(length=128), nullable=False, server_default=''),
        sa.Column('major_category', sa.String(length=50), nullable=False, server_default=''),
        sa.Column('major_code', sa.String(length=32), nullable=False, server_default=''),
        sa.Column('level', sa.String(length=16), nullable=False),
        sa.Column('detail', sa.Text(), nullable=False, server_default=''),
        sa.Column('province', sa.String(length=20), nullable=False, server_default=''),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint(_YEAR_CHECK, name=op.f('ck_physical_restriction_year_range')),
        sa.CheckConstraint(
            "level IN ('reject', 'not_suitable')",
            name=op.f('ck_physical_restriction_level_values'),
        ),
        sa.ForeignKeyConstraint(['source_id'], ['source.id'], name=op.f('fk_physical_restriction_source_id')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_physical_restriction')),
    )
    op.create_index('ix_physical_restriction_condition', 'physical_restriction', ['condition'], unique=False)
    op.create_index(
        'ix_physical_restriction_major', 'physical_restriction',
        ['major_category', 'major_code'], unique=False,
    )

    # ------------------------------------------------------------------ #
    # 2) 考生档案（profiles）补齐 v1.1 字段
    # ------------------------------------------------------------------ #
    with op.batch_alter_table('profiles', schema=None) as batch_op:
        # 字段名对齐产品书 6.1.4 / 前端 types
        batch_op.alter_column(
            'household_county', new_column_name='home_county',
            existing_type=sa.String(length=50), nullable=False,
        )
        # 基本
        batch_op.add_column(sa.Column('exam_type', sa.String(length=8), nullable=False, server_default='普通'))
        batch_op.add_column(sa.Column('first_subject', sa.String(length=16), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('second_subjects', sa.JSON(), nullable=False, server_default='[]'))
        batch_op.add_column(sa.Column('rank', sa.Integer(), nullable=True))
        # 户籍与学籍
        batch_op.add_column(sa.Column('home_county_code', sa.String(length=16), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('school_years', sa.Integer(), nullable=False, server_default='0'))
        # 专项资格写回
        batch_op.add_column(sa.Column('has_national_special', sa.Boolean(), nullable=False, server_default=sa.text('0')))
        batch_op.add_column(sa.Column('has_local_special', sa.Boolean(), nullable=False, server_default=sa.text('0')))
        batch_op.add_column(sa.Column('has_college_special', sa.Boolean(), nullable=False, server_default=sa.text('0')))
        # 偏好
        batch_op.add_column(sa.Column('preferred_cities', sa.JSON(), nullable=False, server_default='[]'))
        batch_op.add_column(sa.Column('preferred_majors', sa.JSON(), nullable=False, server_default='[]'))
        batch_op.add_column(sa.Column('tuition_budget', sa.Integer(), nullable=True))
        # 体检（v1.1 新增 9 项）
        batch_op.add_column(sa.Column('color_vision', sa.String(length=24), nullable=True))
        batch_op.add_column(sa.Column('vision_left', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('vision_right', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('height', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('weight', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('hepatitis_b', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('hearing', sa.String(length=8), nullable=False, server_default='未填'))
        batch_op.add_column(sa.Column('smell', sa.String(length=8), nullable=False, server_default='未填'))
        batch_op.add_column(sa.Column('stutter', sa.String(length=8), nullable=False, server_default='未填'))
        # 志愿倾向
        batch_op.add_column(sa.Column('batch_preference', sa.JSON(), nullable=False, server_default='[]'))
        batch_op.add_column(sa.Column('accept_adjustment', sa.Boolean(), nullable=True))

    # ------------------------------------------------------------------ #
    # 3) 专业基础库（major）补齐 v1.1 字段（产品书 7.1 后半段）
    #    闸门 4 用 tuition / ownership 分档，6.2.9 用单科 / 语种 / 性别 / 面试
    # ------------------------------------------------------------------ #
    with op.batch_alter_table('major', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tuition', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('ownership', sa.String(length=32), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('duration', sa.String(length=16), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('campus', sa.String(length=100), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('is_category', sa.Boolean(), nullable=False, server_default=sa.text('0')))
        batch_op.add_column(sa.Column('single_subject_req', sa.String(length=100), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('language_req', sa.String(length=64), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('gender_req', sa.String(length=32), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('interview_required', sa.Boolean(), nullable=False, server_default=sa.text('0')))


def downgrade() -> None:
    with op.batch_alter_table('major', schema=None) as batch_op:
        for column in (
            'interview_required', 'gender_req', 'language_req', 'single_subject_req',
            'is_category', 'campus', 'duration', 'ownership', 'tuition',
        ):
            batch_op.drop_column(column)

    with op.batch_alter_table('profiles', schema=None) as batch_op:
        for column in (
            'accept_adjustment', 'batch_preference', 'stutter', 'smell', 'hearing',
            'hepatitis_b', 'weight', 'height', 'vision_right', 'vision_left',
            'color_vision', 'tuition_budget', 'preferred_majors', 'preferred_cities',
            'has_college_special', 'has_local_special', 'has_national_special',
            'school_years', 'home_county_code', 'rank', 'second_subjects',
            'first_subject', 'exam_type',
        ):
            batch_op.drop_column(column)
        batch_op.alter_column(
            'home_county', new_column_name='household_county',
            existing_type=sa.String(length=50), nullable=False,
        )

    op.drop_index('ix_physical_restriction_major', table_name='physical_restriction')
    op.drop_index('ix_physical_restriction_condition', table_name='physical_restriction')
    op.drop_table('physical_restriction')

    op.drop_index('ix_subject_requirement_school', table_name='subject_requirement')
    op.drop_index('ix_subject_requirement_major', table_name='subject_requirement')
    op.drop_table('subject_requirement')

    op.drop_index('ix_province_exam_rule_lookup', table_name='province_exam_rule')
    op.drop_table('province_exam_rule')
