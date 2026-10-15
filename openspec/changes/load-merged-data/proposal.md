## Why

整合数据已经在仓库外生成，但导入器要求仓库内 `data/` 目录形态。若直接修改导入器或手工复制，容易破坏既有 schema、位置耦合的 `school_id` 和可重复导入能力。本变更通过可幂等重跑的 staging 脚本完成目录适配，并建立全量装载、行数对账、语义抽查和回归验收流程。

## What Changes

- 新增从外部 `merged/` 目录生成 staging 数据根目录的脚本。
- 新增三步装载操作手册和环境变量说明。
- 装载 8 类当前已有 importer 支持的数据集：source、pathway、pathway_region、pathway_eligibility、province_exam_rule、school、score_segment、school_major_score。
- 对齐并核验每个数据集的 `meta.count`、实际行数和数据库行数。
- 增加清华、北大、郑州大学、null 关联和中外合作办学继承的 SQL 抽查说明。
- 保留未匹配行和已知差异，不修改数据内容、不猜测补全、不修改 schema 或 importer。
- 明确 `major.json` 等尚无 importer 的数据集暂不纳入本次装载，另立后续任务。

## Capabilities

### New Capabilities

- `merged-data-staging`: 将外部整合数据按 importer 约定组织为可重复使用的 staging 根目录。
- `database-load-validation`: 定义全量装载、逐表对账、语义抽查和回归验收标准。

### Modified Capabilities

- 无

## Impact

- 新增 `data/scripts/stage_load_root.py`。
- 新增 `docs/装载操作手册.md` 和装载报告模板。
- 影响本地 SQLite/PostgreSQL 数据装载流程，但不改变 API DTO、模型和 Alembic schema。
- 外部数据目录不入仓库，仓库只提交脚本、文档和小型样本。
