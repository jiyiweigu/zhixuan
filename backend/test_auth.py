"""认证与档案模块测试（tasks.md 3.1–3.5，对应 3.7 的后端侧用例）。

覆盖范围：
- 注册/登录/退出/注销全流程，令牌签发与校验，失败限流；
- 口令只存加盐哈希、日志不含明文（tasks.md 3.1、9.4 验证项）；
- 档案读写与校验、局部更新、专项标记、偏好联动方案生成（3.4、3.5）。

纯脚本，无 pytest 依赖，直接运行：
    cd backend && .venv\\Scripts\\python.exe test_auth.py
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

# 环境变量必须在导入 app.* 之前设置：settings 在首次导入时读取一次
_WORK = Path(tempfile.mkdtemp(prefix="zhixuan_auth_test_"))
os.environ["ZHIXUAN_DATABASE_URL"] = f"sqlite:///{(_WORK / 'auth.db').as_posix()}"
os.environ["ZHIXUAN_SECRET_KEY"] = "test-secret-key-auth-suite-at-least-32-bytes-long"
os.environ["ZHIXUAN_ENV"] = "test"
os.environ["ZHIXUAN_LOGIN_MAX_FAILURES"] = "3"
os.environ["ZHIXUAN_LOGIN_LOCK_SECONDS"] = "1"

import jwt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.ratelimit import FailureLimiter  # noqa: E402
from app.core.response import BizError  # noqa: E402
from app.core.security import (  # noqa: E402
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db.session import SessionLocal, create_all  # noqa: E402
from app.main import app  # noqa: E402
from app.models.profile import Profile  # noqa: E402
from app.models.user import User  # noqa: E402

PASSWORD = "change-me"
WRONG_PASSWORD = "not-my-password"

create_all()
client = TestClient(app)

# 默认压低业务日志，避免正常用例刷屏；"日志不含明文口令"用例会临时打开
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
def unique_name(prefix: str = "stu") -> str:
    _counter["n"] += 1
    return f"{prefix}{_counter['n']:04d}"


def register(username: str | None = None, password: str = PASSWORD):
    name = username or unique_name()
    resp = client.post("/api/auth/register", json={"username": name, "password": password})
    return name, resp


def login(username: str, password: str = PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def new_user() -> tuple[str, str, dict[str, str]]:
    """注册一个用户，返回 (用户名, 用户 ID, 认证头)。"""
    name, resp = register()
    data = resp.json()["data"]
    return name, data["user_id"], headers(data["access_token"])


def db_user(username: str) -> User | None:
    with SessionLocal() as session:
        return session.scalar(select(User).where(User.username == username))


def profile_payload(**overrides):
    payload = {"province": "河南", "score": 620, "subject_type": "物理类"}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# 1. 注册
# --------------------------------------------------------------------------- #
@case("01 注册成功：返回 user_id / username / access_token，响应包结构完整")
def _() -> None:
    name, resp = register()
    assert resp.status_code == 200, resp.status_code
    body = resp.json()
    assert set(body) == {"code", "message", "data", "trace_id"}, body.keys()
    assert body["code"] == 0, body
    data = body["data"]
    assert data["username"] == name
    assert data["user_id"].startswith("u_")
    assert len(data["access_token"]) > 20
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0


@case("02 数据库中不存明文口令：只有 PBKDF2 加盐哈希")
def _() -> None:
    name, _resp = register(password="Secret-Pass-9527")
    user = db_user(name)
    assert user is not None
    assert "Secret-Pass-9527" not in user.password_hash
    assert user.password_hash.startswith("pbkdf2_sha256$")
    columns = {column.name for column in User.__table__.columns}
    assert "password" not in columns
    assert not {"plain_password", "password_plain"} & columns


@case("03 同一口令两次注册得到不同哈希（每用户独立盐）")
def _() -> None:
    first, _r1 = register(password=PASSWORD)
    second, _r2 = register(password=PASSWORD)
    assert db_user(first).password_hash != db_user(second).password_hash


@case("04 哈希校验：正确口令通过、错误口令与损坏串返回 False")
def _() -> None:
    encoded = hash_password(PASSWORD)
    assert verify_password(PASSWORD, encoded) is True
    assert verify_password("别的口令", encoded) is False
    assert verify_password(PASSWORD, "坏掉的字符串") is False
    assert verify_password(PASSWORD, "md5$1$aaaa$bbbb") is False


@case("05 用户名重复 → 1006")
def _() -> None:
    name, _resp = register()
    _again, resp = register(username=name)
    assert resp.json()["code"] == 1006, resp.json()
    assert resp.json()["data"] is None
    assert "已存在" in resp.json()["message"]


@case("06 用户名过短（1 字）→ 1001")
def _() -> None:
    resp = client.post("/api/auth/register", json={"username": "x", "password": PASSWORD})
    assert resp.json()["code"] == 1001, resp.json()


@case("07 口令过短（5 位）→ 1001")
def _() -> None:
    resp = client.post("/api/auth/register", json={"username": unique_name(), "password": "12345"})
    assert resp.json()["code"] == 1001, resp.json()


# --------------------------------------------------------------------------- #
# 2. 登录与限流
# --------------------------------------------------------------------------- #
@case("08 登录成功：令牌可解出 sub / username / exp / jti")
def _() -> None:
    name, resp = register()
    user_id = resp.json()["data"]["user_id"]
    body = login(name).json()
    assert body["code"] == 0, body
    claims = decode_access_token(body["data"]["access_token"])
    assert claims["sub"] == user_id
    assert claims["username"] == name
    assert claims["exp"] > time.time()
    assert len(claims["jti"]) >= 16


@case("09 口令错误 → 1002")
def _() -> None:
    name, _resp = register()
    body = login(name, WRONG_PASSWORD).json()
    assert body["code"] == 1002, body
    assert body["data"] is None


@case("10 用户不存在与口令错误返回同一文案（防用户名枚举）")
def _() -> None:
    name, _resp = register()
    missing = login(unique_name("ghost"), WRONG_PASSWORD).json()
    wrong = login(name, WRONG_PASSWORD).json()
    assert missing["code"] == wrong["code"] == 1002
    assert missing["message"] == wrong["message"]


@case("11 连续失败达阈值 → 1008 限流，提示剩余秒数")
def _() -> None:
    name, _resp = register()
    for _attempt in range(3):
        assert login(name, WRONG_PASSWORD).json()["code"] == 1002
    body = login(name, WRONG_PASSWORD).json()
    assert body["code"] == 1008, body
    assert "秒后重试" in body["message"], body["message"]


@case("12 锁定期间口令正确也被拒（限流优先于凭据校验）")
def _() -> None:
    name, _resp = register()
    for _attempt in range(3):
        login(name, WRONG_PASSWORD)
    body = login(name).json()
    assert body["code"] == 1008, body


@case("13 锁定窗口过期后恢复登录")
def _() -> None:
    name, _resp = register()
    for _attempt in range(3):
        login(name, WRONG_PASSWORD)
    assert login(name).json()["code"] == 1008
    time.sleep(1.1)
    body = login(name).json()
    assert body["code"] == 0, body


@case("14 登录成功后失败计数清零")
def _() -> None:
    name, _resp = register()
    assert login(name, WRONG_PASSWORD).json()["code"] == 1002
    assert login(name, WRONG_PASSWORD).json()["code"] == 1002
    assert login(name).json()["code"] == 0
    body = login(name, WRONG_PASSWORD).json()
    assert body["code"] == 1002, body


@case("15 限流器单元行为：阈值、retry_after、reset、窗口滑动")
def _() -> None:
    timer = {"now": 0.0}
    limiter = FailureLimiter(max_failures=2, lock_seconds=60, clock=lambda: timer["now"])
    assert limiter.retry_after("u", "ip") == 0
    limiter.record_failure("u", "ip")
    assert limiter.retry_after("u", "ip") == 0
    limiter.record_failure("u", "ip")
    assert limiter.retry_after("u", "ip") > 0
    try:
        limiter.ensure_allowed("u", "ip")
    except BizError as exc:
        assert exc.code == 1008, exc.code
    else:
        raise AssertionError("应抛出限流异常")
    limiter.reset("u", "ip")
    assert limiter.retry_after("u", "ip") == 0
    # 窗口滑动：失败记录滑出窗口后自动解锁
    limiter.record_failure("v", "ip")
    limiter.record_failure("v", "ip")
    assert limiter.retry_after("v", "ip") > 0
    timer["now"] = 61.0
    assert limiter.retry_after("v", "ip") == 0


# --------------------------------------------------------------------------- #
# 3. 令牌校验与退出
# --------------------------------------------------------------------------- #
@case("16 无令牌访问受保护接口 → 1002")
def _() -> None:
    body = client.get("/api/user/profile").json()
    assert body["code"] == 1002, body
    assert "未登录" in body["message"]


@case("17 伪造签名令牌 → 1002")
def _() -> None:
    forged = jwt.encode(
        {"sub": "u_forged", "username": "x", "exp": int(time.time()) + 600},
        "another-secret",
        algorithm="HS256",
    )
    body = client.get("/api/user/profile", headers=headers(forged)).json()
    assert body["code"] == 1002, body


@case("18 乱码令牌 → 1002")
def _() -> None:
    body = client.get("/api/user/profile", headers=headers("not-a-jwt")).json()
    assert body["code"] == 1002, body


@case("19 过期令牌 → 1002")
def _() -> None:
    token, _claims = create_access_token("u_expired", "expired", ttl_minutes=-1)
    body = client.get("/api/user/profile", headers=headers(token)).json()
    assert body["code"] == 1002, body
    assert "过期" in body["message"]


@case("20 非 Bearer 认证头视为未登录 → 1002")
def _() -> None:
    _name, _uid, auth = new_user()
    token = auth["Authorization"].split(" ")[1]
    body = client.get("/api/user/profile", headers={"Authorization": f"Token {token}"}).json()
    assert body["code"] == 1002, body


@case("21 退出登录后原令牌立即失效")
def _() -> None:
    _name, _uid, auth = new_user()
    assert client.get("/api/user/profile", headers=auth).json()["code"] == 0
    assert client.post("/api/auth/logout", headers=auth).json()["code"] == 0
    body = client.get("/api/user/profile", headers=auth).json()
    assert body["code"] == 1002, body


@case("22 退出登录未带令牌 → 1002")
def _() -> None:
    body = client.post("/api/auth/logout").json()
    assert body["code"] == 1002, body


@case("23 /api/auth/me 返回当前用户身份")
def _() -> None:
    name, user_id, auth = new_user()
    body = client.get("/api/auth/me", headers=auth).json()
    assert body["code"] == 0, body
    assert body["data"]["user_id"] == user_id
    assert body["data"]["username"] == name
    assert body["data"]["is_admin"] is False
    assert "password_hash" not in body["data"]


@case("24 注册与登录的日志不含明文口令")
def _() -> None:
    collected: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            collected.append(record.getMessage())

    logger = logging.getLogger("zhixuan")
    handler = _Capture()
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        name, _resp = register(password="Secret-Pass-9527")
        login(name, password="Secret-Pass-9527")
        login(name, password=WRONG_PASSWORD)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    text = " | ".join(collected)
    assert "Secret-Pass-9527" not in text, text
    assert WRONG_PASSWORD not in text, text
    assert name in text, "至少应记录到用户名，便于排查"


# --------------------------------------------------------------------------- #
# 4. 考生档案
# --------------------------------------------------------------------------- #
@case("25 首次读取档案自动建立默认档案")
def _() -> None:
    _name, _uid, auth = new_user()
    body = client.get("/api/user/profile", headers=auth).json()
    data = body["data"]
    assert data["province"] == "河南"
    assert data["score"] == 0
    assert data["household_type"] == "未知"
    assert data["special_marks"] == []
    assert data["preferences"]["strategy"] == "稳"


@case("26 档案写入后再次读取一致（含户籍与学籍字段）")
def _() -> None:
    _name, _uid, auth = new_user()
    payload = profile_payload(
        score=630,
        household_type="农村",
        home_county="兰考县",
        enrollment_county="兰考县",
        household_years=3,
        enrollment_years=3,
        parent_household_local=True,
    )
    saved = client.put("/api/user/profile", headers=auth, json=payload).json()["data"]
    assert saved["score"] == 630
    assert saved["home_county"] == "兰考县"
    assert saved["parent_household_local"] is True
    assert saved["updated_at"]

    reread = client.get("/api/user/profile", headers=auth).json()["data"]
    for key, value in payload.items():
        assert reread[key] == value, (key, reread[key], value)


@case("27 非法分数被拦截：751 与 -1 → 1001")
def _() -> None:
    _name, _uid, auth = new_user()
    high = client.put("/api/user/profile", headers=auth, json=profile_payload(score=751)).json()
    low = client.put("/api/user/profile", headers=auth, json=profile_payload(score=-1)).json()
    assert high["code"] == 1001, high
    assert low["code"] == 1001, low
    assert "score" in high["message"], high["message"]


@case("28 局部更新：只传三字段不会清空已保存的户籍信息")
def _() -> None:
    _name, _uid, auth = new_user()
    client.put(
        "/api/user/profile",
        headers=auth,
        json=profile_payload(household_type="农村", home_county="兰考县", household_years=3),
    )
    updated = client.put("/api/user/profile", headers=auth, json=profile_payload(score=640)).json()[
        "data"
    ]
    assert updated["score"] == 640
    assert updated["home_county"] == "兰考县"
    assert updated["household_years"] == 3
    assert updated["household_type"] == "农村"


@case("29 专项标记取值非法 → 1001，且提示可用取值")
def _() -> None:
    _name, _uid, auth = new_user()
    body = client.put(
        "/api/user/profile",
        headers=auth,
        json=profile_payload(special_marks=["不存在的途径"]),
    ).json()
    assert body["code"] == 1001, body
    assert "可用取值" in body["message"], body["message"]


@case("30 专项标记可用中文名称，统一存为途径 id")
def _() -> None:
    _name, _uid, auth = new_user()
    catalog = client.get("/api/pathways").json()["data"]
    target = next(item for item in catalog if item["status"] == "可判定")
    saved = client.put(
        "/api/user/profile",
        headers=auth,
        json=profile_payload(special_marks=[target["name"], target["id"]]),
    ).json()["data"]
    assert saved["special_marks"] == [target["id"]], saved["special_marks"]


@case("31 档案偏好联动方案生成：未显式提供 strategy 时沿用档案值")
def _() -> None:
    _name, _uid, auth = new_user()
    client.put(
        "/api/user/profile",
        headers=auth,
        json=profile_payload(preferences={"strategy": "冲", "preferred_majors": ["临床医学"]}),
    )
    inherited = client.post(
        "/api/plans", headers=auth, json={"profile": profile_payload()}
    ).json()["data"]
    assert inherited["strategy"] == "冲", inherited["strategy"]

    explicit = client.post(
        "/api/plans",
        headers=auth,
        json={"profile": profile_payload(), "strategy": "保"},
    ).json()["data"]
    assert explicit["strategy"] == "保", explicit["strategy"]


@case("32 已登录资格自检：请求未提供的字段回落档案，显式传值优先")
def _() -> None:
    _name, _uid, auth = new_user()
    client.put(
        "/api/user/profile",
        headers=auth,
        json=profile_payload(
            household_type="农村",
            home_county="兰考县",
            enrollment_county="兰考县",
            household_years=3,
            enrollment_years=3,
            parent_household_local=True,
        ),
    )
    inherited = client.post(
        "/api/pathways/eligibility-check", headers=auth, json=profile_payload()
    ).json()["data"]
    assert inherited["profile"]["home_county"] == "兰考县"
    assert inherited["profile"]["household_type"] == "农村"
    assert inherited["profile"]["enrollment_years"] == 3

    explicit = client.post(
        "/api/pathways/eligibility-check",
        headers=auth,
        json=profile_payload(home_county="郑州市"),
    ).json()["data"]
    assert explicit["profile"]["home_county"] == "郑州市"


@case("33 游客自检不被鉴权破坏（tasks.md 4.5）")
def _() -> None:
    body = client.post(
        "/api/pathways/eligibility-check", json=profile_payload()
    ).json()
    assert body["code"] == 0, body
    data = body["data"]
    assert data["eligible"] == ["普通批"], data["eligible"]
    assert "国家专项计划" in data["pending"], data["pending"]


@case("34 无效令牌不阻塞游客自检（按游客处理）")
def _() -> None:
    body = client.post(
        "/api/pathways/eligibility-check",
        headers=headers("not-a-jwt"),
        json=profile_payload(),
    ).json()
    assert body["code"] == 0, body


@case("35 方案生成需登录（契约 Auth: yes）→ 未登录 1002")
def _() -> None:
    body = client.post("/api/plans", json={"profile": profile_payload()}).json()
    assert body["code"] == 1002, body


# --------------------------------------------------------------------------- #
# 5. 账号注销
# --------------------------------------------------------------------------- #
@case("36 注销口令校验失败 → 1002，账号仍可正常使用")
def _() -> None:
    name, _uid, auth = new_user()
    body = client.request(
        "DELETE", "/api/user", headers=auth, json={"password": WRONG_PASSWORD}
    ).json()
    assert body["code"] == 1002, body
    assert client.get("/api/user/profile", headers=auth).json()["code"] == 0
    assert login(name).json()["code"] == 0


@case("37 注销成功：令牌失效、账号匿名化、档案被删除")
def _() -> None:
    name, user_id, auth = new_user()
    client.put("/api/user/profile", headers=auth, json=profile_payload(score=620))

    body = client.request("DELETE", "/api/user", headers=auth, json={"password": PASSWORD}).json()
    assert body["code"] == 0, body

    assert client.get("/api/user/profile", headers=auth).json()["code"] == 1002
    assert client.get("/api/auth/me", headers=auth).json()["code"] == 1002

    with SessionLocal() as session:
        user = session.get(User, user_id)
        assert user is not None, "用户行应保留（保留 ID 供审计）"
        assert user.status == "deleted"
        assert user.deleted_at is not None
        assert user.username == f"deleted_{user_id}"
        assert session.get(Profile, user_id) is None, "档案行应被删除"
        assert name != user.username, "原用户名应已脱敏"


@case("38 注销后原用户名与原口令都无法再登录")
def _() -> None:
    name, user_id, auth = new_user()
    client.request("DELETE", "/api/user", headers=auth, json={"password": PASSWORD})
    assert login(name).json()["code"] == 1002
    assert login(name, PASSWORD).json()["code"] == 1002
    assert login(f"deleted_{user_id}", PASSWORD).json()["code"] == 1002


if __name__ == "__main__":
    print(f"test_auth: 共 {len(CASES)} 个用例\n")
    failures: list[tuple[str, str]] = []
    for title, func in CASES:
        try:
            func()
        except AssertionError as exc:
            failures.append((title, str(exc) or "断言失败"))
            print(f"  x {title}\n      {exc}")
        except Exception as exc:  # noqa: BLE001
            failures.append((title, f"{type(exc).__name__}: {exc}"))
            print(f"  x {title}\n      {type(exc).__name__}: {exc}")
        else:
            print(f"  v {title}")

    passed = len(CASES) - len(failures)
    print(f"\n{passed}/{len(CASES)} 通过")
    if failures:
        print("失败用例：")
        for title, detail in failures:
            print(f"  - {title}: {detail}")
        raise SystemExit(1)
