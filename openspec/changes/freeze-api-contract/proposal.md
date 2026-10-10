## Why

当前前后端骨架已经建立，但团队成员缺少一份冻结的接口契约，容易出现字段命名、鉴权、错误码和数据溯源规则不一致。现在先冻结第一轮接口与 Mock 约定，成员即可并行开发并通过 PR 集成。

## What Changes

- 建立用户认证、考生档案、路径自检、路径目录、问答、志愿方案和院校检索的首版 HTTP 契约。
- 统一响应包为 `{code, message, data, trace_id}`，统一错误码和 snake_case 字段。
- 为事实性结果定义 `source_name`、`source_url`、`year`，问答定义 `citations` 与 `confidence`。
- 提供 Mock 数据约定、联调示例和接口变更流程，作为成员开发入口。

## Capabilities

### New Capabilities

- `api-contract`: 为第一轮用户端核心接口提供可执行的请求、响应、错误和溯源契约。

### Modified Capabilities

- 无

## Impact

- 新增 `docs/api-contract.md` 作为团队接口文档。
- 约束 `backend/app/api`、`backend/app/schemas`、`frontend/src/api` 和 `frontend/src/types` 的实现。
- FastAPI OpenAPI 文档必须与契约保持同步。
- 不新增运行时依赖，不改变现有前端视觉骨架。
