"""索引管理测试（tasks.md 8.3；产品书 6.6.4–6.6.5）。

8.3 的验收条件原文是「**重建期间问答仍可响应**」——本测试用「可控阻塞的 embedder」把重建任务
稳定停在 running 态，在此期间打问答接口与统计接口，验证请求链路未被重建阻塞（用例 06）。

同时固化②号的边界与增量语义：
- 未接入 ④ 的向量化时**不假装成功**：任务 partial、``pending_embedding`` 如实计数、message 明写；
- ``incremental=True`` 只处理 ``embedding IS NULL`` 的切片；``scope=doc_ids`` 只处理指定文档；
- 并发重建被拒（1001）、发起重建留痕（``index.rebuild``）。

无需 pytest，直接运行：
    cd backend && .venv\\Scripts\\python.exe test_index.py
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

_WORK = Path(tempfile.mkdtemp(prefix="zhixuan_index_test_"))
os.environ["ZHIXUAN_DATABASE_URL"] = f"sqlite:///{(_WORK / 'index.db').as_posix()}"
os.environ["ZHIXUAN_SECRET_KEY"] = "test-secret-key-index-suite-at-least-32-bytes"
os.environ["ZHIXUAN_ENV"] = "test"
os.environ["ZHIXUAN_LOGIN_MAX_FAILURES"] = "100"
os.environ["ZHIXUAN_LOGIN_LOCK_SECONDS"] = "1"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal, create_all  # noqa: E402
from app.main import app  # noqa: E402
from app.models.knowledge import IndexTask, KnowledgeChunk, KnowledgeDoc  # noqa: E402
from app.models.source import Source  # noqa: E402
from app.services import admin_auth  # noqa: E402
from app.services import indexing as indexing_service  # noqa: E402

# These legacy cases specifically verify the explicit no-embedder partial path.
indexing_service.register_embedder(None)

ADMIN_USERNAME = "root_admin"
ADMIN_PASSWORD = "admin-pass-123"
USER_PASSWORD = "user-pass-123"

SOURCE_URL = "https://www.haeea.cn/index-notice"
SOURCE_NAME = "河南省教育考试院"

create_all()
with SessionLocal() as _db:
    admin_auth.ensure_admin(_db, ADMIN_USERNAME, ADMIN_PASSWORD, role="admin")

client = TestClient(app)
logging.getLogger("zhixuan").setLevel(logging.CRITICAL)

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
def unique(prefix: str) -> str:
    _counter["n"] += 1
    return f"{prefix}{_counter['n']:04d}"


def auth(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def call(method: str, path: str, token: str | None = None, **kwargs) -> dict:
    resp = client.request(method, path, headers=auth(token), **kwargs)
    assert resp.status_code == 200, (method, path, resp.status_code, resp.text)
    return resp.json()


def data(method: str, path: str, token: str | None = None, **kwargs) -> dict:
    body = call(method, path, token, **kwargs)
    assert body["code"] == 0, (method, path, body)
    return body["data"]


def code_of(method: str, path: str, token: str | None = None, **kwargs) -> int:
    return call(method, path, token, **kwargs)["code"]


def login() -> str:
    body = call("post", "/api/admin/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert body["code"] == 0, body
    return body["data"]["token"]


def user_token() -> str:
    body = call(
        "post", "/api/auth/register", json={"username": unique("stu"), "password": USER_PASSWORD}
    )
    assert body["code"] == 0, body
    return body["data"]["access_token"]


def _ensure_source_id() -> int:
    with SessionLocal() as db:
        source = db.scalar(select(Source).where(Source.source_url == SOURCE_URL))
        if source is None:
            source = Source(source_name=SOURCE_NAME, source_url=SOURCE_URL, year=2026, source_type="official")
            db.add(source)
            db.commit()
            db.refresh(source)
        return int(source.id)


def make_doc(chunk_count: int, embedded_indexes: tuple[int, ...] = ()) -> tuple[int, list[int]]:
    """建一篇文档与若干切片；``embedded_indexes`` 中的切片预置向量（模拟已索引）。"""
    source_id = _ensure_source_id()
    with SessionLocal() as db:
        doc = KnowledgeDoc(
            title=unique("索引测试文档"),
            source_name=SOURCE_NAME,
            source_url=SOURCE_URL,
            year=2026,
            doc_type="公告",
            content="索引测试正文",
        )
        db.add(doc)
        db.flush()
        chunk_ids: list[int] = []
        for index in range(chunk_count):
            chunk = KnowledgeChunk(
                doc_id=doc.id,
                content=f"切片正文 {index}：普通类本科批实行平行志愿。",
                chunk_index=index,
                embedding=[0.6, 0.8] if index in embedded_indexes else None,
                province="河南",
                source_id=source_id,
            )
            db.add(chunk)
            db.flush()
            chunk_ids.append(int(chunk.id))
        db.commit()
        return int(doc.id), chunk_ids


def chunk_embedding(chunk_id: int) -> list[float] | None:
    with SessionLocal() as db:
        chunk = db.get(KnowledgeChunk, chunk_id)
        return None if chunk is None or chunk.embedding is None else list(chunk.embedding)


def wait_status(task_id: int, statuses: tuple[str, ...], timeout: float = 15.0) -> dict:
    """轮询任务态直到落入期望状态集合（超时抛错，便于定位）。"""
    deadline = time.monotonic() + timeout
    last: dict = {}
    while time.monotonic() < deadline:
        last = data("get", f"/api/admin/index/tasks/{task_id}", login())
        if last["status"] in statuses:
            return last
        time.sleep(0.02)
    raise AssertionError(f"任务 {task_id} 未在 {timeout}s 内进入 {statuses}，当前：{last}")


def rebuild(**payload) -> dict:
    return data("post", "/api/admin/index/rebuild", login(), json=payload)


# --------------------------------------------------------------------------- #
# 鉴权
# --------------------------------------------------------------------------- #
@case("01 未登录访问索引接口一律 1002")
def _() -> None:
    assert code_of("post", "/api/admin/index/rebuild", json={"scope": "all"}) == 1002
    assert code_of("get", "/api/admin/index/tasks/1") == 1002


@case("02 持 C 端用户令牌访问索引接口一律 1003")
def _() -> None:
    token = user_token()
    assert code_of("post", "/api/admin/index/rebuild", token, json={"scope": "all"}) == 1003
    assert code_of("get", "/api/admin/index/tasks/1", token) == 1003


# --------------------------------------------------------------------------- #
# 参数校验与任务态
# --------------------------------------------------------------------------- #
@case("03 参数非法 / 文档不存在 → 1001")
def _() -> None:
    token = login()
    assert code_of("post", "/api/admin/index/rebuild", token, json={"scope": "whatever"}) == 1001
    assert code_of("post", "/api/admin/index/rebuild", token, json={"scope": "doc_ids"}) == 1001
    assert code_of(
        "post", "/api/admin/index/rebuild", token, json={"scope": "doc_ids", "doc_ids": [999999]}
    ) == 1001


@case("04 任务不存在 → 1001")
def _() -> None:
    assert code_of("get", "/api/admin/index/tasks/999999", login()) == 1001


@case("05 incremental=True 只圈定未向量化切片，返回 {task_id, status}")
def _() -> None:
    doc_id, chunk_ids = make_doc(3, embedded_indexes=(0,))
    without_embedder = rebuild(scope="doc_ids", doc_ids=[doc_id], incremental=True)
    assert set(without_embedder) == {"task_id", "status"}, without_embedder

    state = wait_status(without_embedder["task_id"], ("partial", "done", "failed"))
    # 3 条切片中 1 条已向量化 → 增量目标 2 条
    assert state["progress"]["total"] == 2, state


@case("06 未接入向量化时不假装成功：partial + pending 如实 + message 明写")
def _() -> None:
    doc_id, _ = make_doc(2)
    assert indexing_service.embedder_ready() is False

    task_id = rebuild(scope="doc_ids", doc_ids=[doc_id], incremental=True)["task_id"]
    state = wait_status(task_id, ("partial", "done", "failed"))

    assert state["status"] == "partial", state
    progress = state["progress"]
    assert progress["total"] == 2 and progress["processed"] == 2
    assert progress["embedded"] == 0
    assert progress["pending_embedding"] == 2
    assert "向量化未接入" in state["message"], state["message"]
    assert state["embedder_ready"] is False


@case("07 无待处理切片时 total=0、percent=100、done")
def _() -> None:
    doc_id, _ = make_doc(0)
    task_id = rebuild(scope="doc_ids", doc_ids=[doc_id], incremental=True)["task_id"]
    state = wait_status(task_id, ("done", "partial", "failed"))

    assert state["status"] == "done", state
    assert state["progress"]["total"] == 0
    assert state["progress"]["percent"] == 100.0


# --------------------------------------------------------------------------- #
# 8.3 验收条件：重建期间问答仍可响应
# --------------------------------------------------------------------------- #
@case("08 重建进行中，问答与统计接口照常响应（8.3 验收）")
def _() -> None:
    doc_id, _ = make_doc(4)

    gate = threading.Event()

    def blocking_embedder(text: str) -> list[float]:
        assert gate.wait(timeout=15), "embedder 等待放行超时"
        return [1.0, 0.0]

    indexing_service.register_embedder(blocking_embedder)
    try:
        task_id = rebuild(scope="doc_ids", doc_ids=[doc_id], incremental=True)["task_id"]
        running = wait_status(task_id, ("running",))
        assert running["status"] == "running"

        # 重建卡在 running 期间，用户侧问答与统计读接口均应正常
        for _ in range(3):
            assert data("get", "/api/qa", params={"q": "平行志愿是什么"}) is not None
        assert data("get", "/api/admin/stats", login())["doc_count"] >= 1

        gate.set()
        finished = wait_status(task_id, ("done", "partial", "failed"))
    finally:
        gate.set()
        indexing_service.register_embedder(None)

    assert finished["status"] == "done", finished
    assert finished["progress"]["embedded"] == 4


@case("09 接入 embedder 后向量落库并做 L2 归一化，任务 done")
def _() -> None:
    doc_id, chunk_ids = make_doc(2)

    def embedder(text: str) -> list[float]:
        return [3.0, 4.0]  # 未归一化，期望落库为 [0.6, 0.8]

    indexing_service.register_embedder(embedder)
    try:
        task_id = rebuild(scope="doc_ids", doc_ids=[doc_id], incremental=True)["task_id"]
        state = wait_status(task_id, ("done", "partial", "failed"))
    finally:
        indexing_service.register_embedder(None)

    assert state["status"] == "done", state
    assert state["progress"]["embedded"] == 2
    assert state["progress"]["pending_embedding"] == 0
    assert state["progress"]["percent"] == 100.0
    for chunk_id in chunk_ids:
        vector = chunk_embedding(chunk_id)
        assert vector is not None, chunk_id
        assert abs(vector[0] - 0.6) < 1e-9 and abs(vector[1] - 0.8) < 1e-9, vector


@case("09b 批量 embedder 单条失败被隔离，其余切片继续完成")
def _() -> None:
    doc_id, chunk_ids = make_doc(3)

    class PartiallyFailingEmbedder:
        dim = 2
        def embed(self, texts: list[str]) -> list[list[float]]:
            if len(texts) > 1:
                return [[1.0, 0.0]]  # 故意返回错误数量，触发逐条定位
            if "切片正文 1：" in texts[0]:
                raise ValueError("fixture embedding failure")
            return [[3.0, 4.0]]

    indexing_service.register_embedder(PartiallyFailingEmbedder())
    try:
        task_id = rebuild(scope="doc_ids", doc_ids=[doc_id], incremental=True)["task_id"]
        state = wait_status(task_id, ("done", "partial", "failed"))
    finally:
        indexing_service.register_embedder(None)

    assert state["status"] == "partial", state
    assert state["progress"]["embedded"] == 2, state
    assert state["progress"]["failed"] == 1, state
    assert "fixture embedding failure" in state["message"], state
    assert chunk_embedding(chunk_ids[0]) == [0.6, 0.8]
    assert chunk_embedding(chunk_ids[2]) == [0.6, 0.8]


@case("10 incremental=False 全量重算：已向量化切片也在范围内")
def _() -> None:
    doc_id, _ = make_doc(2, embedded_indexes=(0, 1))
    state = wait_status(
        rebuild(scope="doc_ids", doc_ids=[doc_id], incremental=False)["task_id"],
        ("partial", "done", "failed"),
    )
    assert state["progress"]["total"] == 2, state


@case("11 scope=doc_ids 只处理指定文档的切片")
def _() -> None:
    doc_a, _ = make_doc(2)
    make_doc(3)  # 干扰文档
    state = wait_status(
        rebuild(scope="doc_ids", doc_ids=[doc_a], incremental=True)["task_id"],
        ("partial", "done", "failed"),
    )
    assert state["progress"]["total"] == 2, state
    assert state["scope"] == "doc_ids" and state["doc_ids"] == [doc_a]


@case("12 并发重建被拒（1001）")
def _() -> None:
    doc_id, _ = make_doc(2)
    gate = threading.Event()

    def blocking_embedder(text: str) -> list[float]:
        gate.wait(timeout=15)
        return [1.0, 1.0]

    indexing_service.register_embedder(blocking_embedder)
    try:
        task_id = rebuild(scope="doc_ids", doc_ids=[doc_id], incremental=True)["task_id"]
        wait_status(task_id, ("running",))
        assert code_of(
            "post",
            "/api/admin/index/rebuild",
            login(),
            json={"scope": "doc_ids", "doc_ids": [doc_id], "incremental": True},
        ) == 1001
        gate.set()
        wait_status(task_id, ("done", "partial", "failed"))
    finally:
        gate.set()
        indexing_service.register_embedder(None)


@case("13 发起重建写留痕 index.rebuild")
def _() -> None:
    token = login()
    doc_id, _ = make_doc(1)
    task_id = rebuild(scope="doc_ids", doc_ids=[doc_id], incremental=True)["task_id"]
    wait_status(task_id, ("partial", "done", "failed"))

    logs = data("get", "/api/admin/audit-logs", token, params={"action": "index.rebuild"})["items"]
    row = next(item for item in logs if item["target_id"] == str(task_id))
    assert row["target_type"] == "index_task"
    assert row["detail"]["scope"] == "doc_ids"
    assert row["detail"]["embedder_ready"] is False
    assert row["admin_username"] == ADMIN_USERNAME


@case("14 任务态字段齐全（产品书 6.6.5 的 {status, progress} + 追加字段）")
def _() -> None:
    doc_id, _ = make_doc(1)
    task_id = rebuild(scope="doc_ids", doc_ids=[doc_id], incremental=True)["task_id"]
    state = wait_status(task_id, ("partial", "done", "failed"))

    assert {"status", "progress"} <= set(state), sorted(state)
    assert {
        "total",
        "processed",
        "embedded",
        "pending_embedding",
        "failed",
        "percent",
    } == set(state["progress"]), sorted(state["progress"])
    with SessionLocal() as db:
        assert db.get(IndexTask, task_id) is not None


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
    print(f"\n索引管理用例：{total - len(failures)}/{total} 通过")
    if failures:
        return 1
    print("index tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
