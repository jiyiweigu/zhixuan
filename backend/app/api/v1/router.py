"""v1 路由汇总。

模块划分与 docs/api-contract.md 一致，各模块接口定义在同名文件内：
    health     健康检查
    auth       认证（注册/登录）
    profile    考生档案
    pathways   升学途径与资格自检
    qa         可溯源问答
    plans      志愿方案生成
    user_plans 志愿方案保存/命名/编辑/删除（产品书 6.1.7）
    schools    院校检索、详情与画像
    majors     专业检索与详情
    admin      管理端（产品书 6.6；tasks.md 8.1/8.2/8.6/8.7），子包 app/api/v1/admin/
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    auth,
    eligibility,
    health,
    majors,
    pathways,
    plans,
    profile,
    qa,
    schools,
    user_plans,
)
from app.core.config import settings

router = APIRouter(prefix=settings.api_prefix)

router.include_router(health.router)
router.include_router(auth.router)
router.include_router(profile.router)
router.include_router(eligibility.user_router)
router.include_router(pathways.router)
router.include_router(eligibility.router)
router.include_router(qa.router)
router.include_router(plans.router)
router.include_router(user_plans.router)
router.include_router(schools.router)
router.include_router(majors.router)
router.include_router(admin.router)
