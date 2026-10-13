"""人工审核工作台与审核闭环测试（tasks.md 8.4、8.5；产品书 6.6.9–6.6.10）。

覆盖两条任务的验收条件与边界：
- 8.4 自动入队：**低置信 / 涉分数线 / 涉规则触发的问答出现在待审列表**、无需审核的不入队、
  幂等不重复建单；
- 8.5 审核操作与回流：**三类操作（通过 / 修正 / 驳回）的状态流转、留痕、修正内容沉淀、
  驳回可追踪**，已处理任务不可重复审核，修正缺答案被拦。

④ 号 RAG 尚未产出真实 qa_log，本测试直接用 ``QaLog`` 落库模拟其输出
（与 8.4 的接入点 ``services.review.auto_enqueue`` 一致）。

纯脚本，无 pytest 依赖，直接运行：
    cd backend && .venv\\Scripts\\python.exe test_review.py
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

# 环境变量必须在导入 app.* 之前设置：settings 在首次导入时读取一次
_WORK = Path(tempfile.mkdtemp(prefix="zhixuan_review_test_"))
os.environ["ZHIXUAN_DATABASE_URL"] = f"sqlite:///{(_WORK / 'review.db').as_posix()}"
os.environ["ZHIXUAN_SECRET_KEY"] = "test-secret-key-review-suite-at-least-32-bytes"
os.environ["ZHIXUAN_ENV"] = "test"
os.environ["ZHIXUAN_LOGIN_MAX_FAILURES"] = "100"
os.environ["ZHIXUAN_LOGIN_LOCK_SECONDS"] = "1"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.db.session import SessionLocal, create_all  # noqa: E402
from app.main import app  # noqa: E402
from app.models.knowledge import (  # noqa: E402
    KnowledgeChunk,
    KnowledgeDoc,
    QaLog,
    ReviewTask,
)
from app.services import admin_auth  # noqa: E402
from app.services import review as review_service  # noqa: E402

ADMIN_USERNAME = "root_admin"
ADMIN_PASSWORD = "admin-pass-123"
REVIEWER_USERNAME = "reviewer01"
REVIEWER_PASSWORD = "review-pass-123"
USER_PASSWORD = "user-pass-123"

CITATION = {
    "source_name": "河南省教育考试院",
    "source_url": "https://www.haeea.cn/notice",
    "year": 2026,
    "snippet": "普通类本科批实行平行志愿……",
}

create_all()
with SessionLocal() as _db:
    admin_auth.ensure_admin(_db, ADMIN_USERNAME, ADMIN_PASSWORD, role="admin")
    admin_auth.ensure_admin(_db, REVIEWER_USERNAME, REVIEWER_PASSWORD, role="reviewer")

client = TestClient(app)
logging.getLogger("zhixuan").setLevel(logging.CRITICAL)

PAGINATION_KEYS = {"items", "total", "page", "page_size"}
LIST_FIELDS = {
    "task_id",
    "qa_log_id",
    "question",
    "answer",
    "confidence",
    "trigger_reason",
    "status",
    "created_at",
}
PROTECTED_CALLS = [
    ("get", "/api/admin/review/tasks"),
    ("get", "/api/admin/review/tasks/1"),
    ("post", "/api/admin/review/tasks/1"),
    ("post", "/api/admin/review/enqueue"),
]

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


def login(username: str = ADMIN_USERNAME, password: str = ADMIN_PASSWORD) -> str:
    body = call("post", "/api/admin/login", json={"username": username, "password": password})
    assert body["code"] == 0, body
    return body["data"]["token"]


def admin_token() -> str:
    return login()


def user_token() -> str:
    body = call(
        "post", "/api/auth/register", json={"username": unique("stu"), "password": USER_PASSWORD}
    )
    assert body["code"] == 0, body
    return body["data"]["access_token"]


def make_qa_log(
    question: str,
    answer: str = "",
    confidence: str = "high",
    needs_review: bool = False,
    citations: list[dict] | None = None,
    degraded: bool = False,
) -> int:
    """落一条问答日志，模拟 ④ 号 RAG 的产出。"""
    with SessionLocal() as db:
        log = QaLog(
            question=question,
            answer=answer,
            confidence=confidence,
            needs_review=needs_review,
            citations=list(citations or []),
            degraded=degraded,
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return int(log.id)


def task_of(qa_log_id: int) -> ReviewTask | None:
    with SessionLocal() as db:
        return db.scalar(select(ReviewTask).where(ReviewTask.qa_log_id == qa_log_id))


def enqueue_via_service(qa_log_id: int) -> tuple[int | None, int | None]:
    """调用 8.4 的接入点（④ 用），返回两次调用得到的任务 id（验证幂等）。"""
    with SessionLocal() as db:
        log = db.get(QaLog, qa_log_id)
        first = review_service.auto_enqueue(db, log)
        db.commit()
        first_id = int(first.id) if first else None
    with SessionLocal() as db:
        log = db.get(QaLog, qa_log_id)
        second = review_service.auto_enqueue(db, log)
        db.commit()
        second_id = int(second.id) if second else None
    return first_id, second_id


def decision_count(action: str) -> int:
    token = admin_token()
    return int(data("get", "/api/admin/audit-logs", token, params={"action": action})["total"])


# --------------------------------------------------------------------------- #
# 8.1 鉴权（审核接口同样受管理端保护）
# --------------------------------------------------------------------------- #
@case("01 未登录访问审核接口一律 1002")
def _() -> None:
    for method, path in PROTECTED_CALLS:
        assert code_of(method, path) == 1002, (method, path)


@case("02 持 C 端用户令牌访问审核接口一律 1003")
def _() -> None:
    token = user_token()
    for method, path in PROTECTED_CALLS:
        assert code_of(method, path, token) == 1003, (method, path)


# --------------------------------------------------------------------------- #
# 8.4 触发条件判定
# --------------------------------------------------------------------------- #
@case("03 低置信 / 涉分数线 / 涉规则各自命中，普通问答不命中")
def _() -> None:
    assert review_service.evaluate_trigger("low", "随便问问", "答案") == "低置信"
    assert "涉分数线" in review_service.evaluate_trigger("high", "620分能上哪些学校", "见投档线")
    assert "涉规则" in review_service.evaluate_trigger("high", "国家专项怎么报", "需户籍与学籍")
    assert review_service.evaluate_trigger("high", "你好", "你好呀") is None


@case("04 多类同时命中，原因以顿号连接")
def _() -> None:
    reason = review_service.evaluate_trigger("low", "专项计划的分数线是多少", "见省控线")
    for keyword in ("低置信", "涉分数线", "涉规则"):
        assert keyword in reason, (keyword, reason)


@case("05 自动入队幂等：同一问答只建一个任务，并置 needs_review / pending_review")
def _() -> None:
    qa_log_id = make_qa_log("某省控线是多少", confidence="low")
    first_id, second_id = enqueue_via_service(qa_log_id)
    assert first_id is not None and first_id == second_id, (first_id, second_id)

    with SessionLocal() as db:
        log = db.get(QaLog, qa_log_id)
        assert log.needs_review is True
        assert log.status == "pending_review", log.status
        count = int(
            db.scalar(
                select(func.count()).select_from(ReviewTask).where(ReviewTask.qa_log_id == qa_log_id)
            )
            or 0
        )
    assert count == 1, count


@case("06 无需审核的高置信普通问答不入队")
def _() -> None:
    qa_log_id = make_qa_log("你好，介绍一下你自己", confidence="high")
    assert enqueue_via_service(qa_log_id) == (None, None)
    assert task_of(qa_log_id) is None


@case("07 刷新待审队列：扫描补建任务，再刷不重复（8.4 验收）")
def _() -> None:
    token = admin_token()
    qa_log_id = make_qa_log("专项计划的分数线如何参考", answer="见省控线", confidence="low", needs_review=True)

    first = data("post", "/api/admin/review/enqueue", token)
    assert first["enqueued"] >= 1, first
    second = data("post", "/api/admin/review/enqueue", token)
    assert second["enqueued"] == 0, second

    page = data("get", "/api/admin/review/tasks", token)
    ids = [row["task_id"] for row in page["items"]]
    task = task_of(qa_log_id)
    assert task is not None and task.id in ids, (task, ids)


# --------------------------------------------------------------------------- #
# 8.4 待审列表
# --------------------------------------------------------------------------- #
@case("08 待审列表返回分页包，字段齐全且默认只列 pending")
def _() -> None:
    token = admin_token()
    qa_log_id = make_qa_log("国家专项报名的学籍要求", confidence="low")
    enqueue_via_service(qa_log_id)

    page = data("get", "/api/admin/review/tasks", token)
    assert set(page) == PAGINATION_KEYS, sorted(page)
    assert page["total"] >= 1
    assert all(row["status"] == "pending" for row in page["items"])

    task = task_of(qa_log_id)
    row = next(item for item in page["items"] if item["task_id"] == task.id)
    for field in LIST_FIELDS:
        assert field in row, field
    assert row["qa_log_id"] == qa_log_id
    assert row["confidence"] == "low"
    assert "低置信" in row["trigger_reason"]


@case("09 待审列表可按入队原因过滤，非法分页参数 1001")
def _() -> None:
    token = admin_token()
    page = data("get", "/api/admin/review/tasks", token, params={"trigger_reason": "涉分数线"})
    assert all("涉分数线" in row["trigger_reason"] for row in page["items"]), page["items"]
    assert code_of("get", "/api/admin/review/tasks", token, params={"page": 0}) == 1001
    assert code_of("get", "/api/admin/review/tasks", token, params={"page_size": 200}) == 1001


# --------------------------------------------------------------------------- #
# 8.4 审核详情
# --------------------------------------------------------------------------- #
@case("10 审核详情含引用原文片段与原始答案，供对照")
def _() -> None:
    token = admin_token()
    qa_log_id = make_qa_log("河南国家专项分数线", answer="约为 560 分", confidence="low", citations=[CITATION])
    task = task_of(qa_log_id) or None
    enqueue_via_service(qa_log_id)
    task = task_of(qa_log_id)

    detail = data("get", f"/api/admin/review/tasks/{task.id}", token)
    assert detail["task_id"] == task.id
    assert detail["qa_log_id"] == qa_log_id
    assert detail["original_answer"] == "约为 560 分"
    assert detail["citations"] == [CITATION], detail["citations"]
    assert detail["status"] == "pending"


@case("11 详情任务不存在 1001")
def _() -> None:
    assert code_of("get", "/api/admin/review/tasks/999999", admin_token()) == 1001


# --------------------------------------------------------------------------- #
# 8.5 审核操作：通过
# --------------------------------------------------------------------------- #
@case("12 通过：返回 null，任务与问答均转 approved，且留痕（8.5）")
def _() -> None:
    token = admin_token()
    qa_log_id = make_qa_log("某校招生计划人数", confidence="low")
    enqueue_via_service(qa_log_id)
    task = task_of(qa_log_id)

    before = decision_count("review.approve")
    assert data("post", f"/api/admin/review/tasks/{task.id}", token, json={"action": "approve"}) is None
    assert decision_count("review.approve") == before + 1

    refreshed = task_of(qa_log_id)
    assert refreshed.status == "approved", refreshed.status
    assert refreshed.reviewer == ADMIN_USERNAME
    assert refreshed.reviewed_at is not None
    with SessionLocal() as db:
        assert db.get(QaLog, qa_log_id).status == "approved"

    logs = data("get", "/api/admin/audit-logs", token, params={"action": "review.approve"})["items"]
    row = logs[0]
    assert row["target_type"] == "review_task"
    assert row["target_id"] == str(task.id)
    assert row["detail"]["qa_log_id"] == qa_log_id
    assert row["detail"]["decision"] == "approve"


@case("13 已处理任务不可重复审核（1001）")
def _() -> None:
    token = admin_token()
    qa_log_id = make_qa_log("重复审核测试", confidence="low")
    enqueue_via_service(qa_log_id)
    task = task_of(qa_log_id)

    assert code_of("post", f"/api/admin/review/tasks/{task.id}", token, json={"action": "approve"}) == 0
    assert code_of("post", f"/api/admin/review/tasks/{task.id}", token, json={"action": "reject"}) == 1001
    assert task_of(qa_log_id).status == "approved"


@case("14 动作非法 / 任务不存在 / 修正缺答案 → 1001")
def _() -> None:
    token = admin_token()
    qa_log_id = make_qa_log("非法动作测试", confidence="low")
    enqueue_via_service(qa_log_id)
    task = task_of(qa_log_id)

    assert code_of("post", f"/api/admin/review/tasks/{task.id}", token, json={"action": "delete"}) == 1001
    assert code_of("post", "/api/admin/review/tasks/999999", token, json={"action": "approve"}) == 1001
    assert code_of("post", f"/api/admin/review/tasks/{task.id}", token, json={"action": "correct"}) == 1001
    assert task_of(qa_log_id).status == "pending", "非法请求不得改变任务状态"


# --------------------------------------------------------------------------- #
# 8.5 审核操作：修正与回流（沉淀）
# --------------------------------------------------------------------------- #
@case("15 修正：状态 corrected，保存修正答案，且沉淀为知识文档 + 切片（8.5 回流）")
def _() -> None:
    token = admin_token()
    question = unique("修正沉淀") + "的分数线"
    qa_log_id = make_qa_log(question, answer="原答案（有误）", confidence="low", citations=[CITATION])
    enqueue_via_service(qa_log_id)
    task = task_of(qa_log_id)

    with SessionLocal() as db:
        docs_before = int(db.scalar(select(func.count()).select_from(KnowledgeDoc)) or 0)

    corrected = "修正后的权威口径：以省教育考试院当年公告为准。"
    before = decision_count("review.correct")
    assert data(
        "post",
        f"/api/admin/review/tasks/{task.id}",
        token,
        json={"action": "correct", "corrected_answer": corrected, "comment": "口径有误"},
    ) is None
    assert decision_count("review.correct") == before + 1

    refreshed = task_of(qa_log_id)
    assert refreshed.status == "corrected", refreshed.status
    assert refreshed.corrected_answer == corrected
    assert refreshed.comment == "口径有误"
    with SessionLocal() as db:
        assert db.get(QaLog, qa_log_id).status == "approved"
        docs_after = int(db.scalar(select(func.count()).select_from(KnowledgeDoc)) or 0)
        doc = db.scalar(select(KnowledgeDoc).where(KnowledgeDoc.title == f"审核修正：{question[:80]}"))
        assert doc is not None, "修正内容未沉淀为知识文档"
        assert doc.source_name == CITATION["source_name"] and doc.year == CITATION["year"]
        chunks = int(
            db.scalar(
                select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.doc_id == doc.id)
            )
            or 0
        )
        assert chunks == 1, chunks
    assert docs_after == docs_before + 1

    logs = data("get", "/api/admin/audit-logs", token, params={"action": "review.correct"})["items"]
    assert logs[0]["detail"]["sedimented"] is True
    assert logs[0]["detail"]["sediment_doc_id"]


@case("16 修正但引用缺来源三要素：不沉淀（缺来源不臆测），仍完成修正")
def _() -> None:
    token = admin_token()
    qa_log_id = make_qa_log("无来源引用的问答", confidence="low", citations=[{"snippet": "无来源片段"}])
    enqueue_via_service(qa_log_id)
    task = task_of(qa_log_id)

    with SessionLocal() as db:
        docs_before = int(db.scalar(select(func.count()).select_from(KnowledgeDoc)) or 0)

    assert data(
        "post",
        f"/api/admin/review/tasks/{task.id}",
        token,
        json={"action": "correct", "corrected_answer": "修正内容"},
    ) is None
    assert task_of(qa_log_id).status == "corrected"
    with SessionLocal() as db:
        docs_after = int(db.scalar(select(func.count()).select_from(KnowledgeDoc)) or 0)
    assert docs_after == docs_before, "缺来源时不得沉淀"

    logs = data("get", "/api/admin/audit-logs", token, params={"action": "review.correct"})["items"]
    assert logs[0]["detail"]["sedimented"] is False


# --------------------------------------------------------------------------- #
# 8.5 审核操作：驳回（可追踪）
# --------------------------------------------------------------------------- #
@case("17 驳回：状态 rejected，问答转 rejected，留痕且可追踪（8.5）")
def _() -> None:
    token = admin_token()
    qa_log_id = make_qa_log("驳回可追踪测试", confidence="low", citations=[CITATION])
    enqueue_via_service(qa_log_id)
    task = task_of(qa_log_id)

    before = decision_count("review.reject")
    assert data(
        "post",
        f"/api/admin/review/tasks/{task.id}",
        token,
        json={"action": "reject", "comment": "无依据，驳回"},
    ) is None
    assert decision_count("review.reject") == before + 1

    refreshed = task_of(qa_log_id)
    assert refreshed.status == "rejected"
    assert refreshed.reviewer == ADMIN_USERNAME
    assert refreshed.comment == "无依据，驳回"
    assert refreshed.reviewed_at is not None
    with SessionLocal() as db:
        assert db.get(QaLog, qa_log_id).status == "rejected"

    page = data("get", "/api/admin/review/tasks", token, params={"status": "rejected"})
    ids = [row["task_id"] for row in page["items"]]
    assert task.id in ids, "驳回记录应可在已处理列表中追踪"
    row = next(item for item in page["items"] if item["task_id"] == task.id)
    assert row["status"] == "rejected" and row["reviewer"] == ADMIN_USERNAME


@case("18 处理后的任务不再出现在默认待审列表")
def _() -> None:
    token = admin_token()
    qa_log_id = make_qa_log("转出待审测试", confidence="low")
    enqueue_via_service(qa_log_id)
    task = task_of(qa_log_id)
    assert task.id in [row["task_id"] for row in data("get", "/api/admin/review/tasks", token)["items"]]

    data("post", f"/api/admin/review/tasks/{task.id}", token, json={"action": "approve"})
    assert task.id not in [row["task_id"] for row in data("get", "/api/admin/review/tasks", token)["items"]]


@case("19 reviewer 角色账号同样可执行审核（角色细分见 PR 说明）")
def _() -> None:
    token = login(REVIEWER_USERNAME, REVIEWER_PASSWORD)
    qa_log_id = make_qa_log("reviewer 审核测试", confidence="low")
    enqueue_via_service(qa_log_id)
    task = task_of(qa_log_id)

    assert data("post", f"/api/admin/review/tasks/{task.id}", token, json={"action": "approve"}) is None
    assert task_of(qa_log_id).reviewer == REVIEWER_USERNAME


@case("20 统计的待审数与库内一致（8.7 联动）")
def _() -> None:
    token = admin_token()
    make_qa_log("统计联动测试", confidence="low")
    data("post", "/api/admin/review/enqueue", token)
    stats = data("get", "/api/admin/stats", token)
    with SessionLocal() as db:
        expected = int(
            db.scalar(
                select(func.count()).select_from(ReviewTask).where(ReviewTask.status == "pending")
            )
            or 0
        )
    assert stats["review_pending_count"] == expected, (stats["review_pending_count"], expected)


# --------------------------------------------------------------------------- #
# 补充：越界年份同样不得写入（避免撞 CHECK 约束把接口变成 500）
# --------------------------------------------------------------------------- #
@case("21 修正但引用年份越界：不沉淀且不报 500，仍完成修正")
def _() -> None:
    token = admin_token()
    qa_log_id = make_qa_log(
        "年份越界的引用问答",
        confidence="low",
        citations=[dict(CITATION, year=1999)],
    )
    enqueue_via_service(qa_log_id)
    task = task_of(qa_log_id)

    with SessionLocal() as db:
        docs_before = int(db.scalar(select(func.count()).select_from(KnowledgeDoc)) or 0)

    assert data(
        "post",
        f"/api/admin/review/tasks/{task.id}",
        token,
        json={"action": "correct", "corrected_answer": "修正内容"},
    ) is None
    assert task_of(qa_log_id).status == "corrected"

    with SessionLocal() as db:
        docs_after = int(db.scalar(select(func.count()).select_from(KnowledgeDoc)) or 0)
    assert docs_after == docs_before, "年份越界时不得沉淀（否则撞 source/knowledge_doc 的 CHECK 约束）"

    logs = data("get", "/api/admin/audit-logs", token, params={"action": "review.correct"})["items"]
    assert logs[0]["detail"]["sedimented"] is False


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
    print(f"\n审核闭环用例：{total - len(failures)}/{total} 通过")
    if failures:
        return 1
    print("review tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())