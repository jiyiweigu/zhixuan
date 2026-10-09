# 智选志愿（智选志愿 · 高考志愿填报 AI 助手）

> 基于知识库与检索增强生成（RAG）的高考志愿填报辅助决策平台。
> 用户端 + 知识库管理端，覆盖 26 类升学途径，支持路径资格自检与答案溯源。
> **本工具仅供参考，不构成任何录取承诺或填报建议。**

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3 + TypeScript + Vite + Element Plus + ECharts |
| 后端 | Python 3.11 + FastAPI + SQLAlchemy 2.0 + Pydantic v2 |
| 数据库 | PostgreSQL 16 + pgvector |
| 检索 | pgvector(HNSW) + BM25 + RRF 融合 |
| 模型 | bge-small-zh-v1.5（Embedding）/ bge-reranker-base（Rerank）/ 通义千问 qwen-plus（生成） |

## 目录结构

```
zhixuan/
├── frontend/     # Vue3（用户端 + /admin 管理端，同工程不同路由）
├── backend/      # FastAPI
├── data/         # 采集脚本、原始语料（小样本）、清洗脚本、途径规则
├── db/           # schema.sql 与 Alembic 迁移
├── docs/         # 开发产品书、接口说明、评测报告
└── scripts/      # 启动与初始化脚本
```

## 本地启动

### 1. 数据库

```bash
# 需已安装 PostgreSQL 16，并在目标库中启用扩展
CREATE EXTENSION IF NOT EXISTS vector;
```

### 2. 后端

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows；macOS/Linux 用 source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # 填写数据库连接与大模型 API Key（勿提交 .env）
alembic upgrade head
uvicorn app.main:app --reload   # http://localhost:8000/docs
```

### 3. 前端

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev                     # http://localhost:5173
```

## 默认账号

| 端 | 账号 | 密码 |
|---|---|---|
| 用户端 | 【待填】 | 【待填】 |
| 管理端 `/admin` | 【待填】 | 【待填】 |

> 仅用于本地演示，首次启动后请自行修改。

## 接口文档

- 本地运行后访问 `http://localhost:8000/docs`（自动生成）。
- **字段级契约以《开发产品书_智选志愿.md》第 6 章为准**，前端 mock 与 TS 类型须与之逐字段一致。

## 协作方式

见 [CONTRIBUTING.md](./CONTRIBUTING.md)。**核心三条**：

1. 不直接往 `main` / `develop` 推代码，一律走 `feature/*` 分支 + Pull Request；
2. 不使用 `git push -f` 与 `git reset --hard`；
3. 不提交 `.env`、API Key、`node_modules/`。

## 分支

| 分支 | 用途 |
|---|---|
| `main` | 稳定可演示版本（仅队长合并，打 tag） |
| `develop` | 集成分支（功能 PR 合入此处） |
| `feature/<模块>-<姓名拼音>` | 个人开发分支 |

## 免责声明

本平台基于各省教育考试院、阳光高考平台及各高校官方公开数据提供志愿填报的辅助参考，**不构成任何录取承诺或填报建议**；升学途径资格请以各省教育考试院官方审核结果为准。所有数据以官方发布为准。
