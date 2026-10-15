## Why

项目已有语料切块、索引任务和 `register_embedder` 注入点，但 embedding 仍未接入：默认开发环境不能稳定完成向量化，SQLite 与 PostgreSQL 的存储路径也没有统一适配层。需要先建立离线可测、可切换的 embedding 基建，供后续混合检索和 RAG 使用。

## What Changes

- 在现有索引服务注入点上定义 Embedder 适配器协议。
- 提供默认离线 `FakeEmbedder`、可选本地 `BgeEmbedder` 和 OpenAI 兼容远程实现。
- 增加 SQLite JSON 与 PostgreSQL pgvector 的双模式存储/检索方案。
- 打通切块、批量向量化、落库和索引任务进度，单条失败可记录并继续。
- 增加轻量 BM25 基线接口供后续混合检索使用。
- 增加不联网、不使用 GPU 的 embedding 测试。

## Capabilities

### New Capabilities

- `embedding-infrastructure`: 定义 embedding 适配器、双数据库模式、索引流程和离线测试契约。

### Modified Capabilities

- 无

## Impact

- 主要影响 `backend/app/rag/`、现有 `backend/app/services/indexing.py`、配置、依赖和 Alembic 迁移。
- 复用现有 `KnowledgeChunk.embedding` JSON 占位和 `IndexTask`，不删除现有列或重写语料服务。
- PostgreSQL 向量类型和 pgvector 依赖必须可选，默认 SQLite 测试不得要求 PostgreSQL、模型文件或 API Key。
- 迁移必须以当前实际 Alembic head `0009_school_major_score_identity` 为依据，不能盲用任务文档中的日期字符串。
