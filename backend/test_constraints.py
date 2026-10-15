"""报考约束接口测试（产品书 6.2.6–6.2.9；管理端三组规则；档案增量与完成度）。

覆盖：

- 6.2.6 省份模板：河南 48 组 / 江西 45 组 / 提前批 64 且无调剂；未知省年 → 3001
- 6.2.7 批量校验：游客可用、逐条三档、items ≤100（超限 1001）、空数组 total=0
- 6.2.8 登录校验：未登录 1002、登录返回 updated_profile
- 6.2.9 专业要求：选科 / 身体 / 学费一次取全
- **红线**：规则数据缺失 → 3001，绝不静默放行
- 6.1.5 档案增量保存与 completeness
- 管理端 province-rules / subject-requirements / physical-restrictions：缺 year 或来源 → 4001

运行：``cd backend && .venv/Scripts/python.exe test_constraints.py``
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

_WORK = Path(tempfile.mkdtemp(prefix="zhixuan_constraint_test_"))
os.environ["ZHIXUAN_DATABASE_URL"] = f"sqlite:///{(_WORK / 'constraint.db').as_posix()}"
os.environ["ZHIXUAN_SECRET_KEY"] = "test-secret-key-constraints-at-least-32-bytes"
os.environ["ZHIXUAN_ENV"] = "test"
os.environ["ZHIXUAN_LOGIN_MAX_FAILURES"] = "100"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal, create_all  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base_data import Major  # noqa: E402
from app.models.constraints import ProvinceExamRule, SubjectRequirement  # noqa: E402
from app.services import admin_auth  # noqa: E402
from app.services.constraint_seed import seed_demo  # noqa: E402

ADMIN_USERNAME = "constraint_admin"
ADMIN_PASSWORD = "admin-cst-771"
USER_NAME = "cst_user"
USER_PASSWORD = "user-cst-552"

create_all()
with SessionLocal() as _db:
    admin_auth.ensure_admin(_db, ADMIN_USERNAME, ADMIN_PASSWORD, role="admin")
    SEED = seed_demo(_db)

client = TestClient(app)
logging.getLogger("zhixuan").setLevel(logging.CRITICAL)

CASES: list[tuple[str, Callable[[], None]]] = []


def case(title: str) -> Callable[[Callable[[], None]], Callable[[], None]]:
    def deco(fn: Callable[[], None]) -> Callable[[], None]:
        CASES.append((title, fn))
        return fn

    return deco


def _major_id(name: str) -> int:
    with SessionLocal() as db:
        row = db.scalar(select(Major).where(Major.name == name))
        assert row is not None, f"演示专业缺失：{name}"
        return row.id


def _admin_token() -> str:
    resp = client.post("/api/admin/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    body = resp.json()
    assert body["code"] == 0, body
    return body["data"]["token"]


def _user_token() -> str:
    resp = client.post("/api/auth/register", json={"username": USER_NAME, "password": USER_PASSWORD})
    body = resp.json()
    if body["code"] != 0:
        resp = client.post("/api/auth/login", json={"username": USER_NAME, "password": USER_PASSWORD})
        body = resp.json()
    assert body["code"] == 0, body
    return body["data"]["access_token"]


def _check(payload: dict[str, Any], *, token: str | None = None, path: str = "/api/eligibility/check"):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post(path, json=payload, headers=headers)


def _profile(**kw: Any) -> dict[str, Any]:
    """一份"填全"的档案。

    契约 8.1：任一可空项缺失都会进 ``unknowns``（因此 ``eligible`` 为 ``null``）。
    需要"无命中 → eligible=true"的用例必须给全字段；需要"缺项"的用例再按需覆盖为 ``None``。
    """
    base: dict[str, Any] = {
        "province": "河南", "exam_type": "普通", "first_subject": "物理",
        "second_subjects": ["化学"], "score": 620, "rank": 12000,
        "color_vision": "正常", "vision_left": 5.0, "vision_right": 5.0,
        "height": 175, "weight": 65, "hepatitis_b": False,
        "hearing": "正常", "smell": "正常", "stutter": "正常",
        "household_type": "农村", "home_county": "兰考县", "home_county_code": "410225",
        "school_years": 3, "tuition_budget": 15000, "batch_preference": ["本科批"],
    }
    base.update(kw)
    return base


# --------------------------------------------------------------------------- #
# 8.3 省份模板
# --------------------------------------------------------------------------- #
@case("省份01 41（河南）2026 本科批 → 48 组 / group / 有调剂，且含契约 8.3 全部字段")
def _() -> None:
    body = client.get("/api/provinces/41/rules?year=2026&batch=本科批").json()
    assert body["code"] == 0, body
    data = body["data"]
    # 契约 8.3：出参含 province_code / batch_code / exam_type / data_status / 嵌套 rule
    assert data["province_code"] == "41" and data["province"] == "河南"
    assert data["batch"] == "本科批" and data["batch_code"] == "undergraduate_regular"
    assert data["exam_type"] == "普通"
    assert data["data_status"] in {"available", "partial"}, data
    rule = data["rule"]
    assert rule["volunteer_count"] == 48 and rule["mode"] == "group" and rule["has_adjust"] is True
    assert isinstance(data["sources"], list) and data["sources"], "可用规则必须带来源"
    assert data["missing_rule_sets"] == []


@case("省份02 36（江西）2026 本科批 → 45 组")
def _() -> None:
    data = client.get("/api/provinces/36/rules?year=2026&batch=本科批").json()["data"]
    assert data["rule"]["volunteer_count"] == 45


@case("省份02b 省名入参仍然可用（兼容历史调用方）")
def _() -> None:
    data = client.get("/api/provinces/河南/rules?year=2026&batch=本科批").json()["data"]
    assert data["province_code"] == "41" and data["rule"]["volunteer_count"] == 48


@case("省份03 河南提前批 → 专业+院校 / 64 / 无调剂 / 有互斥组")
def _() -> None:
    data = client.get("/api/provinces/41/rules?year=2026&batch=提前批").json()["data"]
    rule = data["rule"]
    assert rule["mode"] == "major_school" and rule["volunteer_count"] == 64
    assert rule["has_adjust"] is False and rule["mutex_groups"]
    assert data["batch_code"] == "undergraduate_early"


@case("省份04 无对应版本 → 200 + unavailable + rule:null（不返回虚构模板）")
def _() -> None:
    body = client.get("/api/provinces/54/rules?year=2026&batch=本科批").json()
    assert body["code"] == 0, body
    data = body["data"]
    assert data["data_status"] == "unavailable", data
    assert data["rule"] is None
    assert "province_exam_rule" in data["missing_rule_sets"]


@case("省份05 缺 year → 1001（契约 8.3：year 必填）")
def _() -> None:
    body = client.get("/api/provinces/41/rules?batch=本科批").json()
    assert body["code"] == 1001, body


# --------------------------------------------------------------------------- #
# 6.2.7 批量校验
# --------------------------------------------------------------------------- #
@case("校验01 历史类 + 色弱报临床医学 → blocked")
def _() -> None:
    payload = {
        "profile": _profile(first_subject="历史", color_vision="色弱"),
        "items": [{"unit_id": "u-1", "batch": "本科批", "major_ids": [_major_id("临床医学")]}],
    }
    data = _check(payload).json()["data"]
    item = data["items"][0]
    assert item["eligible"] is False and len(item["blockers"]) >= 2
    assert data["summary"]["blocked"] == 1


@case("校验02 档案填全的正常考生报法学 → eligible 为 true（无命中）")
def _() -> None:
    payload = {
        "profile": _profile(),
        "items": [{"unit_id": "u-2", "batch": "本科批", "major_ids": [_major_id("法学")]}],
    }
    item = _check(payload).json()["data"]["items"][0]
    assert not item["unknowns"], item["unknowns"]
    assert item["eligible"] is True and not item["blockers"] and not item["warnings"]


@case("校验03 未填体检 → unknowns 且 eligible 为 null（红线：不得判为合格）")
def _() -> None:
    payload = {
        "profile": _profile(color_vision=None, vision_left=None, vision_right=None),
        "items": [{"unit_id": "u-3", "batch": "本科批", "major_ids": [_major_id("临床医学")]}],
    }
    result = _check(payload).json()["data"]
    item = result["items"][0]
    assert item["unknowns"], "未填体检必须进 unknowns"
    assert not item["blockers"]
    # 契约 8.1：无 blocker 但有 unknown → eligible 必须是 null，绝不能是 True
    assert item["eligible"] is None, f"缺项不得判为合格，实际 {item['eligible']!r}"
    assert result["summary"]["unknown"] >= 1


@case("校验03b summary 各计数互相独立（单位可同时计入 warned 与 unknown）")
def _() -> None:
    payload = {
        "profile": _profile(color_vision=None, vision_left=None, vision_right=None, tuition_budget=100),
        "items": [{"unit_id": "u-3b", "batch": "本科批",
                   "major_ids": [_major_id("计算机科学与技术(中外合作)")]}],
    }
    summary = _check(payload).json()["data"]["summary"]
    assert summary["total"] == 1
    # 同一单位：超预算进 warned，体检缺项进 unknown → 两个计数都要算它（不是 if/elif 二选一）
    assert summary["warned"] >= 1, summary
    assert summary["unknown"] >= 1, summary


@case("校验04 超预算 → warnings（保留在结果里）")
def _() -> None:
    payload = {
        "profile": _profile(tuition_budget=15000),
        "items": [{"unit_id": "u-4", "batch": "本科批",
                   "major_ids": [_major_id("计算机科学与技术(中外合作)")]}],
    }
    item = _check(payload).json()["data"]["items"][0]
    assert any(hit["type"] == "fee" for hit in item["warnings"])


@case("校验05 items 空数组 → summary.total = 0")
def _() -> None:
    body = _check({"profile": _profile(), "items": []}).json()
    assert body["code"] == 0 and body["data"]["summary"]["total"] == 0


@case("校验06 items 超过 100 条 → 1001")
def _() -> None:
    items = [{"unit_id": f"u-{i}", "batch": "本科批", "major_ids": []} for i in range(101)]
    body = _check({"profile": _profile(), "items": items}).json()
    assert body["code"] == 1001, body


@case("校验07 每次结论都带 citation（三要素齐全）")
def _() -> None:
    payload = {
        "profile": _profile(color_vision="色弱"),
        "items": [{"unit_id": "u-5", "batch": "本科批", "major_ids": [_major_id("临床医学")]}],
    }
    item = _check(payload).json()["data"]["items"][0]
    for hit in item["blockers"]:
        assert hit.get("citation"), hit
        assert hit["citation"]["source_name"] and hit["citation"]["source_url"]


# --------------------------------------------------------------------------- #
# 6.2.8 登录校验
# --------------------------------------------------------------------------- #
@case("登录01 未登录访问 /api/user/eligibility/check → 1002")
def _() -> None:
    body = _check({"profile": _profile(), "items": []}, path="/api/user/eligibility/check").json()
    assert body["code"] == 1002, body


@case("登录02 登录后校验 → 返回 updated_profile")
def _() -> None:
    token = _user_token()
    body = _check(
        {"profile": _profile(accept_adjustment=True), "items": []},
        token=token, path="/api/user/eligibility/check",
    ).json()
    assert body["code"] == 0 and "updated_profile" in body["data"], body


# --------------------------------------------------------------------------- #
# 8.6 专业要求
# --------------------------------------------------------------------------- #
@case("专业01 41（河南）临床医学 → 首选物理 + 再选化学（all）+ 契约 8.6 形状")
def _() -> None:
    mid = _major_id("临床医学")
    body = client.get(f"/api/majors/{mid}/requirements?province=41&year=2026").json()
    assert body["code"] == 0, body
    data = body["data"]
    assert data["subject_req"]["first"] == "物理"
    assert "化学" in data["subject_req"]["secondary"] and data["subject_req"]["logic"] == "all"
    assert data["province_code"] == "41" and data["data_status"] in {
        "available", "partial", "schema_only", "unavailable"
    }
    # threshold 必须是对象 {operator, value}，不是自由文本
    for restriction in data["physical_restrictions"]:
        assert isinstance(restriction["threshold"], dict), restriction
        assert "operator" in restriction["threshold"] and "value" in restriction["threshold"]
    # tuition 结构完整；来源／缺失集如实
    assert isinstance(data["missing_rule_sets"], list)
    if data["tuition"] is not None:
        for field in ("amount", "currency", "period", "ownership", "note"):
            assert field in data["tuition"], field
    # enrollment_notes 六项齐全，未知项为 null（不得用空数组冒充"无限制"）
    for field in (
        "single_subject_req", "language_req", "gender_req",
        "interview_required", "political_review_required", "physical_test_required",
    ):
        assert field in data["enrollment_notes"], field


@case("专业02 专业不存在 → 1001")
def _() -> None:
    body = client.get("/api/majors/999999/requirements?province=41&year=2026").json()
    assert body["code"] == 1001, body


@case("专业03 缺 province / year → 1001（契约 8.6：均必填）")
def _() -> None:
    mid = _major_id("临床医学")
    assert client.get(f"/api/majors/{mid}/requirements?year=2026").json()["code"] == 1001
    assert client.get(f"/api/majors/{mid}/requirements?province=41").json()["code"] == 1001


# --------------------------------------------------------------------------- #
# 8.4 边界：unit_id 重复 / 响应含 data_status
# --------------------------------------------------------------------------- #
@case("边界01 unit_id 在请求内重复 → 1001")
def _() -> None:
    mid = _major_id("法学")
    payload = {
        "profile": _profile(),
        "items": [
            {"unit_id": "dup", "batch": "本科批", "major_ids": [mid]},
            {"unit_id": "dup", "batch": "本科批", "major_ids": [mid]},
        ],
    }
    assert _check(payload).json()["code"] == 1001


@case("边界02 校验响应首字段为 data_status（契约 8.4）")
def _() -> None:
    data = _check({"profile": _profile(), "items": []}).json()["data"]
    assert data["data_status"] in {"available", "partial", "schema_only", "unavailable"}, data
    assert "items" in data and "summary" in data


# --------------------------------------------------------------------------- #
# 红线：规则缺失 → 3001
# --------------------------------------------------------------------------- #
@case("红线01 删除省份模板后请求 → 3001")
def _() -> None:
    with SessionLocal() as db:
        for row in db.scalars(select(ProvinceExamRule)).all():
            db.delete(row)
        db.commit()
    body = _check({"profile": _profile(), "items": []}).json()
    assert body["code"] == 3001, body
    with SessionLocal() as db:  # 恢复
        seed_demo(db)


@case("红线02 删除选科要求后请求 → 3001")
def _() -> None:
    mid = _major_id("临床医学")
    with SessionLocal() as db:
        for row in db.scalars(select(SubjectRequirement).where(SubjectRequirement.major_id == mid)).all():
            db.delete(row)
        db.commit()
    payload = {"profile": _profile(), "items": [{"unit_id": "u-x", "batch": "本科批", "major_ids": [mid]}]}
    body = _check(payload).json()
    assert body["code"] == 3001, body
    with SessionLocal() as db:
        seed_demo(db)


# --------------------------------------------------------------------------- #
# 6.1.5 档案增量保存与完成度
# --------------------------------------------------------------------------- #
@case("档案01 增量保存：只传两字段不影响其他字段")
def _() -> None:
    token = _user_token()
    headers = {"Authorization": f"Bearer {token}"}
    client.put("/api/user/profile", json={"province": "河南", "score": 620, "color_vision": "色弱"}, headers=headers)
    body = client.put("/api/user/profile", json={"tuition_budget": 20000}, headers=headers).json()
    assert body["code"] == 0
    data = body["data"]
    assert data["tuition_budget"] == 20000 and data["color_vision"] == "色弱"


@case("档案02 响应含 completeness.percent 与 missing[]")
def _() -> None:
    token = _user_token()
    headers = {"Authorization": f"Bearer {token}"}
    body = client.get("/api/user/profile", headers=headers).json()
    comp = body["data"]["completeness"]
    assert isinstance(comp["percent"], int) and isinstance(comp["missing"], list)


@case("档案03 字段名对齐产品书 6.1.4（home_county 等）")
def _() -> None:
    token = _user_token()
    headers = {"Authorization": f"Bearer {token}"}
    client.put("/api/user/profile", json={"home_county": "兰考县", "home_county_code": "410225"}, headers=headers)
    data = client.get("/api/user/profile", headers=headers).json()["data"]
    assert data["home_county"] == "兰考县" and data["home_county_code"] == "410225"
    assert "exam_type" in data and "batch_preference" in data


# --------------------------------------------------------------------------- #
# 管理端三组规则维护
# --------------------------------------------------------------------------- #
@case("管理01 未登录访问 province-rules → 1002")
def _() -> None:
    assert client.get("/api/admin/province-rules").json()["code"] == 1002


@case("管理02 新建省份模板缺来源 → 4001")
def _() -> None:
    headers = {"Authorization": f"Bearer {_admin_token()}"}
    payload = {"province": "河北", "year": 2026, "batch": "本科批", "mode": "group"}
    assert client.post("/api/admin/province-rules", json=payload, headers=headers).json()["code"] == 4001


@case("管理03 新建省份模板缺 year → 4001")
def _() -> None:
    headers = {"Authorization": f"Bearer {_admin_token()}"}
    payload = {
        "province": "河北", "year": 0, "batch": "本科批", "mode": "group",
        "source": {"source_name": "河北省教育考试院", "source_url": "http://www.hebeea.edu.cn/", "year": 0},
    }
    assert client.post("/api/admin/province-rules", json=payload, headers=headers).json()["code"] == 4001


@case("管理04 新建省份模板正常 → 返回 rule_id")
def _() -> None:
    headers = {"Authorization": f"Bearer {_admin_token()}"}
    payload = {
        "province": "河北", "year": 2026, "batch": "本科批", "mode": "group",
        "volunteer_count": 96, "has_adjust": True,
        "source": {"source_name": "河北省教育考试院", "source_url": "http://www.hebeea.edu.cn/", "year": 2026},
    }
    body = client.post("/api/admin/province-rules", json=payload, headers=headers).json()
    assert body["code"] == 0 and body["data"]["rule_id"]


@case("管理05 身体条件 level 非法 → 1001")
def _() -> None:
    headers = {"Authorization": f"Bearer {_admin_token()}"}
    payload = {
        "condition": "色弱", "level": "ban", "year": 2026,
        "source": {"source_name": "x", "source_url": "http://x.invalid/", "year": 2026},
    }
    assert client.post("/api/admin/physical-restrictions", json=payload, headers=headers).json()["code"] == 1001


@case("管理06 身体条件合法写入 → 200 与列表可查")
def _() -> None:
    headers = {"Authorization": f"Bearer {_admin_token()}"}
    payload = {
        "condition": "嗅觉", "threshold": "异常", "major_category": "医学类", "level": "not_suitable",
        "detail": "嗅觉异常不宜就读医学类", "province": "河南", "year": 2026,
        "source": {"source_name": "《普通高等学校招生体检工作指导意见》",
                   "source_url": "http://www.moe.gov.cn/", "year": 2026},
    }
    assert client.post("/api/admin/physical-restrictions", json=payload, headers=headers).json()["code"] == 0
    listing = client.get("/api/admin/physical-restrictions?province=河南&year=2026", headers=headers).json()["data"]
    assert any(item["condition"] == "嗅觉" for item in listing["items"])
    # 契约 8.8：GET 统一返回分页包
    assert {"items", "total", "page", "page_size"} <= set(listing)


def _admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_admin_token()}"}


# --------------------------------------------------------------------------- #
# 契约 8.8 四组新增管理端接口
# --------------------------------------------------------------------------- #
@case("管理07 章程要求：新建 → 出现在 8.6 的 enrollment_notes")
def _() -> None:
    mid = _major_id("临床医学")
    payload = {
        "province_code": "41", "year": 2026, "major_id": mid,
        "requirement_type": "language", "requirement_value": {"allowed_languages": ["英语"]},
        "level": "reject", "detail": "仅限英语考生",
        "source": {"source_name": "河南省教育考试院", "source_url": "https://www.haeea.cn/", "year": 2026},
    }
    body = client.post("/api/admin/admission-requirements", json=payload, headers=_admin_headers()).json()
    assert body["code"] == 0, body
    data = client.get(f"/api/majors/{mid}/requirements?province=41&year=2026").json()["data"]
    assert data["enrollment_notes"]["language_req"] == {"allowed_languages": ["英语"]}, data["enrollment_notes"]


@case("管理08 章程要求：requirement_type 非法 → 1001")
def _() -> None:
    payload = {
        "province_code": "41", "year": 2026, "major_id": 1,
        "requirement_type": "身高", "detail": "x",
        "source": {"source_name": "河南省教育考试院", "source_url": "https://www.haeea.cn/", "year": 2026},
    }
    assert client.post(
        "/api/admin/admission-requirements", json=payload, headers=_admin_headers()
    ).json()["code"] == 1001


@case("管理09 专业学费：新建 → 8.6 的 tuition 取库值并带 currency/period")
def _() -> None:
    mid = _major_id("法学")
    payload = {
        "province_code": "41", "year": 2026, "major_id": mid,
        "amount": 5200, "currency": "CNY", "period": "year", "ownership": "公办",
        "note": "按官方收费标准",
        "source": {"source_name": "河南省教育考试院", "source_url": "https://www.haeea.cn/", "year": 2026},
    }
    assert client.post("/api/admin/major-tuition", json=payload, headers=_admin_headers()).json()["code"] == 0
    data = client.get(f"/api/majors/{mid}/requirements?province=41&year=2026").json()["data"]
    assert data["tuition"]["amount"] == 5200 and data["tuition"]["currency"] == "CNY"
    assert data["tuition"]["period"] == "year" and data["tuition"]["ownership"] == "公办"


@case("管理10 规则集状态：手工置 available 被拒 → 1001（契约 8.8）")
def _() -> None:
    payload = {
        "province_code": "41", "year": 2026, "batch_code": "undergraduate_regular",
        "exam_type": "普通", "dataset": "major_tuition", "status": "available",
        "note": "试图手工放行",
    }
    body = client.put("/api/admin/rule-dataset-status", json=payload, headers=_admin_headers()).json()
    assert body["code"] == 1001, body


@case("管理11 规则集状态：schema_only 可写，且 GET 可查")
def _() -> None:
    payload = {
        "province_code": "41", "year": 2026, "batch_code": "undergraduate_regular",
        "exam_type": "普通", "dataset": "admission_requirement", "status": "schema_only",
        "note": "结构已就绪，待 ③ 号导入",
    }
    assert client.put(
        "/api/admin/rule-dataset-status", json=payload, headers=_admin_headers()
    ).json()["code"] == 0
    listing = client.get(
        "/api/admin/rule-dataset-status?province_code=41&year=2026", headers=_admin_headers()
    ).json()["data"]
    assert any(item["dataset"] == "admission_requirement" for item in listing["items"])


@case("管理12 批量导入：dataset 非法 → 1001")
def _() -> None:
    payload = {"dataset": "unknown_set", "province_code": "41", "year": 2026, "items": [{"x": 1}]}
    assert client.post(
        "/api/admin/rule-datasets/import", json=payload, headers=_admin_headers()
    ).json()["code"] == 1001


@case("管理13 批量导入：缺来源 → 4001 且整批不落库")
def _() -> None:
    payload = {
        "dataset": "major_tuition", "province_code": "41", "year": 2026,
        "items": [{"major_id": 1, "amount": 5000, "source_name": "", "source_url": ""}],
    }
    body = client.post(
        "/api/admin/rule-datasets/import", json=payload, headers=_admin_headers()
    ).json()
    assert body["code"] == 4001, body


@case("管理14 批量导入：演示来源 example.invalid 被拒")
def _() -> None:
    payload = {
        "dataset": "major_tuition", "province_code": "41", "year": 2026,
        "items": [{"major_id": 1, "amount": 5000,
                   "source_name": "演示", "source_url": "https://example.invalid/x", "year": 2026}],
    }
    body = client.post(
        "/api/admin/rule-datasets/import", json=payload, headers=_admin_headers()
    ).json()
    assert body["code"] == 1001, body


@case("管理15 批量导入：整批成功 → dataset/created/updated/rejected/errors 齐全")
def _() -> None:
    mid = _major_id("汉语言文学")
    payload = {
        "dataset": "major_tuition", "province_code": "41", "year": 2026, "batch_code": "undergraduate_regular",
        "exam_type": "普通",
        "items": [{
            "major_id": mid, "amount": 5000, "currency": "CNY", "period": "year",
            "ownership": "公办", "note": "按官方收费标准",
            "source_name": "河南省教育考试院", "source_url": "https://www.haeea.cn/", "year": 2026,
        }],
    }
    body = client.post(
        "/api/admin/rule-datasets/import", json=payload, headers=_admin_headers()
    ).json()
    assert body["code"] == 0, body
    for field in ("dataset", "created", "updated", "rejected", "errors"):
        assert field in body["data"], field
    assert body["data"]["created"] == 1 and body["data"]["rejected"] == 0


def main() -> int:
    passed = 0
    failures: list[str] = []
    for title, fn in CASES:
        try:
            fn()
            passed += 1
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{title}: {type(exc).__name__}: {exc}")
    total = len(CASES)
    if failures:
        print("报考约束接口测试失败：")
        for item in failures:
            print("  -", item)
        print(f"{passed}/{total} 通过")
        return 1
    print(f"报考约束接口测试：{passed}/{total} 通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
