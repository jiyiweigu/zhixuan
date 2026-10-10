# 第一轮任务分工

- 主负责人：维护契约、Mock、develop 集成与 PR 审查。
- 后端：FastAPI 分层、Pydantic schemas、认证/档案接口。
- 数据：爬虫方案、来源白名单、字段清洗（本轮先不提交真实数据）。
- RAG：问答检索接口与 citations/confidence 规则。
- 管理端与测试：管理端页面骨架、审核状态、契约 smoke check。
- 前端公共：首页、档案、资格、问答、方案、院校页面，统一使用 `src/api`。

所有成员先以 Mock 完成页面和接口联调，再接入真实数据。
