# 成员开发指南

1. `git checkout develop && git pull origin develop`，再切换自己的 `feature/*` 分支。
2. 阅读 [API 契约](api-contract.md)、[Mock 说明](mock-data.md) 和 [任务分工](team-tasks.md)。
3. `cd frontend && npm install && npm run dev`，默认使用 Mock。
4. 页面请求统一走 `src/api/`，字段使用 snake_case；事实结论必须带引用。
5. 完成后运行 `npm run build` 与后端 smoke check，提交小而独立的 PR 到 `develop`。
6. 真实数据由后续爬虫提供，当前不得提交密钥、隐私或未经审核的政策数据。
