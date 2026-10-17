# 智选志愿开发入口

## 快速启动

**一键起全套（推荐）**：双击 `scripts\start-all.bat`
→ 自动启动后端 `:8000` + 前端 `:5173` 并打开浏览器。

**只起前端**（Vite + Vue 3 + TS）：

```bash
cd frontend
npm install
npm run dev
```

> 前端**默认走 Mock**，无需后端即可看页面。要看真实数据，把 `frontend/.env.local` 设为
> `VITE_USE_MOCK=false` 与 `VITE_API_BASE_URL=http://127.0.0.1:8000`，再重启 Vite。

**只起后端**（FastAPI）：

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

> 本机已配好的解释器由 `scripts\start-backend.bat` 自动探测；也可在
> `scripts/local-paths.bat` 里写死（该文件不入库）。
> 完整启动、演示动线与排错见 **[本地启动与演示指南](docs/本地启动与演示指南.md)**。

## 常用信息

- 接口契约：[docs/api-contract.md](docs/api-contract.md)（前后端对齐的唯一依据）
- FastAPI 交互文档：`http://localhost:8000/docs`
- 前端 Mock 默认开启；联调真实后端时在 `frontend/.env.local` 设 `VITE_USE_MOCK=false` 与 `VITE_API_BASE_URL=http://127.0.0.1:8000`（样例见 `frontend/.env.example`）
- 类型检查：`cd frontend && npm run typecheck`

## 开发文档

- [成员开发指南](docs/development-guide.md)
- [第一轮任务分工](docs/team-tasks.md)
- [Mock 数据说明](docs/mock-data.md)

## 验收

```bash
python tests/mock_contract_smoke.py
```
