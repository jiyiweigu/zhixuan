## 1. Staging 脚本

- [x] 1.1 创建 `data/scripts/stage_load_root.py`，支持默认路径和 `--merged-root`、`--output-root` 参数。
- [x] 1.2 建立 8 类数据集到 staging 目录的固定映射。
- [x] 1.3 对文件存在性、JSON、`target_table`、`meta.count` 和记录键执行校验。
- [x] 1.4 对 `school.json`、`score_segment.json`、`school_major_score.json` 保持原始顺序并映射为 importer 需要的文件名。
- [x] 1.5 增加幂等重跑检查和清晰的复制/计数输出。

## 2. 装载操作手册

- [x] 2.1 创建 `docs/装载操作手册.md`，写明前置条件、环境变量和三条快速命令。
- [x] 2.2 记录支持装载的数据集、期望行数和暂不接入的数据集。
- [x] 2.3 记录空库迁移、全量导入、重复导入和失败处理方式。

## 3. 对账与语义验收

- [x] 3.1 增加逐表计数 SQL/脚本，输出 expected、actual 和 delta。
- [x] 3.2 增加学校层次、null 关联、郑州大学中外合作办学继承的 SQL 抽查。
- [x] 3.3 登记 39 个未知 school_id、1983 个空 school_id、2200 个空 major_id 等已知差异。
- [x] 3.4 记录 major=938 已有 importer，单列对账，不并入 8 类验收口径。

## 4. 回归与交接

- [x] 4.1 运行 `python test_importers.py` 和 `python test_models.py`。
- [x] 4.2 在空 SQLite 数据库完成迁移、staging、导入和重复导入验证。（2026-10-15 实测：9 表全对、悬空外键 0、二次执行幂等，见 `docs/装载验收报告_20261015.md`）
- [x] 4.3 生成装载报告模板，供 PR 描述粘贴逐表行数和 SQL 结果。
- [x] 4.4 检查仓库不包含外部数据本体、密钥、数据库文件或临时 staging。
- [x] 4.5 准备 `chore/load-merged` → `develop` 的 PR 交接说明和提交信息。

