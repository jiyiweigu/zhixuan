"""报考约束：补齐契约 8.7 的三张逻辑表 + province_exam_rule 收敛到 batch_code / exam_type

依据 docs/api-contract.md v1.2：

- 8.7 要求 ``admission_requirement`` / ``major_tuition`` / ``rule_dataset_status`` 三张逻辑表
  （承载 8.6 ``enrollment_notes``、闸门 4 学费、8.1 ``data_status`` 的唯一来源）；
- 8.3/8.7 要求 ``province_exam_rule`` 的唯一键为 ``(province_code, year, batch_code, exam_type)``，
  ``batch`` 仅作展示（河南「普通本科批」/江西「本科批次」经 batch_code 归一后不得再区分）；
- 数据源列名 ``category_group`` 导入时必须映射为 ``exam_type``（本轮先落列，映射在导入脚本）。

``province_code`` 同时补到 ``subject_requirement`` / ``physical_restriction``，
让规则可按两位省代码直接检索（8.3/8.6 的入参口径）。

注：SQLite 下新增 NOT NULL 列必须带 server_default；带 CHECK 的新列与唯一键变更
由 batch 模式重建表完成（Alembic 会反射并保留既有外键与 CHECK）。

Revision ID: 0007_rule_datasets
Revises: 0006_constraint_tables
Create Date: 2026-10-13 11:30:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0007_rule_datasets'
down_revision = '0006_constraint_tables'
branch_labels = None
depends_on = None

# 与 app/models/constants.py 口径一致（迁移不 import app 代码）
_YEAR_CHECK = "year BETWEEN 2000 AND 2100"
_LEVEL_SQL = "'reject', 'not_suitable'"
_EXAM_TYPE_SQL = "'普通', '艺术', '体育'"
_DATA_STATUS_SQL = "'available', 'partial', 'schema_only', 'unavailable'"
_REQUIREMENT_TYPE_SQL = (
    "'single_subject', 'language', 'gender', "
    "'interview', 'political_review', 'physical_test'"
)


def _audit_columns() -> tuple[sa.Column, sa.Column]:
    """审计列：ORM 侧由 utcnow 填充，故迁移不设 server_default。

    每次返回全新 Column 实例——同一个 Column 对象不能挂到多张表上。
    """
    return (
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )



def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1) province_exam_rule 收敛到 (province_code, year, batch_code, exam_type)
    # ------------------------------------------------------------------ #
    # 先删旧唯一索引，避免 batch 重建表时索引名冲突
    op.drop_index('ix_province_exam_rule_lookup', table_name='province_exam_rule')

    with op.batch_alter_table('province_exam_rule', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('province_code', sa.String(length=32), nullable=False, server_default='')
        )
        batch_op.add_column(
            sa.Column('batch_code', sa.String(length=32), nullable=False, server_default='')
        )
        batch_op.add_column(
            sa.Column('exam_type', sa.String(length=8), nullable=False, server_default='普通')
        )
        batch_op.create_check_constraint(
            'ck_province_exam_rule_exam_type_values', f'exam_type IN ({_EXAM_TYPE_SQL})'
        )

    op.create_index(
        'ix_province_exam_rule_lookup', 'province_exam_rule',
        ['province_code', 'year', 'batch_code', 'exam_type'], unique=True,
    )

    # ------------------------------------------------------------------ #
    # 2) subject_requirement / physical_restriction 补 province_code
    #    （SQLite 支持原生 ADD COLUMN，不走 batch，避免重建表）
    # ------------------------------------------------------------------ #
    op.add_column(
        'subject_requirement',
        sa.Column('province_code', sa.String(length=32), nullable=False, server_default=''),
    )
    op.add_column(
        'physical_restriction',
        sa.Column('province_code', sa.String(length=32), nullable=False, server_default=''),
    )

    # ------------------------------------------------------------------ #
    # 3) admission_requirement（契约 8.7）
    # ------------------------------------------------------------------ #
    op.create_table(
        'admission_requirement',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('province_code', sa.String(length=32), nullable=False, server_default=''),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=True),
        sa.Column('major_id', sa.Integer(), nullable=True),
        sa.Column('requirement_type', sa.String(length=32), nullable=False),
        sa.Column('requirement_value', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('level', sa.String(length=16), nullable=False, server_default='reject'),
        sa.Column('detail', sa.Text(), nullable=False, server_default=''),
        sa.Column('source_id', sa.Integer(), nullable=False),
        *_audit_columns(),
        sa.CheckConstraint(_YEAR_CHECK, name=op.f('ck_admission_requirement_year_range')),
        sa.CheckConstraint(
            f'requirement_type IN ({_REQUIREMENT_TYPE_SQL})',
            name=op.f('ck_admission_requirement_requirement_type_values'),
        ),
        sa.CheckConstraint(
            f'level IN ({_LEVEL_SQL})', name=op.f('ck_admission_requirement_level_values')
        ),
        sa.ForeignKeyConstraint(
            ['major_id'], ['major.id'], name=op.f('fk_admission_requirement_major_id')
        ),
        sa.ForeignKeyConstraint(
            ['school_id'], ['school.id'], name=op.f('fk_admission_requirement_school_id')
        ),
        sa.ForeignKeyConstraint(
            ['source_id'], ['source.id'], name=op.f('fk_admission_requirement_source_id')
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_admission_requirement')),
    )
    op.create_index(
        'ix_admission_requirement_lookup', 'admission_requirement',
        ['province_code', 'year', 'school_id', 'major_id', 'requirement_type'], unique=True,
    )

    # ------------------------------------------------------------------ #
    # 4) major_tuition（契约 8.7；闸门 4）
    # ------------------------------------------------------------------ #
    op.create_table(
        'major_tuition',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('province_code', sa.String(length=32), nullable=False, server_default=''),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=True),
        sa.Column('major_id', sa.Integer(), nullable=True),
        sa.Column('amount', sa.Float(), nullable=True),
        sa.Column('currency', sa.String(length=8), nullable=False, server_default='CNY'),
        sa.Column('period', sa.String(length=8), nullable=False, server_default='year'),
        sa.Column('ownership', sa.String(length=32), nullable=False, server_default=''),
        sa.Column('note', sa.Text(), nullable=False, server_default=''),
        sa.Column('source_id', sa.Integer(), nullable=False),
        *_audit_columns(),
        sa.CheckConstraint(_YEAR_CHECK, name=op.f('ck_major_tuition_year_range')),
        sa.ForeignKeyConstraint(['major_id'], ['major.id'], name=op.f('fk_major_tuition_major_id')),
        sa.ForeignKeyConstraint(['school_id'], ['school.id'], name=op.f('fk_major_tuition_school_id')),
        sa.ForeignKeyConstraint(['source_id'], ['source.id'], name=op.f('fk_major_tuition_source_id')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_major_tuition')),
    )
    op.create_index(
        'ix_major_tuition_lookup', 'major_tuition',
        ['province_code', 'year', 'school_id', 'major_id'], unique=True,
    )

    # ------------------------------------------------------------------ #
    # 5) rule_dataset_status（契约 8.7；8.1 data_status 的唯一来源，无来源三要素）
    # ------------------------------------------------------------------ #
    op.create_table(
        'rule_dataset_status',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('province_code', sa.String(length=32), nullable=False, server_default=''),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('batch_code', sa.String(length=32), nullable=False, server_default=''),
        sa.Column('exam_type', sa.String(length=8), nullable=False, server_default='普通'),
        sa.Column('dataset', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='schema_only'),
        sa.Column('note', sa.Text(), nullable=False, server_default=''),
        *_audit_columns(),
        sa.CheckConstraint(_YEAR_CHECK, name=op.f('ck_rule_dataset_status_year_range')),
        sa.CheckConstraint(
            f'status IN ({_DATA_STATUS_SQL})', name=op.f('ck_rule_dataset_status_status_values')
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_rule_dataset_status')),
    )
    op.create_index(
        'ix_rule_dataset_status_lookup', 'rule_dataset_status',
        ['province_code', 'year', 'batch_code', 'exam_type', 'dataset'], unique=True,
    )


def downgrade() -> None:
    op.drop_index('ix_rule_dataset_status_lookup', table_name='rule_dataset_status')
    op.drop_table('rule_dataset_status')

    op.drop_index('ix_major_tuition_lookup', table_name='major_tuition')
    op.drop_table('major_tuition')

    op.drop_index('ix_admission_requirement_lookup', table_name='admission_requirement')
    op.drop_table('admission_requirement')

    op.drop_column('physical_restriction', 'province_code')
    op.drop_column('subject_requirement', 'province_code')

    op.drop_index('ix_province_exam_rule_lookup', table_name='province_exam_rule')
    with op.batch_alter_table('province_exam_rule', schema=None) as batch_op:
        batch_op.drop_constraint('ck_province_exam_rule_exam_type_values', type_='check')
        batch_op.drop_column('exam_type')
        batch_op.drop_column('batch_code')
        batch_op.drop_column('province_code')
    op.create_index(
        'ix_province_exam_rule_lookup', 'province_exam_rule',
        ['province', 'year', 'batch'], unique=True,
    )
