## Why

当前 T2 已完成 embedding、向量检索、BM25、索引重建和 SQLite/pgvector 存储基建，但 `services/qa.py` 仍返回固定演示答案。用户问答尚未真正使用知识库，无法形成“检索—重排—受限生成—引用—审核—留痕”的可信闭环。

## What Changes

- 接通向量检索与 BM25 检索，并使用 RRF 融合候选结果。
- 新增可替换的 Fake/BGE reranker 和 Fake/OpenAI-compatible 生成适配器。
- 在 `services/qa.py` 中接通省份、升学途径过滤、多轮上下文、重排、受限生成和无证据兜底。
- 统一输出数值置信度与 high/medium/low 分档。
- 低置信回答自动写入 `review_task`，所有问答写入 `qa_log`。
- 保持 `/api/qa`、`/api/qa/ask`、`/api/qa/history` 路由和 `docs/api-contract.md` 不变。
- 增加离线 Fake 全链路测试和生成失败降级测试。

## Capabilities

### New Capabilities
- `rag-qa-chain`: 真实 RAG 问答链路、模型适配器、证据约束和离线验证。

### Modified Capabilities
- `knowledge-qa`: 将问答从固定演示实现改为基于知识库检索、重排和受限生成，并补齐审核入队与日志行为。

## Impact

- 主要影响 `backend/app/services/qa.py`、`backend/app/rag/`、配置、AI 说明文档和新增测试。
- 不修改 API 路由签名、响应字段或 `docs/api-contract.md`。
- 真实 BGE/Qwen 依赖保持可选，默认环境不联网、不下载模型、不需要 GPU。
