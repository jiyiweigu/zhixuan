## 1. 适配器与配置

- [x] 1.1 新增 `backend/app/rag/reranker.py`，定义 reranker 协议、确定性的 FakeReranker 和可选 BGE reranker。
- [x] 1.2 新增 `backend/app/rag/generation.py`，定义受限生成协议、FakeGenerator 和 OpenAI-compatible Generator。
- [x] 1.3 在配置与 `.env.example` 增加 rerank、generation、top-k、超时等环境变量，默认全部离线可用。
- [x] 1.4 在 `backend/app/rag/__init__.py` 导出新增适配器，并补充可选依赖说明。

## 2. 检索与证据组装

- [x] 2.1 在问答服务中批量加载 `KnowledgeChunk`、`KnowledgeDoc` 和 `Source`，组装正文、元数据和来源字段。
- [x] 2.2 实现省份、`pathway_id` 过滤及无结果时的安全回退标记。
- [x] 2.3 接通 T2 embedding、向量检索、BM25 与 `ai_support.rrf_merge`，输出统一候选结构。
- [x] 2.4 接通 reranker，按重排结果截取最终 top-K，并保留分数和来源片段。
- [x] 2.5 实现引用构造，确保每条引用包含 `source_name`、`source_url`、`year`、`snippet` 和 `chunk_id`。

## 3. QA 服务闭环

- [x] 3.1 重构 `backend/app/services/qa.py` 的内部问答 pipeline，使 GET 与 POST 共用同一检索和生成逻辑。
- [x] 3.2 实现按 `session_id` 读取最近历史，并对“它/这个学校/该校”等指代问题进行最小上下文改写。
- [x] 3.3 实现无证据优先兜底，确认无证据时不调用 generator，并返回低置信结果。
- [x] 3.4 实现有证据的受限生成，要求回答只依据片段并附引用编号。
- [x] 3.5 实现生成异常降级为检索摘要，设置 `degraded=true` 并记录错误。
- [x] 3.6 统一输出 confidence 数值与 confidence_level，接入 `ai_support.classify_confidence` 或等价单一判定入口。
- [x] 3.7 完成 `QaLog` 落库，并在低置信或高风险问题时创建唯一 pending `ReviewTask`。
- [x] 3.8 保持 `/api/qa`、`/api/qa/ask`、`/api/qa/history` 的路由和 DTO 字段完全兼容。

## 4. 测试与回归

- [x] 4.1 新建 `backend/test_qa_rag.py`，覆盖 Fake embedding、检索、RRF、rerank、Fake generation 全链路。
- [x] 4.2 测试无证据时 generator 调用次数为零，并验证固定兜底话术和低置信字段。
- [x] 4.3 测试生成失败降级、引用完整性和 `degraded` 标记。
- [x] 4.4 测试低置信问答创建 `ReviewTask`，并验证重复请求不重复入队。
- [x] 4.5 测试 `QaLog` 字段、多轮指代改写和 API 契约 DTO 字段。
- [x] 4.6 运行 `test_qa_rag.py`、`test_index.py`、`test_models.py`、`test_admin.py` 及问答历史回归，确认不联网、不下载模型、不使用 GPU。

## 5. 文档与交接

- [x] 5.1 更新 `docs/ai/implementation.md`，说明真实链路、Fake 回落、无证据和生成失败行为。
- [x] 5.2 检查不修改 `docs/api-contract.md`、问答路由签名和真实密钥，记录真实 BGE/Qwen 与 PostgreSQL 的部署验证限制。
- [x] 5.3 运行 OpenSpec 校验并整理 `feature/ai-qa` 到 `develop` 的交接说明。
