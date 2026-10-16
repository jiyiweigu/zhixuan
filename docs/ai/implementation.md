# AI 决策支持实现说明

## RAG 问答链路

问答服务按“查询 embedding → 向量检索 + BM25 → RRF 融合 → rerank → 受限生成”的顺序工作。检索结果通过 `KnowledgeChunk`、`KnowledgeDoc` 和 `Source` 组装来源名称、链接、年份、原文片段和切片 ID，生成器只能接收这些证据。

默认配置使用离线 Fake embedding、FakeReranker 和 FakeGenerator，不联网、不下载模型、不依赖 GPU。生产环境可以通过 `ZHIXUAN_RERANK_BACKEND=bge` 和 `ZHIXUAN_GENERATION_BACKEND=openai-compatible` 切换真实模型；密钥只从环境变量读取。

无有效证据时，服务直接返回“知识库暂无相关数据，建议查阅各省教育考试院官方渠道”，不调用生成器，并以低置信度入审核队列。生成器超时或返回空内容时，服务退回检索片段摘要，标记 `degraded=true` 并保留引用。

每次 `POST /api/qa/ask` 都写入 `qa_log`；低置信、生成降级或问题涉及分数线/规则/资格时，通过审核服务幂等创建 `review_task`。API 路由和 `docs/api-contract.md` 保持不变。

## 趋势分析

- `POST /api/recommend/trend`：输出 rising/stable/falling/insufficient_data。
- 趋势不参与冲稳保排序，不代表报名人数或录取概率。

## 真实部署限制

本地 BGE reranker、Qwen-compatible API 和 PostgreSQL pgvector 尚未在当前离线环境实机演练；接入前需配置模型、API 地址和密钥，并用带官方来源的小规模语料做验收。
