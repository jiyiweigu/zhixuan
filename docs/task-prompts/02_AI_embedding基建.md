# T2【AI】embedding + 向量存储基建

> **任务属性**：复杂度 `高` ｜ 核心度 `核心` ｜ 推荐模型 `高级（推理型）` —— AI 支柱之一，涉及 pgvector 接入与双环境开关，逻辑严谨性要求高。

> 复制本文件全文作为提示词投喂。任务性质：后端 AI 基础设施，纯增量，不碰已有业务逻辑。

## 项目背景速览（必读）

- 项目「智选志愿」：高考志愿填报 AI 助手 + 知识库管理端，全国大学生数媒竞赛作品，10-23 截止。
- 仓库：`C:\Users\Administrator\Desktop\数媒大赛`（git，基于 `develop` 新开 `feature/ai-embedding` 分支）。
- 技术栈：FastAPI + SQLAlchemy + Alembic；开发期 SQLite（`ZHIXUAN_DATABASE_URL` 可覆盖），目标 PostgreSQL 16 + pgvector。
- 目标 AI 组件：**bge-small-zh**（embedding，512 维）+ **bge-reranker**（重排，下一任务用）+ **qwen-plus**（生成，走 API）。
- 契约：`docs/api-contract.md`（v1.4）唯一 DTO 基线。
- Python 环境：`C:\Users\Administrator\.workbuddy\binaries\python\envs\zhixuan\Scripts\python.exe`；测试直接 `python test_xxx.py`（自带 runner）。
- 数据红线：宁可缺、不可猜；演示与真实实现必须可区分、可切换。

## 现状（已完成的部分，不要重做）

1. **索引模块骨架已存在**：`backend/app/services/indexing.py` 提供语料切块（chunk）与索引任务管理，并预留了 **`register_embedder(embedder)` 注入点**——本任务的接口设计必须基于它扩展，不要另起炉灶。
2. **语料切块服务已存在**：`backend/app/services/corpus.py`（含 CHUNK 常量与批量处理）。
3. **表已建好**：`backend/app/models/knowledge.py` 有 `knowledge_chunk`（**`embedding` 字段目前是 JSON 文本占位**）、`index_task`、`qa_log`、`review_task`。
4. **依赖现状**：`backend/requirements.txt` 里**没有任何向量/大模型依赖**（无 pgvector、sentence-transformers）。
5. `backend/app/rag/` 目录只有一个空 `__init__.py`——这是本任务的主战场。

## 任务要求

1. **定义 Embedder 适配器协议**（放在 `backend/app/rag/` 下，例如 `embedder.py`）：
   - 抽象基类/Protocol：`embed(texts: list[str]) -> list[list[float]]`，附带 `name`、`dim` 属性。
   - 至少三个实现：
     a. `BgeEmbedder`：基于 bge-small-zh（本地推理，生产用）；
     b. `OpenAICompatibleEmbedder`：走 OpenAI 兼容 API（qwen 系兼容端点，密钥从环境变量读，绝不硬编码）；
     c. `FakeEmbedder`：确定性伪向量（如 hash 到固定维度），**测试与无网环境用**。
   - 通过 `indexing.register_embedder()` 注册；默认在无配置时回落 FakeEmbedder 并打日志说明「当前为演示实现」——与项目现有 `core/demo.py` 的演示标记风格一致。
2. **向量存储双模式**：
   - PG 模式：引入 `pgvector` 依赖与 `Vector` 列类型（新增 Alembic 迁移 `2026xxxx_0010_*`，down_revision 指向 `20261014_0009_school_major_score_identity`；SQLite 下用现有 JSON 列继续跑，**不要让开发环境强依赖 PG**）。
   - SQLite 模式：embedding 存 JSON（现状），检索余弦相似度用 numpy 内存计算（语料量级几千 chunk，可接受）。
   - 用配置开关选择（沿用 `app/core/config.py` 的 Settings 风格，新增 embedding 相关配置项与 `.env` 支持）。
3. **打通「切语料 → 向量化 → 落库」**：在 indexing 流程里接 embedder，`index_task` 记录进度与失败原因；单条 chunk 失败不中断整批（如实记录，不静默吞）。
4. **BM25 检索基线**：同文件或 `rag/retrieval.py` 里实现一个轻量 BM25（中文按字符或 jieba 分词均可，依赖加入 requirements），供下一任务混合检索用。
5. **测试**：`backend/test_rag_embedding.py`（新建，风格参照 `test_importers.py` 的自带 runner + 中文用例名）：
   - FakeEmbedder 确定性（同输入同输出）；
   - 切块 → 向量化 → 落库 → SQLite 模式检索 top-k 正确；
   - index_task 状态流转正确；
   - **全部测试不允许网络与 GPU**（BgeEmbedder 的真模型测试用 `@skip_if_no_model` 之类标记跳过）。

## 交付物清单

- `backend/app/rag/embedder.py`、`backend/app/rag/retrieval.py`（+ 非空 `__init__.py` 导出）
- Alembic 迁移 `2026xxxx_0010_*`（仅 PG 分支生效的向量列/索引，SQLite 不破坏）
- `backend/requirements.txt` 增补依赖（附版本号；国内环境用 `-i https://pypi.org/simple` 安装）
- `backend/test_rag_embedding.py` 全绿
- PR：`feature/ai-embedding` → `develop`（squash），`feat(rag): embedding 适配器与向量存储双模式`

## 禁止事项

- 不要动 `docs/api-contract.md`、`backend/app/models/knowledge.py` 的既有列、`services/qa.py`（那是 T3 的活）。
- 不要在代码或测试里硬编码任何 API key（环境变量 / `.env`，且 `.env` 已在 `.gitignore`）。
- 不要让默认开发环境必须下载模型/必须连 PG 才能跑测试。
