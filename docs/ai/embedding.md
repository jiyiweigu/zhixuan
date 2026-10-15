# Embedding 基建说明

默认配置是离线 `FakeEmbedder`，不下载模型、不访问网络、不需要 GPU 或 PostgreSQL。通过 `ZHIXUAN_EMBEDDING_BACKEND` 选择 `fake`、`bge` 或 `openai-compatible`；真实模型依赖见 `requirements-embedding.txt`。

SQLite 继续把向量写入 `knowledge_chunk.embedding` JSON，并使用内存余弦相似度。PostgreSQL 迁移 `0010_embedding_vector` 将现有 `knowledge_chunk.embedding` 转换为原生 `vector(512)`，并创建 HNSW 余弦索引；迁移以 `0009_school_major_score_identity` 为基线，SQLite 执行时不改表。

现有 `services/indexing.register_embedder()` 同时兼容旧的单文本 callable 和新的批量 Embedder 对象。单条向量化失败会记录在索引任务进度中并继续处理。
