# 智选志愿前后端骨架
## 启动前端
cd frontend
npm install
npm run dev

## 启动后端
cd backend
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# 开发入口
- 接口契约：[docs/api-contract.md](docs/api-contract.md)
- 前端：`cd frontend && npm install && npm run dev`
- 后端：`cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload --port 8000`
- FastAPI 文档：`http://localhost:8000/docs`
- 前端 Mock 默认开启；设置 `VITE_USE_MOCK=false` 后连接真实 API。
## 第一轮文档
- [Mock 数据说明](docs/mock-data.md)
- [成员开发指南](docs/development-guide.md)
- [第一轮任务分工](docs/team-tasks.md)
- 验收：`python tests/mock_contract_smoke.py`
