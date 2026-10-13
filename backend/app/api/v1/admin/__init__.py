"""管理端接口包（前缀 ``/api/admin``，产品书 6.6；tasks.md 8.1–8.7）。

挂载方式（见 app/api/v1/router.py）：
- ``auth.router``（``/login``、``/me``）**不加**统一鉴权依赖——``/login`` 必须公开，
  ``/me`` 自行声明 ``get_current_admin``；
- 其余子路由统一挂在 ``protected`` 上，一次性要求 ``get_current_admin``，
  因此漏写依赖也不会把接口暴露出去。缺令牌 1002、持 C 端令牌 1003。

已覆盖：
    8.1 鉴权与操作留痕（auth.py + audit.py）
    8.2 语料管理（docs.py）
    8.3 索引管理（index.py）
    8.4 审核工作台（review.py）
    8.5 审核操作与回流（review.py）
    8.6 途径与资格规则维护（pathways.py）
    8.7 数据统计（stats.py）

至此管理端 6.6 的接口已全部落地；8.3 的向量化计算仍待 ④ 号 5.2 通过
``services.indexing.register_embedder`` 注入（未注入时任务如实标注为 partial）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.admin import audit, auth, docs, index, pathways, review, rules, stats
from app.core.deps import get_current_admin

router = APIRouter(prefix="/admin", tags=["管理端"])

# 公开：登录（/me 在 auth.router 内自行鉴权）
router.include_router(auth.router)

# 受保护：统一要求管理员身份，避免逐个接口漏写依赖
protected = APIRouter(dependencies=[Depends(get_current_admin)])
protected.include_router(docs.router)
protected.include_router(index.router)
protected.include_router(pathways.router)
protected.include_router(rules.router)
protected.include_router(review.router)
protected.include_router(stats.router)
protected.include_router(audit.router)
router.include_router(protected)

__all__ = ["router"]
