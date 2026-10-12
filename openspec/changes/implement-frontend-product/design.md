## Context

产品书规定前端采用 Vue3 + TypeScript + Vite + Element Plus + Pinia，用户端与管理端共用一个工程，通过路由和角色区分。当前代码只有单页首页和少量请求/Mock 文件，需按完整路由表和第 6 章接口落地。本变更覆盖用户端和管理端全部前端工作，由当前前端负责人统筹实现。

## Goals / Non-Goals

**Goals:**

- 让产品书列出的前端路由均可访问，并具备真实可交互的 Mock 流程。
- 让所有事实结论通过来源和置信度组件呈现。
- 让登录、档案、资格、问答、方案、院校和管理审核链路可演示。
- 保持视觉系统和组件复用，支持桌面与移动端。

**Non-Goals:**

- 不在前端实现资格判定、推荐排序、RAG、权限校验或爬虫逻辑。
- 不替代后端数据库、JWT 验证和管理端权限控制。
- 不提交真实政策、院校或用户隐私数据。

## Decisions

1. **路由分组**：用户页面放 `views/user`，管理页面放 `views/admin`，公共布局与组件放 `components`；路由逐项对应产品书第 4.1 节，QA 历史可以作为 `/qa` 内部视图。
2. **状态边界**：auth、profile、qa、plan、dict 使用 Pinia；页面筛选、输入和展开状态留在页面组件。
3. **接口入口**：所有请求只通过 `src/api` 与 `src/utils/request.ts`，页面不直接调用 fetch；统一处理 bearer token、响应包、错误码和 trace_id。Mock 与真实 API 使用同一 DTO。
4. **可信展示**：SourceCard/CitationList/ConfidenceBadge 作为事实结果的统一出口；缺 citations 不渲染确定性结论，low confidence 显示人工核验提示。
5. **设计系统**：延续 Editorial 规范，暖米 `#F9F8F6`、柔黑 `#1C1C1C`、细线、无渐变阴影和大圆角；Element Plus 仅作为交互基础，不采用默认彩色主题。
6. **完整契约映射**：按产品书第 6 章覆盖用户/档案/收藏/方案、路径/区域/资格、QA/历史、推荐/方案生成/风险/位次、院校画像/生活信息/比较、专业和管理端接口；分页统一使用 `items/total/page/page_size`。
7. **渐进交付**：先完成路由、布局、公共组件和 Mock 演示，再逐页切换真实 API；页面不依赖爬虫数据才能启动。

## 前端页面与接口映射

| 页面/流程 | 产品书接口 |
|---|---|
| 登录/注册/账号 | `POST /api/user/register`、`POST /api/user/login`、`POST /api/user/logout` |
| 档案 | `GET/PUT /api/user/profile` |
| 收藏 | `GET/POST/DELETE /api/user/favorites` |
| 志愿方案管理 | `GET/POST /api/user/plans`、`GET/PUT/DELETE /api/user/plans/{id}` |
| 路径与资格 | `GET /api/pathways`、`GET /api/pathways/{id}`、`GET /api/pathways/{id}/regions`、`POST /api/user/profile/eligibility`、`POST /api/pathways/eligibility-check` |
| 问答与历史 | `POST /api/qa/ask`、`GET /api/qa/history` |
| 推荐与风险 | `POST /api/recommend`、`POST /api/plan/generate`、`POST /api/plan/risk-check`、`GET /api/scores/segment` |
| 院校/专业/比较 | `GET /api/schools`、`GET /api/schools/{id}`、`GET /api/schools/{id}/profile`、`GET /api/schools/{id}/life`、`POST /api/schools/compare`、`GET /api/majors`、`GET /api/majors/{id}` |
| 管理端 | `/api/admin/login`、`/api/admin/docs`、`/api/admin/index/*`、`/api/admin/pathways`、`/api/admin/pathway-rules`、`/api/admin/pathway-regions`、`/api/admin/review/tasks*`、`/api/admin/stats` |

实现期间若仓库实际 `docs/api-contract.md` 与产品书第 6 章冲突，先记录契约差异并沿用已确认的字段，不在页面代码内私自发明接口；需由契约负责人先同步文档、类型和 Mock。

## Risks / Trade-offs

- [页面范围较大] → 按用户端、公共组件、管理端拆分任务，每项有独立验收。
- [接口字段继续变化] → 以 `docs/api-contract.md` 和 `api.d.ts` 为唯一来源，变更必须同步 Mock。
- [事实数据误展示] → 强制来源组件和免责声明，演示数据显式标记非官方。
- [管理端权限被误认为前端安全] → 前端只隐藏入口，后端仍必须完成角色校验。

## Migration Plan

1. 建立前端目录、路由、布局、状态和公共组件。
2. 将现有首页迁移到用户端布局，接入 Mock。
3. 按模块实现用户端页面，再实现管理端骨架。
4. 运行类型检查、构建、路由 smoke check 和关键流程演示。
5. 后端接口稳定后切换 `VITE_USE_MOCK=false`，保留失败和空态。
