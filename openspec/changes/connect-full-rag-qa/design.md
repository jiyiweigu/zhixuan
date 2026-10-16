## Context

T2 已提供批量 embedding、SQLite 向量检索、BM25、索引重建和 Fake 默认适配器。当前 `services/qa.py` 仍返回固定演示答案；`KnowledgeChunk` 通过 `source_id` 关联来源，`QaLog` 与 `ReviewTask` 已存在，问答路由和 API 契约已经冻结。实现必须在 SQLite、无密钥、无模型文件环境下可运行。

## Goals / Non-Goals

**Goals:**

- 将向量检索、BM25、RRF、重排、受限生成、引用、置信度、审核和日志接成一条可测试链路。
- 通过适配器支持 Fake、BGE reranker 和 OpenAI-compatible generation，默认离线运行。
- 严格保持现有问答路由、DTO 和历史接口兼容。
- 对无证据、生成失败和低置信结果提供可观测的安全行为。

**Non-Goals:**

- 不修改 `docs/api-contract.md`、问答路由签名或数据库主表结构。
- 不在本变更实现新的多轮实体抽取、RRF 算法或 pgvector 查询优化。
- 不要求 CI 下载模型、访问外部 API 或运行 GPU。

## Decisions

1. **服务编排集中在 `qa.py`**：保留现有公开函数，新增内部 pipeline 函数，避免 GET 与 POST 产生不同问答逻辑。
2. **适配器统一批量接口**：reranker 接收问题和候选片段并返回分数；generator 接收问题、上下文和省份/途径上下文并返回答案。Fake 实现保持确定性，真实实现延迟加载。
3. **检索先过滤后召回**：按 `province`、`pathway_id` 优先过滤 `KnowledgeChunk`，通过 `KnowledgeDoc` 和 `Source` 补齐来源字段；过滤后不足时允许回退到未过滤候选，但置信度降低并记录回退。
4. **证据优先**：向量和 BM25 各取 top-N，经 `ai_support.rrf_merge` 后交给 reranker。没有同时具备有效来源和正文的候选时直接调用 `restricted_answer`，不调用 generator。
5. **生成受限且可降级**：生成提示明确只能引用给定片段；生成异常时使用片段摘要，设置 `degraded=true`，保留引用并记录警告。
6. **置信度单一出口**：将重排分数、结构化命中、来源完整性和过滤回退转换为 0~1 分数及同源等级；低等级创建一个 pending `ReviewTask`。
7. **日志事务边界**：先保存 `QaLog`，再按低置信条件创建 `ReviewTask`，同一 `qa_log_id` 不重复入队；提交失败回滚并抛出可观测错误。
8. **配置默认 Fake**：新增 rerank/generation backend、模型、API 地址和 top-k 配置，API key 仅从环境变量读取。

## Risks / Trade-offs

- [Fake 结果不代表语义质量] -> 在响应和文档中标记演示模式，并用真实模型配置替换。
- [SQLite 全表候选不适合生产规模] -> 开发期使用，生产 PostgreSQL 再接 pgvector 查询。
- [生成模型可能偏离证据] -> 强制上下文提示、引用校验和生成失败降级；无法校验时不输出事实扩展。
- [来源关联查询增加延迟] -> 单次问答批量加载文档和来源，避免逐片段查询。
- [真实 BGE/Qwen 未在本机演练] -> 保留可替换适配器，并在交接文档中明确部署验证步骤。

## Migration Plan

1. 先新增 Fake reranker/generator、配置和纯函数测试。
2. 接入 `qa.py` 的混合检索、来源组装、生成/兜底和持久化。
3. 运行离线 RAG、索引、模型、管理端和历史接口回归。
4. 部署时保持 Fake 默认；配置真实模型后执行小规模语料验收。
5. 回滚时恢复 `qa.py` 的上一版本即可，数据库字段无需回滚。

## Open Questions

- 生产环境最终使用本地 BGE reranker 还是远程兼容 API，需要部署资源确认。
- Qwen 兼容接口的响应格式和超时策略需要在接入真实服务时验证。
