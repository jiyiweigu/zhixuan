"""志愿方案保存 / 命名 / 编辑测试（tasks.md 6.6，产品书 6.1.7）。

覆盖 6.6 的验收条件"已登录用户可保存并重新打开方案"，并补齐边界：
- 未登录 / 令牌失效一律 1002；
- 保存后重新打开的 items 与保存时逐字段一致（含中文与嵌套字段，不被裁剪）；
- 列表只回摘要、按最近更新在前，多套方案互不干扰；
- 编辑（改名 + 换条目）后重新打开为新值，updated_at 前进；
- 删除后列表不含、重新打开返回 1001；
- 跨用户访问（读 / 改 / 删）一律 1003，且不影响方案归属方；
- 参数校验：名称为空或超长、items 非数组、tier 取值非法 → 1001。

纯脚本，无 pytest 依赖，直接运行：
    cd backend && .venv\\Scripts\\python.exe test_user_plans.py
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

# 环境变量必须在导入 app.* 之前设置：settings 在首次导入时读取一次
_WORK = Path(tempfile.mkdtemp(prefix="zhixuan_plan_test_"))
os.environ["ZHIXUAN_DATABASE_URL"] = f"sqlite:///{(_WORK / 'plan.db').as_posix()}"
os.environ["ZHIXUAN_SECRET_KEY"] = "test-secret-key-plan-suite-at-least-32-bytes-long"
os.environ["ZHIXUAN_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402

from app.db.session import create_all  # noqa: E402
from app.main import app  # noqa: E402

create_all()
client = TestClient(app)
logging.getLogger("zhixuan").setLevel(logging.CRITICAL)

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
def unique_name(prefix: str = "planner") -> str:
    _counter["n"] += 1
    return f"{prefix}{_counter['n']:04d}"


def register(username: str | None = None) -> tuple[str, str]:
    """注册并登录一个用户，返回 (username, token)。"""
    name = username or unique_name()
    resp = client.post("/api/auth/register", json={"username": name, "password": PASSWORD})
    assert resp.status_code == 200 and resp.json()["code"] == 0, resp.text
    return name, resp.json()["data"]["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def sample_items() -> list[dict]:
    """一批带中文、嵌套与来源三要素的条目，用于验证"原样保存"。"""
    return [
        {
            "tier": "冲",
            "order": 1,
            "school_id": "s001",
            "name": "郑州大学",
            "major": "计算机科学与技术",
            "min_score": 615,
            "admission_year": 2025,
            "reasons": ["2025 年最低录取分 615，与本人 600 分相差 -15 分，属『冲』档。"],
            "citations": [
                {"source_name": "河南省教育考试院", "source_url": "https://example.invalid/hn", "year": 2025}
            ],
            "extra": {"tags": ["双一流", "211"], "note": "含中文与嵌套结构"},
        },
        {
            "tier": "稳",
            "order": 2,
            "school_id": "s002",
            "name": "河南大学",
            "major": "软件工程",
            "min_score": 590,
            "admission_year": 2025,
        },
        {
            "tier": "保",
            "order": 3,
            "school_id": "s003",
            "name": "华北水利水电大学",
            "major": "电子信息工程",
            "min_score": 572,
            "admission_year": 2025,
        },
    ]


def save(token: str, name: str, items: list | None = None, strategy: str = "稳") -> str:
    resp = client.post(
        "/api/user/plans",
        headers=auth(token),
        json={"name": name, "strategy": strategy, "items": sample_items() if items is None else items},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0, body
    return body["data"]["plan_id"]


def open_plan(token: str, plan_id: str) -> dict:
    resp = client.get(f"/api/user/plans/{plan_id}", headers=auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def listing(token: str) -> dict:
    resp = client.get("/api/user/plans", headers=auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


# --------------------------------------------------------------------------- #
# 鉴权（1002）
# --------------------------------------------------------------------------- #
@case("01 未登录访问方案接口一律返回 1002")
def _() -> None:
    calls = [
        client.get("/api/user/plans"),
        client.post("/api/user/plans", json={"name": "x", "items": []}),
        client.get("/api/user/plans/plan_deadbeef"),
        client.put("/api/user/plans/plan_deadbeef", json={"name": "x", "items": []}),
        client.delete("/api/user/plans/plan_deadbeef"),
    ]
    for resp in calls:
        assert resp.status_code == 200, resp.text
        assert resp.json()["code"] == 1002, resp.json()


@case("02 令牌无效时按未登录处理（1002）")
def _() -> None:
    resp = client.get("/api/user/plans", headers=auth("not-a-real-token"))
    assert resp.json()["code"] == 1002, resp.json()


# --------------------------------------------------------------------------- #
# 保存与重新打开（6.6 验收条件）
# --------------------------------------------------------------------------- #
@case("03 保存返回 plan_id，且以 plan_ 开头")
def _() -> None:
    _, token = register()
    plan_id = save(token, "我的第一套方案")
    assert plan_id.startswith("plan_"), plan_id


@case("04 重新打开方案：名称、倾向、items 与保存时逐字段一致")
def _() -> None:
    _, token = register()
    items = sample_items()
    plan_id = save(token, "冲稳保方案A", items=items)
    detail = open_plan(token, plan_id)["data"]

    assert detail["plan_id"] == plan_id
    assert detail["name"] == "冲稳保方案A"
    assert detail["strategy"] == "稳"
    assert detail["items"] == items, "重新打开的 items 必须与保存时完全一致"
    assert detail["created_at"] and detail["updated_at"]


@case("05 items 原样保存：中文、嵌套对象与来源三要素不被裁剪")
def _() -> None:
    _, token = register()
    plan_id = save(token, "原样保存")
    first = open_plan(token, plan_id)["data"]["items"][0]
    assert first["name"] == "郑州大学"
    assert first["extra"]["tags"] == ["双一流", "211"]
    assert first["citations"][0]["source_name"] == "河南省教育考试院"
    assert first["reasons"][0].startswith("2025 年最低录取分")


@case("06 允许保存空条目的草稿方案")
def _() -> None:
    _, token = register()
    plan_id = save(token, "草稿", items=[])
    detail = open_plan(token, plan_id)["data"]
    assert detail["items"] == []


# --------------------------------------------------------------------------- #
# 列表
# --------------------------------------------------------------------------- #
@case("07 新用户的方案列表为空")
def _() -> None:
    _, token = register()
    assert listing(token)["items"] == []


@case("08 列表只回摘要（含 item_count），不下发 items")
def _() -> None:
    _, token = register()
    save(token, "摘要检查")
    item = listing(token)["items"][0]
    assert set(item) == {"plan_id", "name", "strategy", "item_count", "created_at", "updated_at"}
    assert item["item_count"] == 3
    assert "items" not in item


@case("09 一个用户的方案互相隔离，列表按最近更新在前")
def _() -> None:
    _, token = register()
    first = save(token, "方案一")
    time.sleep(0.01)
    second = save(token, "方案二")

    ids = [item["plan_id"] for item in listing(token)["items"]]
    assert ids == [second, first], ids

    time.sleep(0.01)
    client.put(
        f"/api/user/plans/{first}",
        headers=auth(token),
        json={"name": "方案一（改）", "strategy": "冲", "items": sample_items()},
    )
    ids = [item["plan_id"] for item in listing(token)["items"]]
    assert ids == [first, second], "更新后的方案应排到最前"


@case("10 不同用户的方案列表互不可见")
def _() -> None:
    _, token_a = register()
    _, token_b = register()
    save(token_a, "A 的方案")
    assert listing(token_b)["items"] == []


# --------------------------------------------------------------------------- #
# 编辑
# --------------------------------------------------------------------------- #
@case("11 编辑：改名并替换条目后，重新打开为新值且 updated_at 前进")
def _() -> None:
    _, token = register()
    plan_id = save(token, "旧名称")
    before = open_plan(token, plan_id)["data"]

    time.sleep(0.01)
    new_items = [{"tier": "保", "order": 1, "school_id": "s009", "name": "保底院校"}]
    resp = client.put(
        f"/api/user/plans/{plan_id}",
        headers=auth(token),
        json={"name": "新名称", "strategy": "保", "items": new_items},
    )
    assert resp.status_code == 200 and resp.json()["code"] == 0, resp.text
    assert resp.json()["data"] is None, "PUT 按产品书 6.1.7 返回 null"

    after = open_plan(token, plan_id)["data"]
    assert after["name"] == "新名称"
    assert after["strategy"] == "保"
    assert after["items"] == new_items
    assert after["updated_at"] >= before["updated_at"]
    assert after["plan_id"] == before["plan_id"], "编辑不改变 plan_id"


@case("12 改名后列表摘要同步更新")
def _() -> None:
    _, token = register()
    plan_id = save(token, "改名前")
    client.put(
        f"/api/user/plans/{plan_id}",
        headers=auth(token),
        json={"name": "改名后", "strategy": "稳", "items": []},
    )
    names = {item["plan_id"]: item["name"] for item in listing(token)["items"]}
    assert names[plan_id] == "改名后"


# --------------------------------------------------------------------------- #
# 删除
# --------------------------------------------------------------------------- #
@case("13 删除后：列表不含该方案，重新打开返回 1001")
def _() -> None:
    _, token = register()
    plan_id = save(token, "待删除")
    resp = client.delete(f"/api/user/plans/{plan_id}", headers=auth(token))
    assert resp.status_code == 200 and resp.json()["code"] == 0, resp.text
    assert resp.json()["data"] is None

    assert all(item["plan_id"] != plan_id for item in listing(token)["items"])
    assert open_plan(token, plan_id)["code"] == 1001


@case("14 打开不存在的方案返回 1001")
def _() -> None:
    _, token = register()
    assert open_plan(token, "plan_000000000000")["code"] == 1001


# --------------------------------------------------------------------------- #
# 越权（1003）
# --------------------------------------------------------------------------- #
@case("15 读 / 改 / 删他人方案一律 1003，且不影响归属方")
def _() -> None:
    _, token_a = register()
    _, token_b = register()
    plan_id = save(token_a, "A 的私密方案")

    assert open_plan(token_b, plan_id)["code"] == 1003
    put = client.put(
        f"/api/user/plans/{plan_id}",
        headers=auth(token_b),
        json={"name": "被篡改", "strategy": "稳", "items": []},
    )
    assert put.json()["code"] == 1003, put.json()
    delete = client.delete(f"/api/user/plans/{plan_id}", headers=auth(token_b))
    assert delete.json()["code"] == 1003, delete.json()

    # 归属方的方案未被改动，也未被删除
    detail = open_plan(token_a, plan_id)["data"]
    assert detail["name"] == "A 的私密方案"
    assert len(detail["items"]) == 3


@case("16 B 无法通过推断 plan_id 访问 A 的方案（ID 不可枚举）")
def _() -> None:
    _, token_a = register()
    _, token_b = register()
    ids = {save(token_a, f"方案{i}") for i in range(3)}
    # A 的三个 plan_id 互不相同，且 B 全部拿不到（1003）
    assert len(ids) == 3
    for plan_id in ids:
        assert open_plan(token_b, plan_id)["code"] == 1003


# --------------------------------------------------------------------------- #
# 参数校验（1001）
# --------------------------------------------------------------------------- #
@case("17 方案名称为空 / 纯空白返回 1001")
def _() -> None:
    _, token = register()
    for name in ("", "   "):
        resp = client.post(
            "/api/user/plans", headers=auth(token), json={"name": name, "items": []}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["code"] == 1001, (name, resp.json())


@case("18 方案名称超过 100 字返回 1001")
def _() -> None:
    _, token = register()
    resp = client.post(
        "/api/user/plans", headers=auth(token), json={"name": "长" * 101, "items": []}
    )
    assert resp.json()["code"] == 1001, resp.json()


@case("19 items 不是数组返回 1001")
def _() -> None:
    _, token = register()
    for bad in ("不是数组", {"tier": "冲"}, 123):
        resp = client.post(
            "/api/user/plans", headers=auth(token), json={"name": "x", "items": bad}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["code"] == 1001, (bad, resp.json())


@case("20 条目 tier 取值非法返回 1001")
def _() -> None:
    _, token = register()
    resp = client.post(
        "/api/user/plans",
        headers=auth(token),
        json={"name": "x", "items": [{"tier": "超冲", "order": 1}]},
    )
    assert resp.json()["code"] == 1001, resp.json()


@case("21 条目数超过上限返回 1001")
def _() -> None:
    _, token = register()
    resp = client.post(
        "/api/user/plans",
        headers=auth(token),
        json={"name": "x", "items": [{"tier": "稳"}] * 201},
    )
    assert resp.json()["code"] == 1001, resp.json()


@case("22 倾向值非法（非 冲/稳/保/balanced）返回 1001")
def _() -> None:
    _, token = register()
    resp = client.post(
        "/api/user/plans", headers=auth(token), json={"name": "x", "strategy": "随便", "items": []}
    )
    assert resp.json()["code"] == 1001, resp.json()


# --------------------------------------------------------------------------- #
# 与方案生成接口联动（6.3 → 6.6）
# --------------------------------------------------------------------------- #
@case("23 生成接口的产物可直接保存，重新打开与生成结果一致")
def _() -> None:
    _, token = register()
    resp = client.post(
        "/api/plans",
        headers=auth(token),
        json={
            "profile": {"province": "河南", "score": 600, "subject_type": "物理类"},
            "strategy": "稳",
        },
    )
    assert resp.status_code == 200 and resp.json()["code"] == 0, resp.text
    generated = resp.json()["data"]
    assert generated["items"], "演示数据下应能生成非空方案"

    plan_id = save(token, "生成后保存", items=generated["items"], strategy=generated["strategy"])
    detail = open_plan(token, plan_id)["data"]
    assert detail["items"] == generated["items"], "保存后再打开应与生成结果逐字段一致"
    assert detail["strategy"] == generated["strategy"]


def main() -> int:
    failures: list[tuple[str, str]] = []
    for title, fn in CASES:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - 测试汇总需要捕获全部异常
            failures.append((title, f"{type(exc).__name__}: {exc}"))

    for title, message in failures:
        print(f"FAIL  {title}\n      {message}")

    total = len(CASES)
    print(f"\n方案保存用例：{total - len(failures)}/{total} 通过")
    if failures:
        return 1
    print("saved plan tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
