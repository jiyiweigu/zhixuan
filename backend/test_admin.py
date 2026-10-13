"""管理端测试（tasks.md 8.1、8.2、8.6、8.7；产品书 6.6）。

覆盖四条任务的验收条件与边界：
- 8.1 鉴权与留痕：未登录 1002、C 端令牌访问管理端 1003、登录成功/失败、
  **操作记录含操作人 / 时间 / 动作**；
- 8.2 语料管理：导入成功、**缺来源 → 4001 拒收**、按来源与年份归档检索、删除连带切片；
- 8.6 途径与规则维护：**未填来源无法保存规则（4001）且库内不新增**、途径字典读写、
  区域名单只读；
- 8.7 数据统计：**统计值与库内计数一致**、覆盖度逐途径给出。

纯脚本，无 pytest 依赖，直接运行：
    cd backend && .venv\\Scripts\\python.exe test_admin.py
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

# 环境变量必须在导入 app.* 之前设置：settings 在首次导入时读取一次
_WORK = Path(tempfile.mkdtemp(prefix="zhixuan_admin_test_"))
os.environ["ZHIXUAN_DATABASE_URL"] = f"sqlite:///{(_WORK / 'admin.db').as_posix()}"
os.environ["ZHIXUAN_SECRET_KEY"] = "test-secret-key-admin-suite-at-least-32-bytes"
os.environ["ZHIXUAN_ENV"] = "test"
# 放宽失败限流，避免用例之间互相锁定
os.environ["ZHIXUAN_LOGIN_MAX_FAILURES"] = "100"
os.environ["ZHIXUAN_LOGIN_LOCK_SECONDS"] = "1"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.core import dataset  # noqa: E402
from app.db.session import SessionLocal, create_all  # noqa: E402
from app.main import app  # noqa: E402
from app.models.knowledge import KnowledgeChunk, KnowledgeDoc, QaLog, ReviewTask  # noqa: E402
from app.models.pathway import Pathway  # noqa: E402
from app.services import admin_auth  # noqa: E402
from app.services.pathway_seed import seed_pathways  # noqa: E402

ADMIN_USERNAME = "root_admin"
ADMIN_PASSWORD = "admin-pass-123"
REVIEWER_USERNAME = "reviewer01"
REVIEWER_PASSWORD = "review-pass-123"
USER_PASSWORD = "user-pass-123"

create_all()
with SessionLocal() as _db:
    admin_auth.ensure_admin(_db, ADMIN_USERNAME, ADMIN_PASSWORD, role="admin")
    admin_auth.ensure_admin(_db, REVIEWER_USERNAME, REVIEWER_PASSWORD, role="reviewer")
    SEEDED = seed_pathways(_db)

client = TestClient(app)
logging.getLogger("zhixuan").setLevel(logging.CRITICAL)

PAGINATION_KEYS = {"items", "total", "page", "page_size"}
CATALOG = dataset.load_catalog()
TOTAL_PATHWAYS = len(CATALOG)
SAMPLE_PATHWAY = CATALOG[0]["id"]
P0_PATHWAYS = sum(1 for item in CATALOG if item["priority"] == "P0")

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
    username = unique("stu")
    body = call("post", "/api/auth/register", json={"username": username, "password": USER_PASSWORD})
    assert body["code"] == 0, body
    return body["data"]["access_token"]


def doc_payload(**overrides) -> dict:
    payload = {
        "title": unique("招生章程"),
        "source_name": "河南省教育考试院",
        "source_url": "https://www.haeea.cn/notice",
        "year": 2026,
        "doc_type": "章程",
        "province": "河南",
        "content": "本章程用于管理端语料导入测试。",
        "chunks": ["切片一", "切片二"],
    }
    payload.update(overrides)
    return payload


def rule_payload(pathway_id: str = SAMPLE_PATHWAY, **overrides) -> dict:
    payload = {
        "pathway_id": pathway_id,
        "province": "河南",
        "rule_type": "户籍",
        "rule_desc": "本人具有当地连续 3 年以上户籍。",
        "params": {"years": 3},
        "year": 2026,
        "source": {
            "source_name": "河南省教育考试院",
            "source_url": "https://www.haeea.cn/rules",
            "year": 2026,
        },
    }
    payload.update(overrides)
    return payload


def pathway_payload(**overrides) -> dict:
    payload = {
        "name": unique("测试途径"),
        "category": "普通类",
        "batch": "本科批",
        "target_group": "全体考生",
        "apply_time": "6 月",
        "description": "管理端新建途径测试。",
        "priority": "P2",
        "data_status": "schema_only",
        "year": 2026,
        "source": {
            "source_name": "河南省教育考试院",
            "source_url": "https://www.haeea.cn/new",
            "year": 2026,
        },
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# 8.1 鉴权
# --------------------------------------------------------------------------- #
PROTECTED_CALLS = [
    ("get", "/api/admin/me"),
    ("get", "/api/admin/docs"),
    ("get", "/api/admin/pathways"),
    ("get", "/api/admin/pathway-rules"),
    ("get", "/api/admin/pathway-regions"),
    ("get", "/api/admin/stats"),
    ("get", "/api/admin/audit-logs"),
    ("post", "/api/admin/docs"),
    ("delete", "/api/admin/docs/1"),
    ("post", "/api/admin/pathway-rules"),
    ("put", "/api/admin/pathway-rules/1"),
    ("post", "/api/admin/pathways"),
]


@case("01 未登录访问任一管理端接口一律 1002")
def _() -> None:
    for method, path in PROTECTED_CALLS:
        assert code_of(method, path) == 1002, (method, path)


@case("02 持 C 端用户令牌访问管理端一律 1003（M0-5 验收）")
def _() -> None:
    token = user_token()
    for method, path in PROTECTED_CALLS:
        assert code_of(method, path, token) == 1003, (method, path)


@case("03 伪造/乱码令牌访问管理端 1002")
def _() -> None:
    assert code_of("get", "/api/admin/me", "not-a-real-token") == 1002


@case("04 管理端登录成功返回 token 与 admin 信息，/me 可用")
def _() -> None:
    body = call(
        "post", "/api/admin/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
    )
    assert body["code"] == 0, body
    payload = body["data"]
    assert payload["token"]
    assert payload["admin"]["username"] == ADMIN_USERNAME
    assert payload["admin"]["role"] == "admin"
    assert isinstance(payload["admin"]["admin_id"], int)

    me = data("get", "/api/admin/me", payload["token"])
    assert me["username"] == ADMIN_USERNAME and me["role"] == "admin"


@case("05 登录失败（口令错 / 账号不存在）均返回 1002 且文案一致")
def _() -> None:
    wrong = call(
        "post", "/api/admin/login", json={"username": ADMIN_USERNAME, "password": "wrong-pass-123"}
    )
    absent = call(
        "post", "/api/admin/login", json={"username": "no_such_admin", "password": ADMIN_PASSWORD}
    )
    assert wrong["code"] == 1002 and absent["code"] == 1002, (wrong, absent)
    assert wrong["message"] == absent["message"], "文案不一致会暴露账号是否存在"


@case("06 reviewer 角色账号同样通过管理端鉴权（角色细分见 PR 说明）")
def _() -> None:
    token = login(REVIEWER_USERNAME, REVIEWER_PASSWORD)
    me = data("get", "/api/admin/me", token)
    assert me["role"] == "reviewer"


# --------------------------------------------------------------------------- #
# 8.1 操作留痕
# --------------------------------------------------------------------------- #
@case("07 登录成功写入留痕，含操作人 / 时间 / 动作")
def _() -> None:
    login()
    token = admin_token()
    page = data("get", "/api/admin/audit-logs", token, params={"action": "admin.login"})
    assert set(page) == PAGINATION_KEYS, sorted(page)
    assert page["total"] >= 1, page
    row = page["items"][0]
    assert row["admin_username"] == ADMIN_USERNAME, row
    assert row["action"] == "admin.login", row
    assert row["created_at"], "留痕缺少时间"
    assert isinstance(row["admin_id"], int), row


# --------------------------------------------------------------------------- #
# 8.2 语料管理
# --------------------------------------------------------------------------- #
@case("08 导入语料成功：返回 doc_id 与切片数")
def _() -> None:
    created = data("post", "/api/admin/docs", admin_token(), json=doc_payload())
    assert isinstance(created["doc_id"], int), created
    assert created["chunk_count"] == 2, created


@case("09 缺来源导入被拒（4001），三种缺法都拦住（8.2 验收）")
def _() -> None:
    token = admin_token()
    assert code_of("post", "/api/admin/docs", token, json=doc_payload(source_name="")) == 4001
    assert code_of("post", "/api/admin/docs", token, json=doc_payload(source_url="")) == 4001
    assert code_of("post", "/api/admin/docs", token, json=doc_payload(year=0)) == 4001


@case("10 缺来源被拒后库内不新增语料")
def _() -> None:
    token = admin_token()
    before = data("get", "/api/admin/docs", token)["total"]
    code_of("post", "/api/admin/docs", token, json=doc_payload(source_url=""))
    after = data("get", "/api/admin/docs", token)["total"]
    assert before == after, (before, after)


@case("11 年份越界 1001，途径不存在 1001")
def _() -> None:
    token = admin_token()
    assert code_of("post", "/api/admin/docs", token, json=doc_payload(year=1900)) == 1001
    assert (
        code_of("post", "/api/admin/docs", token, json=doc_payload(pathway_id="p_not_exist")) == 1001
    )


@case("12 语料列表支持按省份 / 年份 / 文种 / 关键词归档检索")
def _() -> None:
    token = admin_token()
    title = unique("归档检索")
    data("post", "/api/admin/docs", token, json=doc_payload(title=title, province="湖北", doc_type="公告", year=2025))

    by_province = data("get", "/api/admin/docs", token, params={"province": "湖北"})
    assert by_province["total"] >= 1
    assert all(item["province"] == "湖北" for item in by_province["items"])

    by_year = data("get", "/api/admin/docs", token, params={"year": 2025})
    assert all(item["year"] == 2025 for item in by_year["items"])

    by_type = data("get", "/api/admin/docs", token, params={"doc_type": "公告"})
    assert all(item["doc_type"] == "公告" for item in by_type["items"])

    by_keyword = data("get", "/api/admin/docs", token, params={"keyword": title})
    assert [item["title"] for item in by_keyword["items"]] == [title]


@case("13 语料列表分页包形状固定，非法参数 1001")
def _() -> None:
    token = admin_token()
    page = data("get", "/api/admin/docs", token, params={"page": 1, "page_size": 2})
    assert set(page) == PAGINATION_KEYS, sorted(page)
    assert len(page["items"]) <= 2
    assert code_of("get", "/api/admin/docs", token, params={"page": 0}) == 1001
    assert code_of("get", "/api/admin/docs", token, params={"page_size": 200}) == 1001


@case("14 删除语料返回 null，连带删除其切片")
def _() -> None:
    token = admin_token()
    created = data("post", "/api/admin/docs", token, json=doc_payload())
    doc_id = created["doc_id"]

    with SessionLocal() as db:
        before = int(
            db.scalar(
                select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.doc_id == doc_id)
            )
            or 0
        )
    assert before == created["chunk_count"] > 0

    assert data("delete", f"/api/admin/docs/{doc_id}", token) is None

    with SessionLocal() as db:
        after = int(
            db.scalar(
                select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.doc_id == doc_id)
            )
            or 0
        )
    assert after == 0, "删除语料后仍残留切片"
    titles = [item["doc_id"] for item in data("get", "/api/admin/docs", token)["items"]]
    assert doc_id not in titles


@case("15 删除不存在的语料返回 1001")
def _() -> None:
    assert code_of("delete", "/api/admin/docs/999999", admin_token()) == 1001


# --------------------------------------------------------------------------- #
# 8.6 途径字典
# --------------------------------------------------------------------------- #
@case("16 途径列表读库，条数与字典文件一致且可按优先级过滤")
def _() -> None:
    token = admin_token()
    items = data("get", "/api/admin/pathways", token)
    assert isinstance(items, list), items
    assert len(items) == TOTAL_PATHWAYS == SEEDED["pathway"], (len(items), SEEDED)
    p0 = data("get", "/api/admin/pathways", token, params={"priority": "P0"})
    assert len(p0) == P0_PATHWAYS, (len(p0), P0_PATHWAYS)
    assert all(item["priority"] == "P0" for item in p0)


@case("17 途径列表项字段与产品书 6.2.1 结构一致，且带来源")
def _() -> None:
    items = data("get", "/api/admin/pathways", admin_token())
    item = next(row for row in items if row["pathway_id"] == SAMPLE_PATHWAY)
    for field in ("pathway_id", "name", "category", "batch", "target_group", "apply_time", "priority", "year", "source"):
        assert field in item, field
    for field in ("source_name", "source_url", "year"):
        assert item["source"].get(field), (field, item["source"])


@case("18 新建途径缺来源 4001；附来源则成功并可查")
def _() -> None:
    token = admin_token()
    bad = pathway_payload(source={"source_name": "", "source_url": "", "year": 0})
    assert code_of("post", "/api/admin/pathways", token, json=bad) == 4001

    created = data("post", "/api/admin/pathways", token, json=pathway_payload())
    assert created["pathway_id"].startswith("p_"), created
    ids = [item["pathway_id"] for item in data("get", "/api/admin/pathways", token)]
    assert created["pathway_id"] in ids


@case("19 修改途径：缺来源 4001，不存在 1001，成功则字段生效")
def _() -> None:
    token = admin_token()
    created = data("post", "/api/admin/pathways", token, json=pathway_payload())
    pathway_id = created["pathway_id"]

    bad = pathway_payload(source={"source_name": "", "source_url": "", "year": 0})
    assert code_of("put", f"/api/admin/pathways/{pathway_id}", token, json=bad) == 4001
    assert code_of("put", "/api/admin/pathways/p_absent", token, json=pathway_payload()) == 1001

    new_name = unique("改名途径")
    assert data(
        "put", f"/api/admin/pathways/{pathway_id}", token, json=pathway_payload(name=new_name)
    ) is None
    items = {item["pathway_id"]: item for item in data("get", "/api/admin/pathways", token)}
    assert items[pathway_id]["name"] == new_name


# --------------------------------------------------------------------------- #
# 8.6 资格规则（核心验收：未填来源无法保存）
# --------------------------------------------------------------------------- #
def rule_count(token: str, pathway_id: str = SAMPLE_PATHWAY) -> int:
    return len(data("get", "/api/admin/pathway-rules", token, params={"pathway_id": pathway_id})["items"])


@case("20 未填来源无法保存规则：4001 且库内不新增（8.6 验收）")
def _() -> None:
    token = admin_token()
    before = rule_count(token)

    missing_name = rule_payload(source={"source_name": "", "source_url": "https://x.cn", "year": 2026})
    missing_url = rule_payload(source={"source_name": "河南省教育考试院", "source_url": "", "year": 2026})
    missing_year = rule_payload(source={"source_name": "河南省教育考试院", "source_url": "https://x.cn", "year": 0})

    for payload in (missing_name, missing_url, missing_year):
        assert code_of("post", "/api/admin/pathway-rules", token, json=payload) == 4001, payload

    assert rule_count(token) == before, "被拒的规则不应入库"


@case("21 附来源可保存规则，列表回显来源三要素")
def _() -> None:
    token = admin_token()
    created = data("post", "/api/admin/pathway-rules", token, json=rule_payload())
    assert isinstance(created["rule_id"], int), created

    items = data("get", "/api/admin/pathway-rules", token, params={"pathway_id": SAMPLE_PATHWAY})["items"]
    row = next(item for item in items if item["rule_id"] == created["rule_id"])
    assert row["pathway_id"] == SAMPLE_PATHWAY
    assert row["rule_type"] == "户籍"
    assert row["params"] == {"years": 3}
    assert row["source"]["source_name"] == "河南省教育考试院"
    assert row["source"]["year"] == 2026


@case("22 规则列表可按省份与类型过滤")
def _() -> None:
    token = admin_token()
    data("post", "/api/admin/pathway-rules", token, json=rule_payload(province="河北", rule_type="学籍"))
    by_province = data("get", "/api/admin/pathway-rules", token, params={"province": "河北"})["items"]
    assert by_province and all(item["province"] == "河北" for item in by_province)
    by_type = data("get", "/api/admin/pathway-rules", token, params={"rule_type": "学籍"})["items"]
    assert by_type and all(item["rule_type"] == "学籍" for item in by_type)


@case("23 规则途径不存在 1001；修改规则缺来源 4001、不存在 1001、成功生效")
def _() -> None:
    token = admin_token()
    assert code_of("post", "/api/admin/pathway-rules", token, json=rule_payload(pathway_id="p_absent")) == 1001

    created = data("post", "/api/admin/pathway-rules", token, json=rule_payload(rule_type="成绩"))
    rule_id = created["rule_id"]

    bad = rule_payload(source={"source_name": "", "source_url": "", "year": 0})
    assert code_of("put", f"/api/admin/pathway-rules/{rule_id}", token, json=bad) == 4001
    assert code_of("put", "/api/admin/pathway-rules/999999", token, json=rule_payload()) == 1001

    assert data(
        "put", f"/api/admin/pathway-rules/{rule_id}", token, json=rule_payload(rule_type="区域", rule_desc="改为区域规则")
    ) is None
    items = {item["rule_id"]: item for item in data("get", "/api/admin/pathway-rules", token, params={"pathway_id": SAMPLE_PATHWAY})["items"]}
    assert items[rule_id]["rule_type"] == "区域"
    assert items[rule_id]["rule_desc"] == "改为区域规则"


# --------------------------------------------------------------------------- #
# 8.6 区域名单
# --------------------------------------------------------------------------- #
@case("24 专项区域名单只读可查（数据由 ③ 号入库，当前为空数组）")
def _() -> None:
    token = admin_token()
    payload = data("get", "/api/admin/pathway-regions", token, params={"pathway_id": "national-plan"})
    assert isinstance(payload["items"], list), payload


# --------------------------------------------------------------------------- #
# 8.7 数据统计
# --------------------------------------------------------------------------- #
@case("25 统计值与库内计数一致（8.7 验收）")
def _() -> None:
    token = admin_token()
    stats = data("get", "/api/admin/stats", token)

    with SessionLocal() as db:
        expected = {
            "doc_count": int(db.scalar(select(func.count()).select_from(KnowledgeDoc)) or 0),
            "chunk_count": int(db.scalar(select(func.count()).select_from(KnowledgeChunk)) or 0),
            "qa_count": int(db.scalar(select(func.count()).select_from(QaLog)) or 0),
            "review_pending_count": int(
                db.scalar(
                    select(func.count())
                    .select_from(ReviewTask)
                    .where(ReviewTask.status == "pending")
                )
                or 0
            ),
            "low_confidence_count": int(
                db.scalar(select(func.count()).select_from(QaLog).where(QaLog.confidence == "low")) or 0
            ),
        }
    for key, value in expected.items():
        assert stats[key] == value, (key, stats[key], value)


@case("26 统计字段齐全，覆盖度逐途径给出且能标出未覆盖")
def _() -> None:
    token = admin_token()
    # 构造一条「挂了途径」的语料，用于验证 covered 标记的两种取值
    data("post", "/api/admin/docs", token, json=doc_payload(pathway_id=SAMPLE_PATHWAY))

    stats = data("get", "/api/admin/stats", token)
    for field in ("doc_count", "chunk_count", "qa_count", "low_confidence_count", "review_pending_count", "coverage_by_pathway"):
        assert field in stats, field

    coverage = stats["coverage_by_pathway"]
    with SessionLocal() as db:
        pathway_total = int(db.scalar(select(func.count()).select_from(Pathway)) or 0)
    assert len(coverage) == pathway_total, (len(coverage), pathway_total)
    for row in coverage:
        for field in ("pathway_id", "pathway_name", "doc_count", "chunk_count", "covered"):
            assert field in row, (field, row)
        assert isinstance(row["covered"], bool), row
        assert row["covered"] == (row["doc_count"] > 0), row

    by_id = {row["pathway_id"]: row for row in coverage}
    assert by_id[SAMPLE_PATHWAY]["covered"] is True, by_id[SAMPLE_PATHWAY]
    assert any(not row["covered"] for row in coverage), "应有途径尚未挂语料"


@case("27 统计随库内变化实时更新（不缓存）")
def _() -> None:
    token = admin_token()
    before = data("get", "/api/admin/stats", token)["doc_count"]
    data("post", "/api/admin/docs", token, json=doc_payload())
    after = data("get", "/api/admin/stats", token)["doc_count"]
    assert after == before + 1, (before, after)


# --------------------------------------------------------------------------- #
# 8.1 写操作留痕
# --------------------------------------------------------------------------- #
@case("28 语料与规则的写操作都留痕，含操作人 / 动作 / 对象")
def _() -> None:
    token = admin_token()
    doc = data("post", "/api/admin/docs", token, json=doc_payload())
    data("delete", f"/api/admin/docs/{doc['doc_id']}", token)
    data("post", "/api/admin/pathway-rules", token, json=rule_payload())

    actions = {"doc.create", "doc.delete", "pathway.create", "rule.create"}
    for action in actions:
        page = data("get", "/api/admin/audit-logs", token, params={"action": action})
        assert page["total"] >= 1, f"缺少留痕：{action}"
        row = page["items"][0]
        assert row["admin_username"] == ADMIN_USERNAME, row
        assert row["created_at"], row
        assert row["target_type"], row
        assert row["target_id"], row

    doc_create = data("get", "/api/admin/audit-logs", token, params={"action": "doc.create"})["items"][0]
    assert doc_create["target_type"] == "doc"
    assert doc_create["target_id"] == str(doc["doc_id"])
    assert doc_create["detail"].get("title"), doc_create


@case("29 留痕只增不改：未提供修改 / 删除入口，且不含口令 / 令牌字段")
def _() -> None:
    token = admin_token()
    page = data("get", "/api/admin/audit-logs", token, params={"page_size": 50})
    assert page["total"] >= 1
    for row in page["items"]:
        detail = row["detail"]
        assert "password" not in detail and "token" not in detail, row

    put = client.request("put", "/api/admin/audit-logs", headers=auth(token))
    delete = client.request("delete", "/api/admin/audit-logs", headers=auth(token))
    assert put.status_code == 405, put.status_code
    assert delete.status_code == 405, delete.status_code


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
    print(f"\n管理端用例：{total - len(failures)}/{total} 通过")
    if failures:
        return 1
    print("admin tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
