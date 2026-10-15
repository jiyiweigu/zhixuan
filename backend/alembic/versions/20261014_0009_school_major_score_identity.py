"""录取分身份列：院校专业组 + 专业代号 / 专业名 + 考试制度

承接 backend 侧在 PR #12 中给出的建模判断（已由队长侧逐条独立复核认可）：
一行录取分的真实身份是「**专业组 + 专业**」，且老高考「文理科」与新高考
「3+1+2」不得跨制度比较。此前 schema 无承载列。

1. **身份列** ``group_code`` / ``major_code`` / ``major_name`` / ``exam_system``
   - ``group_code`` **已由 0008 加入**（河南为院校专业组志愿模式），本迁移不再重复；
   - 本迁移补 ``major_code`` / ``major_name`` / ``exam_system`` 三列。
   依据 ``data/samples/school_major_score.json`` 的实例：官方样本
   「河南/2025/本科批/物理类/560 分/101279 位次」**出现两行，仅专业不同**
   （``major_code`` 14 公共管理类 / 12 国际商务）。缺这两列则既无法区分行、
   也无法定义幂等键。``exam_system`` 是数据侧 §2.3 的硬要求。

2. **身份查询索引** ``ix_school_major_score_identity``
   覆盖 ``(school_id, province, year, batch, subject_type, group_code, major_code)``，
   与导入层按身份键 upsert 的取数路径一致。

注：本迁移**只新增列与索引**，不含表重建，故不涉及 0008 那条 ``copy_from`` 路径。
新增列均为 NOT NULL，SQLite 下必须带 ``server_default``。

⚠️ 与 PR #12 的关系：PR #12 原含 ``0008_score_segment_batch``（加
``score_segment.batch``）与 ``0009_school_major_score_identity``（放宽两个外键 +
加 group_code/major_code/major_name/exam_system）。其中 ``score_segment.batch``、
两个外键放宽、``group_code`` **均已由 0008_merge_ready 完成**，若两线同时合入会
形成 Alembic 双 head 并触发 ``duplicate column name``。故由本迁移在 develop 侧
承接「三条真正缺的身份列 + 索引」，PR #12 只需删除其两个迁移文件、保留导入层。

Revision ID: 0009_school_major_score_identity
Revises: 0008_merge_ready
Create Date: 2026-10-14 14:30:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0009_school_major_score_identity'
down_revision = '0008_merge_ready'
branch_labels = None
depends_on = None

# 与 app/models/base_data.py 保持一致
_MAJOR_CODE_MAX_LENGTH = 32
_MAJOR_NAME_MAX_LENGTH = 200
_EXAM_SYSTEM_MAX_LENGTH = 16

_NEW_COLUMNS = (
    ('major_code', sa.String(length=_MAJOR_CODE_MAX_LENGTH),
     '专业代号；将来据此回挂 major_id'),
    ('major_name', sa.String(length=_MAJOR_NAME_MAX_LENGTH), '专业名称'),
    ('exam_system', sa.String(length=_EXAM_SYSTEM_MAX_LENGTH),
     '考试制度：文理科 / 3+1+2（跨制度不得比较）'),
)

_INDEX_NAME = 'ix_school_major_score_identity'
_INDEX_COLUMNS = ['school_id', 'province', 'year', 'batch', 'subject_type',
                  'group_code', 'major_code']


def upgrade() -> None:
    for name, type_, comment in _NEW_COLUMNS:
        op.add_column(
            'school_major_score',
            sa.Column(name, type_, nullable=False, server_default='', comment=comment),
        )
    op.create_index(_INDEX_NAME, 'school_major_score', _INDEX_COLUMNS)


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name='school_major_score')
    for name, _type, _comment in reversed(_NEW_COLUMNS):
        op.drop_column('school_major_score', name)
