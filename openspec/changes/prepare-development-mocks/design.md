## Context

接口契约已经冻结，但真实政策、院校和分数线数据将由后续爬虫与审核流程提供。当前需要让前端、后端和测试成员立即并行开发，因此 Mock 必须覆盖核心模块及关键状态，同时明确 Mock 不等于事实数据。

## Goals / Non-Goals

**Goals:**

- 用本地静态数据覆盖六类核心模块及常见 UI 状态。
- 通过环境变量切换 Mock 与真实 API。
- 提供成员开发指南、任务分工和最小验收路径。
- 保持 Mock 字段与 API 契约一致，方便未来接入爬虫适配层。

**Non-Goals:**

- 不抓取真实网站，不引入爬虫、数据库或第三方数据服务。
- 不把 Mock 中的院校、政策、分数示例当作生产结论。
- 不实现完整业务规则、鉴权或审核后台。

## Decisions

1. **按模块拆分 Mock**：在 `frontend/src/mocks/` 下按 auth、profile、eligibility、qa、plans、schools 拆分，便于成员独立替换。
2. **统一状态模型**：每个模块至少提供 success、empty、error；问答额外提供 low-confidence，资格额外提供 eligible、pending、ineligible。
3. **适配层优先**：API 封装只依赖类型和响应包，真实爬虫数据未来通过同一 DTO 进入，不让页面直接依赖抓取格式。
4. **显式标注演示数据**：Mock 来源字段使用 `source_name: "演示数据（非官方）"`，文档和 UI 均不得将其当作官方事实。
5. **验收脚本轻量化**：使用 TypeScript 类型检查、Python 编译检查和固定 JSON 断言，不新增运行时依赖。

## Risks / Trade-offs

- [成员误把 Mock 当真实政策] → 所有 Mock 来源明确标注演示，开发指南加入免责声明。
- [Mock 与爬虫字段不一致] → 先冻结 DTO，爬虫必须输出 API 契约格式。
- [状态数量增加维护成本] → 只覆盖首轮页面所需状态，新增状态需在任务表登记。

## Migration Plan

1. 合并 Mock、文档和验收脚本到 `develop`。
2. 成员从各自 feature 分支同步 `develop`，默认使用 Mock 开发。
3. 爬虫完成后新增数据适配器，保持现有 DTO 和页面不变。
4. 联调阶段将 `VITE_USE_MOCK=false`，逐接口替换并保留失败回退。

## Open Questions

- 后续爬虫的来源白名单、频率限制和人工审核责任人需要在数据阶段确定。
