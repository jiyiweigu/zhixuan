## Context

现有导入入口 `backend/app/services/importers/__main__.py` 已定义依赖顺序和 8 类数据集路径。外部整合目录按目标表平铺文件，顶层结构和 importer 期望的目录结构不同，但 JSON 内容已经按表对齐。`school_major_score.school_id` 与院校表行序号存在位置耦合，必须使用原始院校文件并保证不改顺序。

## Goals / Non-Goals

**Goals:**

- 让同一份外部 merged 数据可以稳定生成 staging 根目录并重复导入。
- 在空库迁移后跑通全量导入，生成可审阅的逐表对账和语义抽查结果。
- 保留 null、未匹配和 dangling 数据并登记差异。

**Non-Goals:**

- 不修改 importer 解析逻辑、模型、Alembic 迁移和 API 契约。
- 不把 15.8MB+ 数据本体提交进仓库。
- 不在本次接入 major、school_major_plan、school_profile、school_life 等没有现成 importer 的数据集。

## Decisions

1. **复制而非符号链接**：Windows 环境统一复制，避免权限和跨盘链接问题；脚本覆盖目标文件并保持幂等。
2. **显式映射表**：脚本内维护 source 文件到 staging 文件的固定映射，并对 score_segment、school_major_score 使用目录形态。
3. **输入校验**：复制前检查文件存在，复制后解析 JSON、检查顶层记录键、`meta.target_table` 和 `meta.count`。
4. **行数验收**：预期行数来自外部 `_merge_summary.json`，数据库计数必须精确一致；不通过则停止并报告，不删行凑数。
5. **数据库执行顺序**：`alembic upgrade head` → staging → `python -m app.services.importers`；导入器内部保持 source、pathway、关联字典、school、score_segment、school_major_score 顺序。
6. **差异处理**：未知 school_id、未匹配 major_id、dangling pathway 和合并 exam_type 只记录在报告，不在本次任务猜测修复。

## Risks / Trade-offs

- [外部文件缺失或 meta.count 不一致] → staging 脚本在复制前失败并列出文件。
- [院校文件顺序被改变造成 school_id 错位] → 只复制原始 school.json 内容为 schools_merged.json，不排序、不重写 records。
- [数据库重复导入] → 使用现有 importer 的幂等逻辑，连续执行后新增数应为 0。
- [major=938 无 importer] → 在报告中单独标记为未纳入本任务，不把它伪装成已装载。

## Migration Plan

1. 生成 staging 并保存脚本输出。
2. 对空 SQLite 或 PostgreSQL 执行 `alembic upgrade head`。
3. 设置 `ZHIXUAN_DATA_ROOT` 运行导入入口。
4. 执行计数 SQL、抽查 SQL 和两组回归脚本。
5. 将报告放入 PR 描述；失败时保留日志和差异，不合并为“部分成功”。

## Open Questions

- `major.json` 的独立 importer 由哪个后续任务负责，需要另行排期。
- `pathway_eligibility` 的 `general-batch` dangling id 和艺术/体育合并规则由产品负责人裁定。
