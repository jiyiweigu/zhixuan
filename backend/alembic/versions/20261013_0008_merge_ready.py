"""数据合并准备：放宽录取分外键 + 补院校层次 / 专业组 / 同分人数列

依据 `.workbuddy/scratch/audit/方案_数据合并与装载_20261013.md` 的 C1–C3 与 K1–K2。
背景：数据工程（徐）与数据库（张）两套产出要合并进本套 schema 时，实测有 3 处装不下。

1. **放宽可空（C1/C2）**
   ``school_major_score.school_id`` / ``major_id`` 原为 NOT NULL，但数据工程实测有
   **1,983 行无 school_id（1.71%）**、**2,200 行无 major_id（1.90%）**，合计 4,183 行（3.6%）。
   未匹配的原因已逐条归因（院校库外 / 独立学院 / 军事院校 / 校名脏值 / 分校区；
   试验班与按类招生 / 职业本科专业名 / 院校自设）。
   项目红线是「**宁可缺，不可猜**」，数据侧留 ``null`` 是正确做法，
   因此必须放宽为可空，否则这批行会在装载时整批失败。

2. **补院校层次（C3）**
   ``school`` 增 ``is_985`` / ``is_211`` / ``dual_class``。院校层次是冲稳保推荐与
   家长决策的核心维度；两套数据源中只有一套带该信息，合并在装载层完成。

3. **补院校专业组代码（K1）**
   ``school_major_score`` 增 ``group_code``。河南是「**院校专业组**」志愿模式，
   志愿表按专业组渲染 48 个志愿格，没有该列无法回填志愿表。

4. **补同分人数（K2）**
   ``score_segment`` 增 ``same_score_count``。一分一段表除累计位次外还需「同分多少人」，
   两个数据源都带该字段，此前 schema 未落列。

5. **补一分一段批次（合并时才发现）**
   ``score_segment`` 增 ``batch``。数据工程在其 meta 中明确警示：
   「★ 老高考一分为多段（本科一批/本科二批/专科批），各段累计值连续，
   **合并会丢批次线信息，故必须按 batch 保留**」。河南 2023–2024 为老高考，
   不落该列会把三个批次的分数段压成一份。

6. **补专业简介（合并时才发现）**
   ``major`` 增 ``intro``。数据库侧为 455 个专业提供了简介正文（产品端「专业介绍」
   直接可用），而此前 schema 没有承载列，不补则这批内容只能丢弃。

注：SQLite 不支持 ALTER COLUMN 改可空，故 ``school_major_score`` 走 batch 模式重建表
（Alembic 反射并保留既有外键 / CHECK / 索引，0007 已验证过该路径）。
``school`` / ``score_segment`` / ``major`` 仅新增列，走原生 ADD COLUMN 避免无谓重建。

Revision ID: 0008_merge_ready
Revises: 0007_rule_datasets
Create Date: 2026-10-13 15:35:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0008_merge_ready'
down_revision = '0007_rule_datasets'
branch_labels = None
depends_on = None

# 新增列的长度口径与 app/models/base_data.py 保持一致
_DUAL_CLASS_MAX_LENGTH = 32
_GROUP_CODE_MAX_LENGTH = 32
_BATCH_MAX_LENGTH = 32


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1) school 补院校层次三列（仅新增列，走原生 ADD COLUMN）
    #    NOT NULL 列在 SQLite 下必须带 server_default
    # ------------------------------------------------------------------ #
    op.add_column(
        'school',
        sa.Column('is_985', sa.Boolean(), nullable=False, server_default=sa.text('0')),
    )
    op.add_column(
        'school',
        sa.Column('is_211', sa.Boolean(), nullable=False, server_default=sa.text('0')),
    )
    op.add_column(
        'school',
        sa.Column(
            'dual_class',
            sa.String(length=_DUAL_CLASS_MAX_LENGTH),
            nullable=False,
            server_default='',
        ),
    )

    # ------------------------------------------------------------------ #
    # 2) score_segment 补同分人数 + 批次
    #    - same_score_count 可空：并非所有年份 / 省份都有该口径
    #    - batch 必须保留：老高考一分为多段，合并会丢批次线信息
    # ------------------------------------------------------------------ #
    op.add_column(
        'score_segment',
        sa.Column('same_score_count', sa.Integer(), nullable=True),
    )
    op.add_column(
        'score_segment',
        sa.Column('batch', sa.String(length=_BATCH_MAX_LENGTH), nullable=False, server_default=''),
    )

    # ------------------------------------------------------------------ #
    # 3) major 补专业简介（数据库侧产出的 455 条简介正文）
    # ------------------------------------------------------------------ #
    op.add_column(
        'major',
        sa.Column('intro', sa.Text(), nullable=False, server_default=''),
    )

    # ------------------------------------------------------------------ #
    # 4) school_major_score 增 group_code + 放宽两个外键为可空
    #    （SQLite 改可空需重建表，故与加列合并为一次 batch）
    # ------------------------------------------------------------------ #
    with op.batch_alter_table('school_major_score', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'group_code',
                sa.String(length=_GROUP_CODE_MAX_LENGTH),
                nullable=False,
                server_default='',
            )
        )
        batch_op.alter_column('school_id', existing_type=sa.Integer(), nullable=True)
        batch_op.alter_column('major_id', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table('school_major_score', schema=None) as batch_op:
        # 先删列，再把两个外键收回 NOT NULL（迁移测试库中无数据，可安全收紧）
        batch_op.drop_column('group_code')
        batch_op.alter_column('major_id', existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column('school_id', existing_type=sa.Integer(), nullable=False)

    op.drop_column('major', 'intro')
    op.drop_column('score_segment', 'batch')
    op.drop_column('score_segment', 'same_score_count')

    op.drop_column('school', 'dual_class')
    op.drop_column('school', 'is_211')
    op.drop_column('school', 'is_985')
