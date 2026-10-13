## 1. 契约文档与 Mock

- [x] 1.1 创建 `docs/api-contract.md`，覆盖认证、档案、路径、问答、方案、院校七类接口。
- [x] 1.2 为每个接口补齐请求、响应、鉴权、错误码和 Mock JSON。
- [x] 1.3 记录统一响应包、溯源字段、confidence 范围和免责声明要求。

## 2. 后端契约骨架

- [x] 2.1 将 FastAPI 路由按 `api/v1`、schemas、services 分层整理。
- [x] 2.2 为核心接口创建 Pydantic request/response schemas。
- [x] 2.3 保证 `/api/health` 与核心 Mock 接口返回统一响应包。
- [x] 2.4 生成并检查 `/openapi.json`，确保字段与文档一致。

## 3. 前端联调入口

- [x] 3.1 创建 `frontend/src/types/api.d.ts`，声明公共响应、来源、引用和核心 DTO。
- [x] 3.2 创建 `frontend/src/api/` 请求封装，禁止页面直接调用 axios/fetch。
- [x] 3.3 提供 Mock 开关或本地静态数据，使成员无需等待后端即可开发页面。

## 4. 团队交接

- [x] 4.1 在 README 或开发文档中链接接口契约和本地启动命令。
- [x] 4.2 在 PR 模板中明确接口变更必须同步文档与 Mock。
- [x] 4.3 在 develop 分支发布首版契约，通知各成员从对应分支开始开发。
- [x] 4.4 用一条健康检查、一条资格自检和一条问答 Mock 完成联调验收。

