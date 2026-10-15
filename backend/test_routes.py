"""后端接口契约冒烟测试。

断言 OpenAPI 暴露的路径与 docs/api-contract.md 完全一致，防止契约漂移。

无需 pytest，直接运行：
    cd backend && .venv\\Scripts\\python.exe test_routes.py

说明：FastAPI 0.143 起 app.routes 不再拍平被 include 的子路由，
因此这里改用 app.openapi()，与框架版本无关，并顺带验证 OpenAPI 可用（tasks.md 1.5）。

契约 v1.2 起，本文件列出的全部接口均已在 docs/api-contract.md 中登记
（新增接口见 6.1 节），原先的 "NEW / 待补入契约" 标记已按约定删除。
"""

from __future__ import annotations

from app.main import app

EXPECTED = {
    ("/api/health", "get"),
    ("/api/auth/register", "post"),
    ("/api/auth/login", "post"),
    ("/api/user/profile", "get"),
    ("/api/user/profile", "put"),
    ("/api/pathways", "get"),
    ("/api/pathways/eligibility-check", "post"),
    ("/api/qa", "get"),
    # NEW：6.1 结构化问答（留痕 + 会话历史）
    ("/api/qa/ask", "post"),
    ("/api/qa/history", "get"),
    ("/api/plans", "post"),
    # NEW：6.1 推荐与方案风险体检
    ("/api/recommend", "post"),
    ("/api/plan/risk-check", "post"),
    ("/api/schools", "get"),
    # NEW：6.1 一分一段（分数 ↔ 位次）
    ("/api/scores/segment", "get"),
    # NEW：6.1 收藏
    ("/api/user/favorites", "get"),
    ("/api/user/favorites", "post"),
    ("/api/user/favorites", "delete"),
    # NEW：新增接口（途径详情 3.、区域判定 3.、途径区域名单 6.1）
    ("/api/pathways/region-check", "get"),
    ("/api/pathways/{pathway_id}", "get"),
    ("/api/pathways/{pathway_id}/regions", "get"),
    # NEW：新增接口，待补入契约（认证 3.1/3.3）
    ("/api/auth/logout", "post"),
    ("/api/auth/me", "get"),
    ("/api/user", "delete"),
    # NEW：新增接口，待补入契约（方案保存/命名/编辑，产品书 6.1.7、tasks.md 6.6）
    ("/api/user/plans", "get"),
    ("/api/user/plans", "post"),
    ("/api/user/plans/{plan_id}", "get"),
    ("/api/user/plans/{plan_id}", "put"),
    ("/api/user/plans/{plan_id}", "delete"),
    # NEW：新增接口，待补入契约（院校详情/画像/生活/并排对比，产品书 6.5.2–6.5.5、tasks.md 7.1/7.2）
    ("/api/schools/{school_id}", "get"),
    ("/api/schools/{school_id}/profile", "get"),
    ("/api/schools/{school_id}/life", "get"),
    ("/api/schools/compare", "post"),
    # NEW：新增接口，待补入契约（专业检索与详情，产品书 6.5.6/6.5.7、tasks.md 7.1）
    ("/api/majors", "get"),
    ("/api/majors/{major_id}", "get"),
    # NEW：新增接口，待补入契约（管理端，产品书 6.6、tasks.md 8.1/8.2/8.6/8.7）
    ("/api/admin/login", "post"),
    ("/api/admin/me", "get"),
    ("/api/admin/docs", "get"),
    ("/api/admin/docs", "post"),
    ("/api/admin/docs/{doc_id}", "delete"),
    ("/api/admin/pathways", "get"),
    ("/api/admin/pathways", "post"),
    ("/api/admin/pathways/{pathway_id}", "put"),
    ("/api/admin/pathway-rules", "get"),
    ("/api/admin/pathway-rules", "post"),
    ("/api/admin/pathway-rules/{rule_id}", "put"),
    ("/api/admin/pathway-regions", "get"),
    ("/api/admin/stats", "get"),
    ("/api/admin/audit-logs", "get"),
    # NEW：新增接口，待补入契约（审核工作台，产品书 6.6.9/6.6.10、tasks.md 8.4/8.5）
    ("/api/admin/review/tasks", "get"),
    ("/api/admin/review/tasks/{task_id}", "get"),
    ("/api/admin/review/tasks/{task_id}", "post"),
    ("/api/admin/review/enqueue", "post"),
    # NEW：新增接口，待补入契约（索引管理，产品书 6.6.4/6.6.5、tasks.md 8.3）
    ("/api/admin/index/rebuild", "post"),
    ("/api/admin/index/tasks/{task_id}", "get"),
    # NEW：新增接口，待补入契约（报考约束，产品书 v1.1 6.2.6–6.2.9、8.5 四道闸门、M2-7～M2-14）
    ("/api/provinces/{code}/rules", "get"),
    ("/api/eligibility/check", "post"),
    ("/api/user/eligibility/check", "post"),
    ("/api/majors/{major_id}/requirements", "get"),
    # NEW：新增接口，待补入契约（管理端·报考约束规则维护三组，产品书 6.6 v1.1）
    ("/api/admin/province-rules", "get"),
    ("/api/admin/province-rules", "post"),
    ("/api/admin/province-rules/{rule_id}", "put"),
    ("/api/admin/subject-requirements", "get"),
    ("/api/admin/subject-requirements", "post"),
    ("/api/admin/subject-requirements/{rule_id}", "put"),
    ("/api/admin/physical-restrictions", "get"),
    ("/api/admin/physical-restrictions", "post"),
    ("/api/admin/physical-restrictions/{rule_id}", "put"),
    # NEW：契约 8.8 四组管理端规则维护（v1.2 补齐）
    ("/api/admin/admission-requirements", "get"),
    ("/api/admin/admission-requirements", "post"),
    ("/api/admin/admission-requirements/{rule_id}", "put"),
    ("/api/admin/major-tuition", "get"),
    ("/api/admin/major-tuition", "post"),
    ("/api/admin/major-tuition/{rule_id}", "put"),
    ("/api/admin/rule-dataset-status", "get"),
    ("/api/admin/rule-dataset-status", "put"),
    ("/api/admin/rule-datasets/import", "post"),
}


def test_routes() -> None:
    paths = app.openapi()["paths"]
    actual = {(path, method) for path, item in paths.items() for method in item}

    missing = EXPECTED - actual
    assert not missing, f"缺少契约接口：{sorted(missing)}"

    unexpected = actual - EXPECTED
    assert not unexpected, f"出现契约外接口：{sorted(unexpected)}"


if __name__ == "__main__":
    test_routes()
    print(f"route contract check passed ({len(EXPECTED)} 个接口)")
