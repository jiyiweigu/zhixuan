# 第一轮任务分工

## 分支模型

| 分支 | 负责人 | 用途 |
|---|---|---|
| `main` | 队长 | **最终项目**：仅在里程碑（可演示）时从 `develop` 经 PR 合入，平时不动 |
| `develop` | 队长 | **集成分支**：汇集各成员 PR + 队长自己的开发提交 |
| `feature/xu` | 徐 | 个人功能开发分支，完成后提 PR 到 `develop` |
| `feature/fei` | 费 | 个人功能开发分支，完成后提 PR 到 `develop` |
| `feature/zhang` | 张 | 个人功能开发分支，完成后提 PR 到 `develop` |
| `feature/yuan` | 袁 | 个人功能开发分支，完成后提 PR 到 `develop` |

每天开工前先在自己分支上执行 `git pull origin develop`，再开始写代码；具体谁做哪个模块由队长指派，模块清单见《开发产品书_智选志愿》第 4–5 章。

## 共享文件约定（重要）

下面这些文件是**公共资产，只有队长可以修改**。队员需要变更时，先在群里说明（或提 Issue），由队长统一改：

- `docs/api-contract.md` —— 接口契约，前后端唯一的对齐依据
- `frontend/src/api/index.ts`、`frontend/src/types/api.d.ts`、`frontend/src/mocks/index.ts`
- `frontend/package.json`、`frontend/package-lock.json`
- `README.md`、`CONTRIBUTING.md`、`docs/*.md`

原因：五个人同时改这些文件必然冲突，而且契约一旦被改乱，前后端立刻对不上。**队员在自己分支上只改自己负责的页面和模块文件。**

## 角色分工

- 主负责人：维护契约、Mock、develop 集成与 PR 审查。
- 后端：FastAPI 分层、Pydantic schemas、认证/档案接口。
- 数据：爬虫方案、来源白名单、字段清洗（本轮先不提交真实数据）。
- RAG：问答检索接口与 citations/confidence 规则。
- 管理端与测试：管理端页面骨架、审核状态、契约 smoke check。
- 前端公共：首页、档案、资格、问答、方案、院校页面，统一使用 `src/api`。

## 当前状态（2026-10-11）

已就绪：接口契约升级至 **v1.2**（`docs/api-contract.md`，6.1 节逐条列出全部接口、附录 A 为前后端路径对照表）；后端已实现契约内全部路由并通过 `test_routes.py` / `test_alignment.py` 双重断言；认证/路径/报考约束 Mock 就绪；前后端骨架联通；前端依赖已锁版本；`.github/CODEOWNERS` 已登记共享文件；`docs/development-guide.md` 已含前后端启动、数据库迁移与依赖申报。

待认领：页面开发（首页/档案/资格/问答/方案/院校）、管理端骨架、真实数据接入、RAG 问答链路、方案生成规则。

所有成员先以 Mock 完成页面和接口联调，再接入真实数据。

## 报考约束增量（契约已明确，真实规则数据待导入）

接口和规则数据逻辑模型以 [`api-contract.md`](api-contract.md) 第 8 节为唯一实现依据。首期只做河南、江西普通本科批；提前批列入后续扩展，不要求数据库同学现在编造或导入提前批规则。前后端可以先用 `schema_only` Mock 完成功能，但真实校验必须等对应规则数据和来源校验通过后开放。

| 负责人 | 本轮交付 |
|---|---|
| 队长 | 维护第 8 节契约及共享前端类型、API、Mock；冻结后通知团队 |
| 后端 | 按第 8 节实现 Profile 增量字段、规则查询和批量资格校验；缺规则集返回 `3001`，不得默认放行 |
| 数据/数据库 | 按第 8.7 节建立版本化规则逻辑表与迁移、唯一约束/索引、数据集状态登记；先保证导入通道可用，数据核实后再导入 |
| 前端 | 使用同一 DTO 和 Mock 开发档案、自检、方案风险体检；清晰区分演示状态、待核验和真实规则结论 |

开始实现前，各负责人先检查第 8 节契约；如字段或状态需要调整，按本文档下方共享文件规则由队长统一更新，避免成员各自实现不同版本。

## 联调对齐（契约 v1.2，2026-10-13）

v1.2 收敛了四处跨层词表并补齐了 6.1 节，**关掉 Mock 即可开始真实联调**：

- 路径对齐已自动断言：`backend/test_alignment.py` 会比对 `frontend/src/api/index.ts` 里
  出现的每个 `/api` 路径与后端实际路由，缺一即失败。新增接口前先跑它。
- `data_status` 统一为 `available | partial | schema_only | unavailable`；
  `pathway_id` 统一为字符串 slug；`batch` 为展示名、`batch_code` 为机器键；
  数据源的 `category_group` 须映射为 `exam_type`。
- 档案三态字段（户籍类型、听力/嗅觉/口吃）出接口一律为 `null`；服务端兼容历史哨兵入参。
- 破坏性变更：`GET /api/schools` 改为返回分页包，前端取数需走 `data.items`。

各负责人对照 [`api-contract.md`](api-contract.md) 附录 A 核对本模块接口后再开工。

> **联调前先读 [开发指南](development-guide.md)**：登录成功后需调用 `setToken(access_token)` 保存令牌，否则带 `Auth: yes` 的档案、方案接口会返回 `1002`。

## 分工与模块对照

| 成员 | 分支 | 负责方向 |
|---|---|---|
| 队长 | `develop` | 契约与 Mock 维护、集成、PR 审查、用户端框架 |
| 徐 | `feature/xu` | 用户端前端页面（首页/档案/资格/问答/方案/院校） |
| 费 | `feature/fei` | 后端（FastAPI 分层、认证/档案/路径/方案接口、数据库迁移） |
| 张 | `feature/zhang` | 检索与 RAG 问答链路（citations / confidence 规则） |
| 袁 | `feature/yuan` | 管理端前端 + 测试 + 提交材料 |

模块清单见《开发产品书_智选志愿》第 4–5 章。
