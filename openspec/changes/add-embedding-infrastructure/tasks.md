## 1. 基线与协议

- [x] 1.1 复核 indexing、corpus、knowledge model、config 和当前 Alembic head，记录兼容边界。
- [x] 1.2 创建 `backend/app/rag/embedder.py`，定义 Embedder 协议、维度校验和 L2 归一化。
- [x] 1.3 实现 FakeEmbedder、BgeEmbedder、OpenAICompatibleEmbedder，默认无配置回退 Fake。

## 2. 存储与检索

- [x] 2.1 创建 `backend/app/rag/retrieval.py`，实现 SQLite 余弦 top-k 和轻量 BM25。
- [x] 2.2 在 indexing 注册适配器，接通切块、向量化、JSON 落库和任务进度。
- [x] 2.3 增加配置项和 `.env.example`，密钥只从环境变量读取。
- [x] 2.4 编写以 `0009_school_major_score_identity` 为基线的 PostgreSQL/pgvector 可选迁移。
- [x] 2.5 更新 requirements，确保可选模型/PG 依赖不阻塞 SQLite 默认环境。

## 3. 测试

- [x] 3.1 创建 `backend/test_rag_embedding.py`，覆盖 Fake 确定性、维度和空输入。
- [x] 3.2 测试切块、向量化、SQLite 落库、余弦 top-k 和 BM25 排序。
- [x] 3.3 测试 index_task 的成功、partial、failed 和单条失败继续处理。
- [x] 3.4 确认测试不联网、不用 GPU、不下载模型，并运行现有索引/模型回归测试。

## 4. 交接

- [x] 4.1 在 `docs/ai/embedding.md` 记录配置、双模式、Fake/BGE/API 切换和限制。
- [x] 4.2 检查变更不触碰 API 契约、qa 业务和真实密钥，准备 `feature/ai-embedding` PR 到 `develop`。

