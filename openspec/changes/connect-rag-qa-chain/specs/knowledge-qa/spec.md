## MODIFIED Requirements

### Requirement: 自然语言问答

系统 SHALL 接收自然语言问题，并通过省份/升学途径过滤、向量检索与关键词检索融合、重排和受限生成返回结构化答案。

#### Scenario: 常规提问
- **WHEN** 用户提交一个关于院校或专业的问题
- **THEN** 系统返回答案正文、数值置信度、置信度分档和可核验引用，答案只使用召回片段中的事实。

#### Scenario: 知识库无相关内容
- **WHEN** 检索片段为空或没有完整来源
- **THEN** 系统不调用生成模型，回复“知识库暂无相关数据，建议查阅官方渠道”，置信度为低并标记需要审核。

### Requirement: 答案溯源

系统 SHALL 为答案中的事实性结论提供来源名称、年份、链接、原文片段和对应切片标识；无来源的事实性结论 SHALL NOT 展示。

#### Scenario: 展示溯源
- **WHEN** 返回包含事实性结论的答案
- **THEN** 每条引用均可追溯到 KnowledgeChunk 及其 Source 记录。

#### Scenario: 无来源则不展示
- **WHEN** 某个召回片段无法关联完整来源
- **THEN** 该片段不得作为事实引用，且不足以支撑回答时走无证据兜底。

### Requirement: 检索与生成约束

系统 SHALL 采用向量检索与 BM25 检索，经 RRF 融合和 reranker 重排后生成；生成阶段 SHALL 仅依据召回片段作答。

#### Scenario: 受限生成
- **WHEN** 存在有完整来源的召回片段且生成器可用
- **THEN** 生成器收到问题、用户省份上下文和带编号片段，并在答案中使用引用编号。

#### Scenario: 按省份与途径过滤
- **WHEN** 请求提供省份或 pathway_id
- **THEN** 检索优先仅使用匹配元数据的切片。

#### Scenario: 生成失败降级
- **WHEN** 生成模型超时、缺少密钥或调用失败
- **THEN** 系统返回检索片段摘要，提示“AI 生成暂不可用”，并标记 degraded。

### Requirement: 置信度分级

系统 SHALL 根据 reranker 得分、结构化命中和来源完整度计算 0~1 置信度，并由同一结果产生 high/medium/low 分档。

#### Scenario: 低置信提示
- **WHEN** 置信度为 low
- **THEN** 响应标记 needs_review=true，并创建一条 pending ReviewTask。

### Requirement: 多轮追问

系统 SHALL 支持基于同一 session 最近问答的最小上下文改写。

#### Scenario: 指代消解
- **WHEN** 连续对话问题包含“它”“这个”“该校”或“这所”等指代词
- **THEN** 系统把上一轮问题和答案摘要加入检索查询后再执行问答。

### Requirement: 问答留痕

系统 SHALL 记录问题、答案、引用、置信度分档、会话标识、是否降级和是否需要审核。

#### Scenario: 保存问答记录
- **WHEN** 系统完成一次问答
- **THEN** 先写入 QaLog，再按低置信条件创建关联 ReviewTask，并保持现有历史接口可查询。
