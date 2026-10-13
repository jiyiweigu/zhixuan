## ADDED Requirements

### Requirement: Algorithm-first recommendation
系统 SHALL 由确定性算法计算冲稳保、策略排序和风险，AI 只能解释已计算结果，且不得改变排序或新增推荐项。

#### Scenario: Generate recommendation
- **WHEN** 用户提交档案和策略
- **THEN** 系统返回三档结果、排序依据、风险提示和 citations。

### Requirement: Trend is non-ranking metadata
系统 SHALL 将 `trend_analysis` 作为推荐项的附加信息，不得用于替代位次差算法或单独决定冲稳保档位。

#### Scenario: Trend attached to item
- **WHEN** 推荐项有足够历史数据
- **THEN** 系统附加趋势标签、年份、指标变化、confidence、citations 和免责声明。

### Requirement: No unsupported certainty
系统 SHALL NOT 输出报名人数预测、录取概率、保证录取或确定性录取结论。

#### Scenario: Insufficient trend data
- **WHEN** 历史数据不可比
- **THEN** 系统显示“趋势暂不可判断”，仍可展示有依据的基础推荐或将该项标记数据不足。
