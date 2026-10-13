## ADDED Requirements

### Requirement: Restricted generation and citations
系统 SHALL 仅依据混合检索和重排后的片段生成问答，事实性结论必须绑定 `index`、`chunk_id`、`source_name`、`source_url`、`year`、`snippet`。

#### Scenario: Evidence-backed answer
- **WHEN** 检索结果足以回答问题
- **THEN** 答案逐条包含引用编号和完整 citation 字段。

#### Scenario: No evidence
- **WHEN** 检索结果不足
- **THEN** 系统返回固定无数据文案，不编造事实。

### Requirement: Confidence and review
系统 SHALL 输出 `high`、`medium` 或 `low` 置信度；低置信或涉及分数线、资格规则的问题 SHALL 自动进入审核队列。

#### Scenario: Low confidence answer
- **WHEN** 最高重排分低于阈值或未命中结构化数据
- **THEN** 系统提示建议人工核实并创建审核任务。

### Requirement: Generation fallback
系统 SHALL 在模型超时或失败时返回有来源的检索片段摘要并设置 `degraded=true`。

#### Scenario: Model unavailable
- **WHEN** 大模型调用失败
- **THEN** 问答接口仍返回可核验摘要，并标注“AI 生成暂不可用”。
