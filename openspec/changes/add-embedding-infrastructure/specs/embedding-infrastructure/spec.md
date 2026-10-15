## ADDED Requirements

### Requirement: Embedder adapter contract
系统 SHALL 提供统一的 Embedder 协议，支持批量文本输入并返回等数量、固定维度的浮点向量；系统 SHALL 提供 Fake、BGE 本地和 OpenAI 兼容三种实现。

#### Scenario: Offline default
- **WHEN** 未配置模型、API 地址或密钥
- **THEN** 系统使用确定性的 FakeEmbedder，记录“当前为演示实现”，且不联网、不下载模型。

### Requirement: Dual storage mode
系统 SHALL 在 SQLite 模式使用现有 JSON embedding 列和内存余弦相似度，在 PostgreSQL 模式支持 pgvector 向量列/索引；SQLite 开发测试 SHALL NOT 强制依赖 pgvector 或 PostgreSQL。

#### Scenario: Switch database
- **WHEN** 运行配置从 SQLite 切换到 PostgreSQL
- **THEN** embedding 适配层保持相同接口，数据库迁移按当前 Alembic head 增加向量能力。

### Requirement: Indexing integration
系统 SHALL 复用 `services.indexing.register_embedder`，完成切块到向量落库的批处理，并记录 processed、embedded、pending、failed 和失败原因；单条 chunk 失败 SHALL NOT 中断整批任务。

#### Scenario: Partial batch failure
- **WHEN** 一条 chunk 向量化失败
- **THEN** 其余 chunk 继续处理，索引任务结束状态和失败原因如实记录。

### Requirement: Retrieval baseline
系统 SHALL 提供 SQLite 可用的余弦相似度 top-k 检索和轻量 BM25 关键词检索接口，供后续 RRF 混合检索调用。

#### Scenario: Similarity top-k
- **WHEN** 查询向量与已向量化 chunk 进行检索
- **THEN** 返回按相似度降序排列的 top-k，并保留 chunk 标识和来源元数据。

### Requirement: Offline verification
系统 SHALL 提供不联网、不使用 GPU、不下载模型的测试，覆盖 Fake 确定性、批量向量化、SQLite 检索、任务状态和失败继续处理。

#### Scenario: Clean test environment
- **WHEN** 测试环境没有 PostgreSQL、模型文件和 API Key
- **THEN** embedding 测试仍可完整运行。
