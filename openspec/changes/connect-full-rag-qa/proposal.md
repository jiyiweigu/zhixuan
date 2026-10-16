## Why

T2 已完成 embedding、向量检索、BM25、索引重建和离线适配器，但问答服务仍返回固定演示答案，检索结果、重排、生成、引用、置信度、审核和日志没有形成闭环。现在接通完整 RAG 链路，才能让 `/api/qa` 和 `/api/qa/ask` 基于知识库回答问题，同时在无模型密钥的开发环境保持可离线演示。

## What Changes

- 新增可切换的 reranker 适配器，支持离线 Fake 实现和可选 BGE 实现。
- 新增受限生成适配器，支持离线 Fake 生成和 OpenAI-compatible 生成 API。
- 将 `KnowledgeChunk` 的向量检索、BM25 检索和 `rrf_merge` 接入问答服务，并支持省份、升学途径过滤。
- 用重排后的知识片段驱动生成，要求回答只使用检索证据并带来源引用。
- 无证据时直接返回 `restricted_answer`，禁止调用生成模型；生成失败时返回检索片段摘要并标记降级。
- 使用统一置信度分数和 `high`/`medium`/`low` 分档，低置信回答自动写入 `review_task`。
- 每次问答写入 `qa_log`，保留问题、回答、引用、置信度、会话和降级状态。
- 保持现有 `/api/qa`、`/api/qa/ask`、`/api/qa/history` 路由签名和响应契约不变。
- 默认使用 Fake 组件，测试不联网、不下载模型、不依赖 GPU；真实 BGE/Qwen 通过环境变量切换。

## Capabilities

### New Capabilities

- `rag-qa-pipeline`: 提供混合检索、RRF 融合、重排、受限生成、引用和安全兜底的完整问答链路。

### Modified Capabilities

- `knowledge-qa`: 将自然语言问答从固定演示实现升级为基于知识库证据的真实链路，并补齐低置信审核、生成降级和多轮上下文行为。

## Impact

- 主要修改 `backend/app/services/qa.py`，不修改问答路由和 `docs/api-contract.md`。
- 在 `backend/app/rag/` 新增 rerank、generation 适配器及其离线 Fake 实现。
- 调整配置、可选依赖和 `docs/ai/implementation.md`。
- 新增 `backend/test_qa_rag.py`，并回归现有索引、模型、管理端和问答历史测试。
- 依赖现有 `KnowledgeChunk`、`KnowledgeDoc`、`Source`、`QaLog`、`ReviewTask` 和 T2 embedding 基建。
