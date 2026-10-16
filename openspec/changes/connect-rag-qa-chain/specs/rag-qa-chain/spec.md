## ADDED Requirements

### Requirement: RAG adapter chain

系统 SHALL 提供可替换的 reranker 与 generator 适配器，并在无真实模型配置时使用确定性的离线 Fake 实现。

#### Scenario: Offline default
- **WHEN** 环境没有有效 reranker 或生成模型配置
- **THEN** 系统使用 Fake 适配器，不联网、不下载模型且可完成问答测试。

### Requirement: Evidence-first retrieval

系统 SHALL 将向量检索与 BM25 检索通过 RRF 融合后重排，并仅使用具备完整来源的片段生成事实回答。

#### Scenario: Hybrid retrieval
- **WHEN** 知识库存在匹配切片
- **THEN** 系统执行向量检索、关键词检索、RRF 融合和 reranker 重排，并保留来源元数据。

#### Scenario: Empty evidence
- **WHEN** 没有可核验的召回片段
- **THEN** 系统不得调用生成器，返回知识库暂无数据的受限回答。

### Requirement: Restricted generation and degradation

系统 SHALL 要求生成器仅依据编号检索片段回答；生成失败时 SHALL 返回检索摘要并标记降级。

#### Scenario: Generation failure
- **WHEN** 生成器超时、缺少密钥或调用失败
- **THEN** 系统返回片段摘要、提示 AI 生成暂不可用，并将 `degraded` 设为 true。

### Requirement: Confidence and review

系统 SHALL 从同一评分结果产生 0~1 的 `confidence` 和 `high`/`medium`/`low` 分档；低置信回答 SHALL 写入待审核任务。

#### Scenario: Low confidence
- **WHEN** 问答置信度为 low
- **THEN** 响应设置 `needs_review=true`，并创建一条关联 QaLog 的 pending ReviewTask。

### Requirement: Conversation context and traceability

系统 SHALL 在同一 session 的指代问题中使用最近问答上下文，并记录完整问答日志和来源引用。

#### Scenario: Follow-up question
- **WHEN** 用户连续提问并使用“它”“该校”等指代词
- **THEN** 系统把上一轮上下文加入检索查询后再回答。

#### Scenario: Persist trace
- **WHEN** 一次问答完成
- **THEN** 系统记录问题、答案、引用、置信度、会话标识、降级状态和审核状态。
