## Context

仓库已有 Vue 3 + Vite 前端和 FastAPI 后端骨架，团队通过 `develop` 集成、成员分支开发。当前接口仅有演示级实现，无法支撑档案、资格、问答、方案和院校模块并行开发。本变更只冻结第一轮契约和 Mock，不实现完整业务规则或数据库。

## Goals / Non-Goals

**Goals:**

- 让前端可以脱离后端使用稳定 Mock 开发。
- 让后端按统一响应、鉴权和溯源约定实现接口。
- 让 OpenAPI、Markdown 文档和示例响应保持同一字段语义。

**Non-Goals:**

- 本轮不实现 JWT、PostgreSQL、pgvector、RAG 检索或资格规则引擎。
- 本轮不冻结管理端接口和最终数据库表结构。
- 本轮不引入新的第三方依赖。

## Decisions

1. **统一响应包**：所有业务接口返回 `{code, message, data, trace_id}`；成功 `code=0`，业务错误使用 1001 参数错误、1002 未登录、1003 无权限、1006 用户名重复。
2. **接口版本**：首版使用 `/api` 前缀，字段全部使用 snake_case；发生破坏性变更时新增版本或先更新文档并通知成员。
3. **溯源约束**：事实结论必须携带 `source_name`、`source_url`、`year`；问答结果必须携带 `citations` 和 0~1 的 `confidence`，缺引用时前端不展示结论。
4. **Mock 方式**：文档提供 JSON 示例，前端通过 `src/api` 封装调用；后端在业务未完成时返回结构一致的静态数据。
5. **契约来源**：`docs/api-contract.md` 是成员阅读入口，FastAPI `/docs` 和 `/openapi.json` 是机器可读入口。

## Risks / Trade-offs

- [字段变更导致联调返工] → 变更前先更新文档和 Mock，并通过 PR 通知所有模块负责人。
- [Mock 与真实规则不一致] → Mock 只表达字段结构，不宣称真实政策结论；所有示例事实标注来源和年份。
- [接口文档落后于代码] → PR 模板增加“接口变更”勾选项，CI 阶段校验 OpenAPI 快照。
