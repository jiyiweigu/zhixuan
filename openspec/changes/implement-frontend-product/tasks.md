## 1. 基础工程与路由

- [x] 1.1 按产品书路由表建立用户端 `/`、`/login`、`/register`、`/profile`、`/eligibility`、`/pathways`、`/pathways/:id`、`/qa`、`/plan`、`/schools`、`/schools/:id`、`/majors`、`/majors/:id`、`/compare`、`/favorites`。
- [x] 1.2 建立 `/admin/login`、`/admin/docs`、`/admin/index`、`/admin/review`、`/admin/pathways`、`/admin/stats` 路由及管理端布局。
- [x] 1.3 增加 auth/profile/qa/plan/dict Pinia stores 与用户/管理员路由守卫。
- [x] 1.4 完成用户端/管理端导航、页脚、响应式断点和 Editorial 设计变量。

## 2. 公共组件

- [x] 2.1 实现 DisclaimerBar、SourceCard、CitationList、ConfidenceBadge。
- [x] 2.2 实现 EligibilityList、TierCard、StrategyTabs、SourceTag、DataStatusTag、LoadingSkeleton、EmptyState。
- [x] 2.3 为公共组件补齐 TypeScript props 与无引用保护。

## 3. 用户端页面

- [x] 3.1 实现首页、登录、注册和账号状态恢复。
- [x] 3.2 实现考生档案表单、校验、保存和空态。
- [x] 3.3 实现途径列表/详情与资格自检、路径筛选、结论依据展开和游客流程。
- [x] 3.4 实现问答多轮会话、`session_id`、引用展开、high/medium/low 置信度、`needs_review`、`degraded` 和历史列表。
- [x] 3.5 实现 `/api/recommend`、`/api/plan/generate`、风险核查、冲稳保分组、策略切换、方案 CRUD 和位次/来源年份展示。
- [x] 3.6 实现院校/专业多条件检索与分页、院校详情/画像/生活信息、专业详情、最多 5 校对比和来源折叠规则。
- [x] 3.7 实现院校对比、收藏和问答历史页面。
- [x] 3.8 实现 dict 状态缓存、问答会话和 session_id 展示。

## 4. 管理端页面

- [x] 4.1 实现管理端登录和布局导航。
- [x] 4.2 实现语料筛选/上传/删除、索引重建/进度、审核任务列表/详情/审核动作、途径及规则维护、区域列表和统计页面。
- [x] 4.3 为管理端补齐表格、筛选、分页、空态和无权限状态。

## 5. API、Mock 与质量

- [x] 5.1 将 API 封装覆盖产品书第 6 章中用户、档案、收藏、方案、路径、问答、推荐、风险、一分一段、院校、专业和管理端接口，并同步 snake_case 类型和 Mock。
- [x] 5.2 为每个页面接入 success/loading/empty/error Mock。
- [x] 5.3 完成 `npm run typecheck`、`npm run build` 和路由 smoke check。
- [x] 5.4 按核心链路完成登录→档案→资格→问答→方案→院校演示验收。
- [x] 5.5 检查移动端、免责声明、引用覆盖和演示数据标记。








