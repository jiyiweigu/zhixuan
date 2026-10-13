"""数据访问层。

- base     : ORM 基类与命名约定
- session  : 引擎、会话与依赖注入入口

表结构变更一律通过 alembic 迁移（tasks.md 1.4）：
    cd backend && .venv/Scripts/alembic upgrade head
"""
