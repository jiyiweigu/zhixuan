# 智选志愿开发入口

## 快速启动

**前端**（Vite + Vue 3 + TS，默认走 Mock，无需启动后端）：

```bash
cd frontend
npm install
npm run dev
```

**后端**（FastAPI）：

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## 常用信息

- 接口契约：[docs/api-contract.md](docs/api-contract.md)（前后端对齐的唯一依据）
- FastAPI 交互文档：`http://localhost:8000/docs`
- 前端 Mock 默认开启；联调真实后端时设置 `VITE_USE_MOCK=false`（见 `frontend/.env.example`）
- 类型检查：`cd frontend && npm run typecheck`

## 开发文档

- [成员开发指南](docs/development-guide.md)
- [第一轮任务分工](docs/team-tasks.md)
- [Mock 数据说明](docs/mock-data.md)

## 验收

```bash
python tests/mock_contract_smoke.py
```
