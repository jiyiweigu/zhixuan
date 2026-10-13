## Why

当前接口契约已冻结，但前端仍只有少量示例 Mock，成员无法在没有真实爬虫数据和完整后端的情况下并行开发所有页面状态。现在补齐结构稳定、来源明确为演示的 Mock 数据与团队开发指南，可以先完成页面、交互和联调；后续爬虫只需替换数据适配层。

## What Changes

- 补齐认证、档案、资格、问答、方案和院校六类模块的成功、空态、错误态和低置信度 Mock。
- 建立独立的 Mock 数据目录、开关和使用文档。
- 编写成员开发指南、任务分工表和第一轮联调验收脚本。
- 明确 Mock 不代表真实政策结论，真实数据后续由爬虫和来源审核流程提供。

## Capabilities

### New Capabilities

- `development-mocks`: 为团队开发提供完整、可切换、状态覆盖充分的 Mock 数据。
- `team-development-readiness`: 提供成员开发指南、任务分工和首轮联调验收。

### Modified Capabilities

- 无

## Impact

- 新增 `frontend/src/mocks/`、`docs/mock-data.md`、`docs/development-guide.md`、`docs/team-tasks.md`。
- 扩展前端 API 类型和 Mock 请求封装。
- 新增轻量契约验收脚本，不引入爬虫依赖或真实政策数据。
- 后续爬虫接入需遵守现有来源字段和审核约束。
