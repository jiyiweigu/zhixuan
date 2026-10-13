# Mock 数据说明

设置 `VITE_USE_MOCK=true`（默认）即可离线开发。数据位于 `frontend/src/mocks/index.ts`，按模块和状态选择。

所有来源均标记为“演示数据（非官方）”，不得作为政策、分数线或院校事实展示。真实爬虫接入时必须输出 API 契约中的 DTO、`source_name/source_url/year`，页面无需改动。

状态覆盖：认证 success/error；档案 success/empty；资格 eligible/pending/ineligible；问答 success/lowConfidence/empty；方案 success/empty；院校 success/empty。
