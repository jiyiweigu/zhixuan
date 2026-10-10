# 智选志愿 · 高考志愿填报 AI 助手

> 2026 年第十四届全国大学生数字媒体科技作品及创意竞赛参赛项目
> 基于知识库与检索增强生成（RAG）的高考志愿填报辅助决策平台 —— 用户端 + 知识库管理端，覆盖 26 类升学途径，支持路径资格自检与答案溯源。
>
> ⚠️ **本工具仅供参考，不构成任何录取承诺或填报建议。** 升学途径资格请以各省教育考试院官方审核结果为准。

**关键时间**：2026 年第十四届全国大学生数字媒体科技作品及创意竞赛，报名及作品提交截止 **2026-10-23 23:59:59**
**开源许可**：[MIT](./LICENSE) ｜ 仓库已公开，欢迎交流、提 Issue 与反馈

---

## 一、这个仓库是什么

同时承担两个角色：

1. **竞赛工作仓** —— 存赛事资料、提交文档、开发规范、OpenSpec 规划产物；
2. **开发仓** —— 承载智选志愿的前后端代码。

**当前状态**：文档与规划已完成，应用代码（`frontend/`、`backend/` 脚手架）由队长推送后出现在根目录。

## 二、文档索引

| 文件 | 用途 | 是否随作品提交 |
|---|---|---|
| `作品介绍_智选志愿（提交版）.md` | 第一章~第十章 + 截图清单 / 演示脚本 / 26 类途径附录。导出 PDF 即「作品说明文档」 | ✅ 提交 |
| `开发产品书_智选志愿.md` | 团队执行手册：功能拆解（M0–M7）、前端/后端拆解、**第 6 章字段级接口契约**、数据字典、RAG 与规则引擎契约、分工矩阵、GitHub 规范、15 天计划 | ❌ 不提交 |
| `提交材料清单_智选志愿.md` | 提交物清单 + 前置审查红线 + 责任人 + D15 核对表 | 内部用 |
| `数媒大赛_要点与选题建议.md` | 竞赛要点速览与选题论证 | 内部用 |
| `openspec/` | OpenSpec 规范驱动开发产物（proposal / specs / design / tasks） | 内部用 |
| 三份竞赛 PDF | 通知、参赛指南、评分标准（原始依据） | ❌ 不提交 |

## 三、团队协作（**新人必读，先看这个**）

- 团队 5 人，**主账号 = 队长账号**，其余 4 人由队长在 `Settings → Collaborators` 邀请（权限 **Write**）；**团队内部不使用 Fork 流程**（外部协作者请走 Fork + PR）。
- 三分支模型：`main`（稳定可演示，仅队长经 PR 合并）→ `develop`（集成）→ `feature/<姓名拼音>`（个人，已建好：`feature/xu`、`feature/fei`、`feature/zhang`、`feature/yuan`）。
- 完整规范见 **[CONTRIBUTING.md](./CONTRIBUTING.md)**（含每日六步流程、提交信息格式、10 条禁止事项、求助模板）。

**核心三条**：

1. 不直接往 `main` / `develop` 推代码，一律走 `feature/*` 分支 + Pull Request；
2. 不使用 `git push -f` 与 `git reset --hard`；
3. 不提交 `.env`、API Key、`node_modules/`。

## 四、统一技术栈（已冻结，D2 后不得变更）

| 层 | 技术 |
|---|---|
| 前端 | Vue 3 + TypeScript + Vite + Element Plus + ECharts |
| 后端 | Python 3.11 + FastAPI + SQLAlchemy 2.0 + Pydantic v2 |
| 数据库 | PostgreSQL 16 + pgvector |
| 检索 | pgvector(HNSW) + BM25 + RRF 融合 + Rerank |
| 模型 | bge-small-zh-v1.5（Embedding）/ bge-reranker-base（Rerank）/ 通义千问 qwen-plus（生成） |

## 五、规划中的应用目录结构

```
zhixuan/
├── frontend/     # Vue3（用户端 + /admin 管理端，同工程不同路由）
├── backend/      # FastAPI
├── data/         # 采集脚本、原始语料（仅小样本）、清洗脚本、途径规则
├── db/           # schema.sql 与 Alembic 迁移
├── docs/         # 开发产品书、接口说明、评测报告
└── scripts/      # 启动与初始化脚本
```

## 六、本地启动（脚手架就绪后适用）

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

## 七、接口文档

- 本地运行后访问 `http://localhost:8000/docs`（FastAPI 自动生成）。
- **字段级契约以《开发产品书_智选志愿.md》第 6 章为准**，前端 mock 与 TS 类型须与之逐字段一致。

## 八、开发进度与任务

按 `openspec/changes/add-zhixuan-volunteer-assistant/tasks.md` 推进（10 个任务组、约 60 条任务，每条带角色代号与验证方式）。
里程碑：M1(D4) OpenAPI 就绪 → M2(D8) 向量库可用 → M3(D10) RAG 打通 → M4(D12) 全链路 → M5(D13) Demo 冻结 → M6(D14) 材料齐备 → M7(D15) 提交取编号。

## 九、数据与合规约定（涉及作品评分，务必遵守）

- 所有事实性数据必须带 `source_name`、`source_url`、`year` 三要素，缺一不得入库、不得展示。
- 事实性结论**没有引用就不展示**。
- 禁止在代码、日志、提交中出现真实用户隐私数据。
- 新增第三方依赖前先在站会提出并说明许可；第三方资源与数据来源须在《知识产权说明》中列明。

## 十、开源许可

本项目采用 **[MIT 许可证](./LICENSE)**，你可以在保留版权声明的前提下自由使用、修改、分发，包括商业用途。

**但以下内容不在本许可范围内**，权利归各自权利人所有：

| 内容 | 说明 |
|---|---|
| 竞赛官方文件 | 仓库中的竞赛通知、参赛指南、评分标准等 PDF，版权归赛事主办方 |
| 第三方开源组件与模型 | Vue、Element Plus、ECharts、FastAPI、PostgreSQL、pgvector、bge 系列模型、通义千问、思源黑体等，遵循其各自许可 |
| 招生数据来源 | 各省教育考试院、阳光高考平台、各高校官方发布等，原始权利归发布方 |

> 团队内部的工作笔记、分工过程记录不入库（见 `.gitignore`）。

## 十一、免责声明

本平台基于各省教育考试院、阳光高考平台及各高校官方公开数据，提供志愿填报的辅助参考，**不构成任何录取承诺或填报建议**。所有数据以官方发布为准。
