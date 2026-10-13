"""统一响应包与全局异常处理。

契约唯一依据：docs/api-contract.md
- 响应包：{code, message, data, trace_id}
- 错误码：1001 参数错误 / 1002 未登录 / 1003 无权限 / 1006 用户名重复

约定（两层，待与队长确认后补入 docs/api-contract.md）：
- 业务错误统一返回 HTTP 200，错误由响应体中的 code 区分（1001/1002/1003/1006）。
  原因见 frontend/src/api/index.ts —— 请求封装对非 2xx 直接抛错，
  只有 HTTP 200 时才会把响应体交给业务层处理。
- HTTP 层错误（404 路由不存在、405 方法不允许等）保留原 HTTP 状态码，
  仅把响应体统一成同一形状；此时 code 直接沿用 HTTP 状态码。
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class BizCode:
    """业务错误码，取值与 docs/api-contract.md 保持一致。"""

    OK = 0
    PARAM_ERROR = 1001
    UNAUTHORIZED = 1002
    FORBIDDEN = 1003
    USERNAME_EXISTS = 1006
    # 以下三项契约暂未定义，为本 PR 提出的补充，待队长确认后补入契约（见 PR 描述）：
    # 1008 登录失败次数超过阈值（tasks.md 3.2），1500 未捕获的服务端异常
    TOO_MANY_ATTEMPTS = 1008
    INTERNAL_ERROR = 1500
    # 产品书 6.0.4 已定义：缺少来源信息，拒绝入库（管理端语料/规则维护，tasks.md 8.2、8.6）
    MISSING_SOURCE = 4001
    # 产品书 6.0.4 / 6.2.6–6.2.9：资格规则数据缺失。
    # 报考约束引擎在规则数据未入库时**必须**返回本码，绝不静默放行（8.5 实现纪律第 3 条）。
    RULE_MISSING = 3001


class BizError(Exception):
    """可预期的业务异常，由全局处理器转成统一响应包。"""

    def __init__(self, message: str, code: int = BizCode.PARAM_ERROR) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def new_trace_id() -> str:
    """生成请求追踪号。"""
    return str(uuid4())


def ok(data: Any = None, message: str = "success", code: int = BizCode.OK) -> dict[str, Any]:
    """成功响应包。"""
    return {"code": code, "message": message, "data": data, "trace_id": new_trace_id()}


def fail(
    message: str, code: int = BizCode.PARAM_ERROR, trace_id: str | None = None
) -> dict[str, Any]:
    """失败响应包，data 恒为 None。"""
    return {
        "code": code,
        "message": message,
        "data": None,
        "trace_id": trace_id or new_trace_id(),
    }


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理，保证任何出口都符合统一响应包。"""

    @app.exception_handler(BizError)
    async def _handle_biz_error(request: Request, exc: BizError) -> JSONResponse:
        return JSONResponse(status_code=200, content=fail(exc.message, exc.code))

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = exc.errors()
        first = errors[0] if errors else {}
        if first.get("type") == "json_invalid":
            return JSONResponse(
                status_code=200,
                content=fail("参数错误：请求体不是合法 JSON", BizCode.PARAM_ERROR),
            )

        # loc 形如 ('body','profile','score') 或 ('query','q')，去掉来源类型后展示字段路径
        location = [str(item) for item in first.get("loc", [])]
        if location and location[0] in {"body", "query", "path", "header", "cookie"}:
            location = location[1:]
        field = ".".join(location)
        detail = first.get("msg", "参数不合法")
        message = f"参数错误：{field} {detail}" if field else f"参数错误：{detail}"
        return JSONResponse(status_code=200, content=fail(message, BizCode.PARAM_ERROR))

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        # HTTP 层错误保留原状态码，仅统一响应体形状
        code = {401: BizCode.UNAUTHORIZED, 403: BizCode.FORBIDDEN}.get(
            exc.status_code, exc.status_code
        )
        return JSONResponse(
            status_code=exc.status_code, content=fail(str(exc.detail), code)
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        trace_id = new_trace_id()
        logging.getLogger("zhixuan").exception("未处理异常 trace_id=%s", trace_id)
        # 不向前端暴露堆栈，仅回传 trace_id 便于对日志
        return JSONResponse(
            status_code=500,
            content=fail("服务器内部错误", BizCode.INTERNAL_ERROR, trace_id),
        )
