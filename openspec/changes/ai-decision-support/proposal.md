## Why

智选志愿需要把 AI 的能力边界、证据约束和新增的竞争热度研判固定下来，避免模型直接替代规则引擎或输出没有依据的录取判断。本变更为算法、后端和前端提供可执行的 AI 决策支持契约。

## What Changes

- 固化可溯源 RAG 问答：混合检索、重排、受限生成、引用、置信度和失败降级。
- 固化多轮追问的问题改写和问答留痕要求。
- 明确低置信与高风险问答进入人工审核队列。
- 明确冲稳保方案由确定性算法计算和排序，大模型只解释，不改变结果。
- 新增“志愿竞争热度趋势研判”：基于历史位次、计划数和可比性输出趋势标签与数据依据。
- 明确数据不足、年份口径不一致时输出“趋势暂不可判断”，禁止模型补结论。

## Capabilities

### New Capabilities

- `ai-decision-support`: 可溯源问答、方案解释和竞争热度趋势研判的 AI 行为契约。

### Modified Capabilities

- `knowledge-qa`: 补充 AI 受限生成、降级和审核边界。
- `volunteer-plan`: 补充竞争热度趋势字段及其不影响排序的约束。

## Impact

- 影响 `backend/app/rag`、`backend/app/services/qa_service`、`backend/app/services/plan_service` 和审核服务。
- 影响问答、推荐接口响应字段和前端 `CitationList`、`ConfidenceBadge`、趋势标签组件。
- 需要历史录取位次、招生计划和来源元数据的可比性检查。
- 不改变资格规则引擎；不新增真实爬虫或模型供应商依赖。
