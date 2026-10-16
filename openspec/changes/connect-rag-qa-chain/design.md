## Context

T2 已提供 `FakeEmbedder`、BGE/OpenAI-compatible embedding、SQLite 向量检索、BM25、索引重建和 `ai_support.rrf_merge`、`classify_confidence`、`restricted_answer` 等基础能力。当前 `services/qa.py` 仍为固定演示回答，`KnowledgeChunk` 通过 `source_id` 关联来源，问答日志和审核任务表已经存在。

## Goals / Non-Goals

**Goals:**

- 在不改变 API 契约和路由层的前提下接通完整 RAG 闭环。
- 默认使用 Fake 适配器完成离线演示和测试，真实模型通过环境变量切换。
- 所有事实回答必须来自有来源的检索片段。
- 统一处理无证据、低置信和生成失败场景。

**Non-Goals:**

- 不修改 `docs/api-contract.md`、路由签名或前端 DTO。
- 不实现新的向量数据库或新的索引重建流程。
- 不在本变更中实现审核工作台 UI 或完整实体识别系统。
- 不要求 CI 下载 BGE、reranker 或调用外部生成 API。

## Decisions

1. **复用 T2 检索能力**：从 `KnowledgeChunk` 读取候选，按 province/pathway_id 过滤后分别执行向量检索和 BM25，再调用现有 `rrf_merge`。
2. **适配器可替换**：新增 `reranker.py` 和 `generator.py`。Fake 实现保证确定性；BGE reranker 延迟加载；生成器支持 OpenAI-compatible API。未配置有效模型时使用 Fake。
3. **证据优先**：检索结果为空或没有完整来源时直接调用 `restricted_answer`，不调用生成模型；生成失败时基于检索片段摘要降级并标记 `degraded=true`。
4. **来源集中组装**：由服务层通过 KnowledgeChunk -> KnowledgeDoc -> Source 组装 source_name、source_url、year、snippet、chunk_id，生成器不得自行编造来源。
5. **置信度双字段**：使用同一评分结果同时产生 0~1 的 `confidence` 和 `confidence_level`，低置信时创建唯一对应的 ReviewTask。
6. **多轮上下文最小实现**：读取同一 session 最近问答；出现指代词时将上一轮问题和答案摘要加入检索查询，不增加独立实体抽取模型。
7. **事务顺序**：先写入 QaLog，再按低置信条件写入 ReviewTask，提交同一事务；异常回滚并记录日志。

## Risks / Trade-offs

- [Fake 模型不代表语义质量] -> 明确演示标记，并为真实模型保留配置切换。
- [SQLite 内存检索不适合大规模语料] -> 维持开发模式，生产使用 pgvector 路径。
- [生成模型可能输出超出证据的内容] -> 系统提示限定片段范围，并在无证据时完全禁止调用生成。
- [来源关联查询增加耗时] -> 批量预加载文档和来源，限制候选数量。
- [外部 API 超时或密钥缺失] -> 捕获异常、记录错误并返回片段摘要降级。

## Migration Plan

1. 先新增适配器和纯函数测试，不影响现有演示接口。
2. 接入 qa 服务内部链路并增加全链路测试。
3. 更新配置和文档，默认保持 Fake。
4. 部署时先以 Fake 验证，再配置真实 reranker/generator。
5. 回滚时恢复 qa 服务旧实现，数据库表结构无需回滚。

## Open Questions

- 生产环境最终选择本地 BGE reranker 还是兼容 API，由部署资源决定。
- Qwen 兼容 API 的具体 endpoint 和模型名由部署环境注入，不写入代码。
