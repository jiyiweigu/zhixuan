## ADDED Requirements

### Requirement: Evidence-grounded AI support
系统 SHALL 将大模型限制在检索片段或确定性算法结果范围内；大模型 SHALL NOT 参与资格判定、方案排序或竞争热度等级判定。

#### Scenario: Model explains algorithm output
- **WHEN** 方案或趋势已有结构化结果和引用
- **THEN** 模型只能生成不改变结果的解释，并保留原始数据依据。

### Requirement: Competition trend analysis
系统 SHALL 对可比历史数据输出 `rising`、`stable`、`falling` 或 `insufficient_data` 趋势标签，并返回数据年份、指标变化、置信度和 citations。

#### Scenario: Comparable history exists
- **WHEN** 同口径存在至少两年有效最低位次、计划数和来源数据
- **THEN** 系统输出竞争热度趋势标签、数据依据和“历史趋势研判”标记。

#### Scenario: History is insufficient
- **WHEN** 历史数据不足、来源缺失或年份口径不可比
- **THEN** 系统输出 `insufficient_data` 和“趋势暂不可判断”，不得由模型补结论。

### Requirement: Trend disclosure
系统 SHALL 在趋势展示处明确说明该结果不代表实际报名人数、录取概率或录取结果，且 SHALL NOT 使用承诺性措辞。

#### Scenario: User views recommendation
- **WHEN** 推荐项附带趋势分析
- **THEN** 用户可展开查看历年数据、来源和限制说明。
