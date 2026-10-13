"""前后端接口对齐测试（契约 v1.2 6.1 节）。

本文件回答一个具体问题：**把 `VITE_USE_MOCK` 关掉之后，前端 api 层声明的每个
`/api/...` 路径在后端是否都存在**。历史上这里存在成片的 404，却被
「默认走 Mock」掩盖，所以单独固化为回归测试。

覆盖四类断言：
1. 路径对齐：`frontend/src/api/index.ts` 里出现的所有 `/api/...` 字面量，
   都能在 ``app.openapi()`` 里找到对应路由（动态段按 ``*`` 归一后比较）；
2. 新增接口可跑通：qa/ask、qa/history、recommend、plan/risk-check、
   scores/segment、favorites、pathways/{id}/regions；
3. 鉴权口径与契约一致（Auth: no / yes / optional）；
4. 数据缺失时如实返回 `schema_only` / `unavailable`，不编造数字。

纯脚本，无 pytest 依赖，直接运行：
    cd backend && .venv\\Scripts\\python.exe test_alignment.py
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

# 环境变量必须在导入 app.* 之前设置：settings 在首次导入时读取一次
_WORK = Path(tempfile.mkdtemp(prefix="zhixuan_align_test_"))
os.environ["ZHIXUAN_DATABASE_URL"] = f"sqlite:///{(_WORK / 'align.db').as_posix()}"
os.environ["ZHIXUAN_SECRET_KEY"] = "test-secret-key-align-suite-at-least-32-bytes"
os.environ["ZHIXUAN_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402

from app.db.session import create_all  # noqa: E402
from app.main import app  # noqa: E402

create_all()
client = TestClient(app)
logging.getLogger("zhixuan").setLevel(logging.CRITICAL)

FRONTEND_API = Path(__file__).resolve().parent.parent / "frontend" / "src" / "api" / "index.ts"

PASSWORD = "change-me"
CASES: list[tuple[str, Callable[[], None]]] = []
_counter = {"n": 0}


def case(title: str) -> Callable:
    def decorator(func: Callable[[], None]) -> Callable[[], None]:
        CASES.append((title, func))
        return func

    return decorator


# --------------------------------------------------------------------------- #
# 辅助
# --------------------------------------------------------------------------- #
def unique_name(prefix: str = "align") -> str:
    _counter["n"] += 1
    return f"{prefix}{_counter['n']:04d}{int(time.time() * 1000) % 100000}"


def register() -> tuple[str, dict[str, str]]:
    name = unique_name()
    resp = client.post("/api/auth/register", json={"username": name, "password": PASSWORD})
    assert resp.status_code == 200 and resp.json()["code"] == 0, resp.text
    token = resp.json()["data"]["access_token"]
    return name, {"Authorization": f"Bearer {token}"}


def normalize_route(path: str) -> str:
    """把路径里的动态段统一成 ``*``，用于跨端比较。"""
    return re.sub(r"\{[^}]*\}", "*", path)


def backend_signatures() -> set[tuple[str, str]]:
    paths = app.openapi()["paths"]
    return {
        (normalize_route(path), method)
        for path, item in paths.items()
        for method in item
        if method in {"get", "post", "put", "delete", "patch"}
    }


def _iter_template_expressions(text: str) -> list[tuple[int, int, str]]:
    """找出所有 ``${...}`` 表达式，按花括号配对扫描。

    不能用 ``\\$\\{[^}]*\\}`` 这类正则：``${qs({province:p})}`` 内部本身含 ``}``，
    非贪婪匹配会在第一个 ``}`` 处截断，残留 ``)}`` 污染归一化路径，把本来存在的
    路由误判成「前端调了后端不存在的路径」。
    """
    spans: list[tuple[int, int, str]] = []
    index = 0
    length = len(text)
    while index < length:
        if text.startswith("${", index):
            depth = 0
            cursor = index + 1  # 指向 '{'
            while cursor < length:
                if text[cursor] == "{":
                    depth += 1
                elif text[cursor] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                cursor += 1
            if cursor < length:  # 括号闭合，才认作一个表达式
                spans.append((index, cursor + 1, text[index + 2 : cursor]))
                index = cursor + 1
                continue
        index += 1
    return spans


def _normalize_frontend_path(raw: str) -> str:
    """把前端模板路径收敛成可与后端路由比较的骨架。

    - ``${qs({...})}`` 这类「查询串构造器」整体删除（后端路径不含查询串）；
    - ``${id}`` 这类占位符替换为 ``*``，与 ``normalize_route`` 的动态段口径一致；
    - ``/api/admin/review/tasks?status=pending&page=1`` 这类硬编码查询串截断。
    """
    spans = _iter_template_expressions(raw)
    if spans:
        parts: list[str] = []
        cursor = 0
        for start, end, body in spans:
            parts.append(raw[cursor:start])
            # 含调用表达式（qs(...)）的整体丢掉，纯变量才当动态段
            parts.append("" if "(" in body else "*")
            cursor = end
        parts.append(raw[cursor:])
        path = "".join(parts)
    else:
        path = raw
    path = path.split("?", 1)[0]
    return path.rstrip("/") or "/"


def frontend_paths() -> list[tuple[str, str]]:
    """从 api/index.ts 提取所有 ``/api/...`` 字面量，返回 (归一化路径, 源码片段)。"""
    text = FRONTEND_API.read_text(encoding="utf-8")
    found: list[tuple[str, str]] = []
    for match in re.finditer(r"['\"`](/api/[^'\"`]*)['\"`]", text):
        raw = match.group(1)
        found.append((normalize_route(_normalize_frontend_path(raw)), raw))
    return found


# --------------------------------------------------------------------------- #
# 1. 路径对齐（本次改动要解决的根因）
# --------------------------------------------------------------------------- #
@case("01 前端 api 层声明的每个 /api 路径在后端都存在")
def _() -> None:
    if not FRONTEND_API.exists():  # pragma: no cover - 仓库布局变化时提示而非误报
        print(f"    ! 未找到 {FRONTEND_API}，跳过路径对齐检查")
        return

    backend = backend_signatures()
    backend_paths = {path for path, _method in backend}

    missing = []
    for path, raw in frontend_paths():
        # 只比较路径是否命中；方法维度另行在 test_routes.py 覆盖
        if path not in backend_paths:
            missing.append((path, raw))
    assert not missing, f"前端调用了后端不存在的路径：{missing}"


@case("02 契约关键路径全部在后端注册（含本次新增）")
def _() -> None:
    backend = backend_signatures()
    expected = {
        ("/api/qa/ask", "post"),
        ("/api/qa/history", "get"),
        ("/api/recommend", "post"),
        ("/api/plan/risk-check", "post"),
        ("/api/scores/segment", "get"),
        ("/api/user/favorites", "get"),
        ("/api/user/favorites", "post"),
        ("/api/user/favorites", "delete"),
        ("/api/pathways/*/regions", "get"),
        ("/api/eligibility/check", "post"),
        ("/api/user/eligibility/check", "post"),
        ("/api/auth/register", "post"),
        ("/api/auth/login", "post"),
        ("/api/auth/logout", "post"),
        ("/api/auth/me", "get"),
        ("/api/plans", "post"),
    }
    missing = expected - backend
    assert not missing, f"契约路径缺失：{sorted(missing)}"


# --------------------------------------------------------------------------- #
# 2. 问答
# --------------------------------------------------------------------------- #
@case("03 POST /api/qa/ask 游客可用，返回置信度与留痕")
def _() -> None:
    resp = client.post(
        "/api/qa/ask",
        json={"question": "620分能报哪些专业", "session_id": "s-align", "province": "河南"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0, body
    data = body["data"]
    assert data["qa_log_id"], "必须落库并回传 qa_log_id"
    assert data["session_id"] == "s-align"
    assert 0.0 <= float(data["confidence"]) <= 1.0, "契约 4：confidence 为 0~1"
    assert data["confidence_level"] in {"high", "medium", "low"}
    assert isinstance(data["needs_review"], bool)
    assert isinstance(data["degraded"], bool)
    assert isinstance(data["elapsed_ms"], int)
    assert data["citations"], "无可核验来源时也必须返回 citations 结构"


@case("04 GET /api/qa/history 需要登录，且能读回会话历史")
def _() -> None:
    anon = client.get("/api/qa/history", params={"session_id": "s-align"})
    assert anon.json()["code"] == 1002, "契约 6.1：Auth yes"

    _name, auth = register()
    client.post("/api/qa/ask", json={"question": "河南新高考选科怎么选", "session_id": "s-h"})
    resp = client.get("/api/qa/history", params={"session_id": "s-h"}, headers=auth)
    body = resp.json()
    assert body["code"] == 0, body
    page = body["data"]
    assert set(page) == {"items", "total", "page", "page_size"}, page
    assert page["total"] >= 1 and page["items"][0]["question"] == "河南新高考选科怎么选"


@case("05 问答空问题 → 1001")
def _() -> None:
    resp = client.post("/api/qa/ask", json={"question": ""})
    assert resp.json()["code"] == 1001, resp.text


# --------------------------------------------------------------------------- #
# 3. 推荐与风险体检
# --------------------------------------------------------------------------- #
@case("06 POST /api/recommend 游客可用，两种请求写法等价")
def _() -> None:
    flat = client.post(
        "/api/recommend",
        json={"province": "河南", "score": 620, "subject_type": "物理类", "strategy": "稳"},
    )
    assert flat.status_code == 200, flat.text
    body = flat.json()
    assert body["code"] == 0, body
    data = body["data"]
    for key in ("items", "tiers", "citations", "disclaimer", "risk_notes"):
        assert key in data, f"契约 5/6.1：缺少 {key}"
    assert data["citations"], "推荐结果必须带来源"

    nested = client.post(
        "/api/recommend",
        json={
            "profile": {"province": "河南", "score": 620, "subject_type": "物理类"},
            "strategy": "冲",
        },
    )
    assert nested.json()["code"] == 0, nested.text


@case("07 POST /api/recommend 的 school/major/city 收敛为排序倾向")
def _() -> None:
    body = client.post(
        "/api/recommend",
        json={"province": "河南", "score": 620, "subject_type": "物理类", "strategy": "major"},
    ).json()
    assert body["code"] == 0, body
    assert body["data"]["priority"] == "专业优先", body["data"].get("priority")
    assert body["data"]["strategy"] == "稳"


@case("08 POST /api/plan/risk-check 需要登录并返回带来源的风险")
def _() -> None:
    anon = client.post("/api/plan/risk-check", json={"profile": {}, "items": []})
    assert anon.json()["code"] == 1002, "契约 6.1：Auth yes"

    _name, auth = register()
    items = [
        {"tier": "冲", "school_name": "郑州大学", "major_names": ["临床医学"], "min_score_ref": 630},
        {"tier": "冲", "school_name": "河南大学", "major_names": ["法学"], "min_score_ref": 628},
    ]
    resp = client.post(
        "/api/plan/risk-check",
        json={"profile": {"province": "河南", "score": 620, "subject_type": "物理类"}, "items": items},
        headers=auth,
    )
    body = resp.json()
    assert body["code"] == 0, body
    risks = body["data"]["risks"]
    assert isinstance(risks, list)
    codes = {risk["code"] for risk in risks}
    # 两条志愿都在『冲』档 → 稳/保两档为空必须被点名，且『冲』档不得被误报为空
    assert {"NO_WEN", "NO_BAO"} <= codes, f"稳/保为空应被提示：{codes}"
    assert "ALL_CHONG" in codes, f"全部为冲档应被提示：{codes}"
    assert "NO_CHONG" not in codes, f"冲档非空，不应报缺少冲刺志愿：{codes}"
    for risk in risks:
        assert risk["level"] in {"high", "medium", "low"}
        # 契约 6.1：每条风险需给出「级别 / 类型 / 目标 / 说明 / 规则来源」
        assert risk["type"] and risk["target"]
        assert risk["citation"]["source_name"] and risk["citation"]["source_url"]


@case("09 风险体检按分差推断档位，不误报「某档为空」")
def _() -> None:
    _name, auth = register()
    # 620 - 600 = +20 分，落在『保』档区间（strategies.json：11~30）；
    # 不传 tier 时必须在服务层按同一分差口径推断，而不是当作无档位丢弃。
    items = [{"school_name": "演示院校", "major_names": ["示例专业"], "min_score_ref": 600}]
    body = client.post(
        "/api/plan/risk-check",
        json={"profile": {"province": "河南", "score": 620, "subject_type": "物理类"}, "items": items},
        headers=auth,
    ).json()
    assert body["code"] == 0, body
    codes = {risk["code"] for risk in body["data"]["risks"]}
    assert "NO_BAO" not in codes, f"该志愿已计入『保』档，不应报保底为空：{codes}"
    assert "BAO_TOO_FEW" in codes, f"『保』档仅 1 个（< 2），应如实提示：{codes}"
    assert {"NO_WEN", "NO_CHONG"} <= codes, f"稳/冲档确实为空，应如实提示：{codes}"


# --------------------------------------------------------------------------- #
# 4. 一分一段
# --------------------------------------------------------------------------- #
@case("10 GET /api/scores/segment 无数据时如实返回 schema_only")
def _() -> None:
    resp = client.get(
        "/api/scores/segment",
        params={"province": "河南", "year": 2026, "subject_type": "物理类", "score": 620},
    )
    body = resp.json()
    assert body["code"] == 0, body
    data = body["data"]
    assert data["data_status"] in {"available", "schema_only", "unavailable"}
    if data["data_status"] != "available":
        assert data["cumulative_rank"] is None, "未导入数据时不得编造位次"
        assert "score_segment" in data["missing_rule_sets"]


@case("11 GET /api/scores/segment 缺少 score 与 rank → 1001")
def _() -> None:
    resp = client.get(
        "/api/scores/segment",
        params={"province": "河南", "year": 2026, "subject_type": "物理类"},
    )
    assert resp.json()["code"] == 1001, resp.text


# --------------------------------------------------------------------------- #
# 5. 收藏
# --------------------------------------------------------------------------- #
@case("12 收藏：需要登录、幂等新增、可删除")
def _() -> None:
    anon = client.get("/api/user/favorites")
    assert anon.json()["code"] == 1002, "契约 6.1：Auth yes"

    _name, auth = register()
    empty = client.get("/api/user/favorites", headers=auth).json()
    assert empty["code"] == 0 and empty["data"] == []

    first = client.post(
        "/api/user/favorites", json={"target_type": "school", "target_id": "1001"}, headers=auth
    ).json()
    assert first["code"] == 0, first
    fid = first["data"]["favorite_id"]
    assert first["data"]["target_type"] == "school"

    again = client.post(
        "/api/user/favorites", json={"target_type": "school", "target_id": "1001"}, headers=auth
    ).json()
    assert again["data"]["favorite_id"] == fid, "重复收藏应幂等，不产生新行"

    listed = client.get("/api/user/favorites", headers=auth).json()
    assert listed["data"] and len(listed["data"]) == 1, listed

    removed = client.delete(
        "/api/user/favorites",
        params={"target_type": "school", "target_id": "1001"},
        headers=auth,
    ).json()
    assert removed["code"] == 0, removed
    assert client.get("/api/user/favorites", headers=auth).json()["data"] == []


@case("13 收藏：非法 target_type → 1001")
def _() -> None:
    _name, auth = register()
    resp = client.post(
        "/api/user/favorites", json={"target_type": "video", "target_id": "1"}, headers=auth
    )
    assert resp.json()["code"] == 1001, resp.text


@case("14 收藏按用户隔离")
def _() -> None:
    _n1, auth1 = register()
    _n2, auth2 = register()
    client.post(
        "/api/user/favorites", json={"target_type": "major", "target_id": "2001"}, headers=auth1
    )
    assert client.get("/api/user/favorites", headers=auth2).json()["data"] == []


# --------------------------------------------------------------------------- #
# 6. 途径区域名单
# --------------------------------------------------------------------------- #
@case("15 GET /api/pathways/{id}/regions 专项返回名单、非专项返回 unavailable")
def _() -> None:
    national = client.get("/api/pathways/national-plan/regions").json()
    assert national["code"] == 0, national
    data = national["data"]
    assert data["regions"], data
    # 名单尚未核验 → 不得声明 available，也不得给出可报考结论
    assert data["data_status"] == "schema_only", data["data_status"]
    assert "pathway_region" in data["missing_rule_sets"]

    regular = client.get("/api/pathways/regular-batch/regions").json()
    assert regular["data"]["data_status"] == "unavailable"
    assert regular["data"]["regions"] == []


@case("16 GET /api/pathways/{id}/regions 未知途径 → 1001")
def _() -> None:
    resp = client.get("/api/pathways/no-such-pathway/regions")
    assert resp.json()["code"] == 1001, resp.text


# --------------------------------------------------------------------------- #
# 7. 档案 null 语义（契约 8.1）
# --------------------------------------------------------------------------- #
@case("17 档案可空项在 API 层统一为 null，不问「未填」哨兵")
def _() -> None:
    _name, auth = register()
    data = client.get("/api/user/profile", headers=auth).json()["data"]
    for field in ("household_type", "hearing", "smell", "stutter", "color_vision"):
        assert data[field] is None, f"{field} 应为 null，实际 {data[field]!r}"

    # 历史哨兵入参应被收敛：写入后读回为 null，而不是原样存字符串
    client.put(
        "/api/user/profile",
        json={"hearing": "未填", "household_type": "未知"},
        headers=auth,
    )
    data = client.get("/api/user/profile", headers=auth).json()["data"]
    assert data["hearing"] is None and data["household_type"] is None, data


# --------------------------------------------------------------------------- #
def main() -> None:
    passed = failed = 0
    for title, func in CASES:
        try:
            func()
        except AssertionError as exc:
            failed += 1
            print(f"  x {title}: {exc}")
        else:
            passed += 1
            print(f"  v {title}")
    print(f"\n对齐测试：{passed}/{len(CASES)} 通过" + (f"，{failed} 个失败" if failed else ""))
    assert failed == 0, f"{failed} 个用例失败"


if __name__ == "__main__":
    main()
