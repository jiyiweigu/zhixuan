## Context

当前仓库已有 `services/corpus.py`、`services/indexing.py`、`KnowledgeChunk.embedding` JSON 列和 `IndexTask`，索引服务已经提供 `register_embedder` 注入点，并在未注入时以 partial 状态如实结束。当前 Alembic head 是 `0009_school_major_score_identity`，不能照搬任务提示词中的日期 revision。配置集中在 `app/core/config.py`，默认数据库为 SQLite。

## Goals / Non-Goals

**Goals:**

- 以最小改动接入现有 indexing 编排，不另起索引流程。
- 让默认环境 Fake embedding 可运行且测试稳定。
- 为 BGE、远程兼容 API、SQLite 向量检索和未来 pgvector 留出适配边界。
- 让任务进度和失败信息可观察。

**Non-Goals:**

- 本变更不实现 Reranker、Qwen 生成、完整 BM25+RRF 问答链路。
- 不强制安装或下载 sentence-transformers、pgvector、numpy 模型包。
- 不修改 `docs/api-contract.md`、已有知识模型字段语义或 `services/qa.py`。

## Decisions

1. **复用注入点**：Embedder 通过 `register_embedder` 注册，适配器把批量 API 转换为现有索引服务可消费的单条 callable，保持旧测试兼容。
2. **Fake 优先**：默认由环境变量选择 backend；未配置时 Fake，避免开发和 CI 受网络/GPU影响。
3. **依赖可选**：BGE 实现延迟导入本地模型库，远程实现使用标准 HTTP；pgvector 仅在 PostgreSQL 路径导入，SQLite 不因缺少可选依赖失败。
4. **维度校验**：配置默认 512；落库前检查向量长度并 L2 归一化，维度不符作为该 chunk 失败原因。
5. **迁移基线**：迁移以实际 head `0009_school_major_score_identity` 为 down_revision；SQLite 保留 JSON，PostgreSQL 将同一 embedding 列转换为 Vector(512) 并创建 HNSW 索引。
6. **BM25 最小实现**：先采用无额外中文分词依赖的字符/词元计分，输出统一 RetrievalHit；后续评测再决定是否引入分词库。

## Risks / Trade-offs

- [可选模型依赖安装复杂] → 延迟导入并保留 Fake 路径。
- [SQLite 内存检索不适合大规模] → 仅作为开发/小规模模式，生产使用 pgvector。
- [历史迁移并行冲突] → 实现前重新确认 Alembic head，迁移只做幂等的能力增量。
- [Fake 向量不代表语义质量] → 所有 Fake 输出标记演示，仅用于结构与流程测试。

## Migration Plan

1. 先实现协议、Fake 和 SQLite 检索，运行离线测试。
2. 接入 indexing 注入、批处理和失败记录。
3. 添加配置和可选依赖，再实现 PG 迁移。
4. 在有模型与数据后单独验证 BGE，不改变默认测试路径。

## Open Questions

- 生产 embedding 模型最终使用本地 BGE 还是兼容 API，由部署资源和数据负责人确认。
- PostgreSQL/pgvector 迁移还需在真实 PostgreSQL 环境演练；当前离线回归仅验证 SQLite 分支。
