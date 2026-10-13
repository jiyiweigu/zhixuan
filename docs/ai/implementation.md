# AI 决策支持实现说明
- `POST /api/qa/ask`：无证据时固定返回知识库暂无数据。
- `POST /api/recommend/trend`：输出 rising/stable/falling/insufficient_data。
- 趋势不参与冲稳保排序，不代表报名人数或录取概率。
- 当前为无模型安全基础实现，真实向量/BM25/RRF/rerank/模型调用后续接入适配器。
