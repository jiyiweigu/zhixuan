## 1. Mock 数据与类型

- [x] 1.1 创建 auth、profile、eligibility、qa、plans、schools 模块 Mock fixtures。
- [x] 1.2 为每个模块补齐 success、empty、error 状态；补充问答 low-confidence 与资格 eligible/pending/ineligible。
- [x] 1.3 更新前端 API 封装和 DTO 类型，确保 Mock 与契约字段一致。
- [x] 1.4 明确所有 Mock 来源为“演示数据（非官方）”，保留 citation 字段。

## 2. Mock 使用与开发文档

- [x] 2.1 创建 `docs/mock-data.md`，说明开关、目录、状态选择和爬虫替换边界。
- [x] 2.2 创建 `docs/development-guide.md`，说明安装、启动、分支、接口契约和提交流程。
- [x] 2.3 创建 `docs/team-tasks.md`，列出前端、后端、数据、RAG、管理端与测试的首轮职责。

## 3. 联调验收

- [x] 3.1 增加健康检查、资格自检和问答 Mock 的契约 smoke check。
- [x] 3.2 验证响应包、citation 三要素、confidence 范围和低置信状态。
- [x] 3.3 在 README_DEV.md 链接三份开发文档和验收命令。

## 4. 集成交接

- [x] 4.1 检查 git diff，确认不包含真实隐私、密钥、爬虫产物或依赖缓存。
- [x] 4.2 在 PR 模板中加入 Mock 数据和状态覆盖检查项。
- [x] 4.3 准备合并到 `develop` 的首轮 PR，并通知成员从各自 feature 分支同步。

