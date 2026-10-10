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
