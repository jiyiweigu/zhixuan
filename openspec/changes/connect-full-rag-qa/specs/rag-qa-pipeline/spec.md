## ADDED Requirements

### Requirement: 混合检索与重排
系统 SHALL 复用 T2 embedding 和 BM25 能力，按省份与升学途径过滤候选，使用 RRF 融合向量与关键词结果，再通过可替换 reranker 输出最终证据排序。

#### Scenario: Fake 全链路召回
- **WHEN** 用户询问语料中存在的事实且使用默认离线配置
- **THEN** 系统返回包含匹配知识切片的排序结果，并且不访问网络或下载模型

#### Scenario: 过滤候选
- **WHEN** 请求包含省份或 pathway_id
- **THEN** 系统优先返回匹配元数据的切片，无法满足时记录过滤回退并降低置信度

### Requirement: 受限生成与安全兜底
系统 SHALL 仅将检索到的知识片段交给生成器，回答中的事实结论 SHALL 带引用；无有效证据时 MUST 不调用生成器并返回知识库暂无数据。

#### Scenario: 有证据生成
- **WHEN** 候选片段具备正文和完整来源
- **THEN** 回答正文仅依据候选片段，并使用 `[1]` 等编号关联 citations

#### Scenario: 无证据
- **WHEN** 检索结果为空或没有完整来源
- **THEN** 系统返回受限兜底话术、低置信度、`needs_review=true`，且生成器调用次数为零

#### Scenario: 生成失败
- **WHEN** 生成器超时或返回错误
- **THEN** 系统返回检索片段摘要，`degraded=true`，并保留可核验 citations

### Requirement: 置信度与人工审核
系统 SHALL 同时返回 0~1 的 confidence 和同源的 `high`/`medium`/`low` confidence_level；低置信问答 SHALL 创建 pending review_task。

#### Scenario: 低置信入队
- **WHEN** 重排证据不足或来源不完整导致 confidence_level=low
- **THEN** 系统将对应 qa_log_id 创建一条待审核记录，且不重复创建

### Requirement: 证据溯源
系统 SHALL 从 KnowledgeChunk、KnowledgeDoc 和 Source 组装 source_name、source_url、year、snippet 和 chunk_id，禁止生成器自行编造来源。

#### Scenario: 来源完整
- **WHEN** 返回事实性回答
- **THEN** 每条 citation 均包含来源名称、链接、年份和原文片段

### Requirement: 问答适配器
系统 SHALL 提供离线 Fake reranker/generator 以及可选 BGE reranker/OpenAI-compatible generator，并由环境变量选择，默认 Fake。

#### Scenario: 未配置真实模型
- **WHEN** 没有模型文件、API 地址或 API key
- **THEN** 问答链路仍可完整运行且不联网
