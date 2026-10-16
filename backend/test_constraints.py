"""报考约束接口测试（产品书 6.2.6–6.2.9；管理端三组规则；档案增量与完成度）。

覆盖：

- 6.2.6 省份模板：河南 48 组 / 江西 45 组 / 提前批 64 且无调剂；未知省年 → 3001
- 6.2.7 批量校验：游客可用、逐条三档、items ≤100（超限 1001）、空数组 total=0
- 6.2.8 登录校验：未登录 1002、登录返回 updated_profile
- 6.2.9 专业要求：选科 / 身体 / 学费一次取全
- **红线**：规则数据缺失 → 3001，绝不静默放行
- 6.1.5 档案增量保存与 completeness
- 管理端 province-rules / subject-requirements / physical-restrictions：缺 year 或来源 → 4001
- **v1.6 修复**：组级多口径（跨科类/跨批次）导入共存并按考生首选选择；
  体检类级匹配走「专业代码前 4 位 → 专业类名」（门类 ≠ 专业类）；
  跨数据集年份对齐（data_years / partial / 绝不借用目标年份之后的数据）

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
from sqlalchemy import func, select  # noqa: E402

from app.db.session import SessionLocal, create_all  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base_data import Major, School  # noqa: E402
from app.models.constants import DATASET_SUBJECT_REQUIREMENT  # noqa: E402
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


@case("闸门③ 色弱规则仅应用于命中的专业类")
def _() -> None:
    data = _check({
        "profile": _profile(color_vision="色弱"),
        "items": [{"unit_id": "unrelated", "batch": "本科批", "major_ids": [_major_id("法学")]}],
    }).json()["data"]
    hits = [hit for hit in data["items"][0]["blockers"] + data["items"][0]["warnings"] if hit["type"] == "physical"]
    assert hits == [], hits


@case("闸门③ 体检规则经管理端导入后按专业类判定并回传来源")
def _() -> None:
    import importlib.util
    import json

    builder_path = Path(__file__).resolve().parents[1] / "data/scripts/build_physical_restriction_import.py"
    spec = importlib.util.spec_from_file_location("t6_physical_builder", builder_path)
    assert spec and spec.loader
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    dictionary = json.loads(builder.DICT_PATH.read_text(encoding="utf-8"))
    generated, _skipped, _need_engine, _counts = builder.build_items(dictionary, builder.load_menlei_map())
    with SessionLocal() as db:
        categories = set(db.scalars(select(Major.category).where(Major.category != "")).all())
    rule = next(item for item in generated
                if item["condition"] == "色弱" and item["major_category"] in categories
                and item["level"] == "reject")
    with SessionLocal() as db:
        target_major_id = db.scalar(select(Major.id).where(Major.category == rule["major_category"]).limit(1))
    assert target_major_id is not None, rule
    payload = {
        "dataset": "physical_restriction", "province_code": "41", "year": 2026,
        "batch_code": "undergraduate_regular", "exam_type": "普通",
        "items": [rule],
    }
    imported = client.post("/api/admin/rule-datasets/import", json=payload, headers=_admin_headers()).json()
    assert imported["code"] == 0 and imported["data"]["created"] == 1, imported
    checked = _check({
        "profile": _profile(color_vision="色弱"),
        "items": [{"unit_id": "physical-import", "batch": "本科批", "major_ids": [target_major_id]}],
    }).json()
    assert checked["code"] == 0, checked
    hits = [hit for hit in checked["data"]["items"][0]["blockers"] if hit["type"] == "physical"]
    assert len(hits) == 1 and hits[0]["citation"]["source_name"] == rule["source_name"], hits
    assert hits[0]["citation"]["year"] == 2026, hits


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


@case("校验03a 空串/未填/未知数值哨兵归一为未填并进入 unknown")
def _() -> None:
    response = _check({
        "profile": _profile(color_vision="未知", vision_left="未填", vision_right="", height="未知"),
        "items": [{"unit_id": "sentinels", "batch": "本科批", "major_ids": [_major_id("临床医学")]}],
    }).json()
    assert response["code"] == 0, response
    item = response["data"]["items"][0]
    assert item["eligible"] is None and item["unknowns"], item


@case("校验03b summary 各计数互相独立（单位可同时计入 warned 与 unknown）")
def _() -> None:
    # 临床医学同时覆盖可用体检规则，验证目标级分类过滤后仍可与学费 warning 并存。
    payload = {
        "profile": _profile(color_vision=None, vision_left=None, vision_right=None, tuition_budget=100),
        "items": [{"unit_id": "u-3b", "batch": "本科批",
                   "major_ids": [_major_id("临床医学")]}],
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


@case("闸门② 专业组代码精确命中组级选科规则")
def _() -> None:
    with SessionLocal() as db:
        school = db.scalar(select(School).limit(1))
        if school is None:
            school = School(name="T6 组级测试院校", province="河南")
            db.add(school)
            db.flush()
        school_id = school.id
        major = Major(name="T6 组级测试专业", code="T6-GROUP-MAJOR", category="医学类")
        db.add(major)
        db.flush()
        db.commit()
        major_id = major.id
    import_payload = {
        "dataset": "subject_requirement", "province_code": "41", "year": 2026,
        "batch_code": "undergraduate_regular", "exam_type": "普通",
        "items": [{
            "province_code": "41", "province": "河南", "year": 2026, "batch": "本科批",
            "school_id": school_id, "group_code": "T6-GROUP-01", "major_id": None,
            "first_subject": "历史", "secondary_subjects": [], "logic": "all",
            "source_name": "河南省教育考试院", "source_url": "https://www.haeea.cn/",
        }],
    }
    imported = client.post("/api/admin/rule-datasets/import", json=import_payload, headers=_admin_headers()).json()
    assert imported["code"] == 0 and imported["data"]["created"] == 1, imported
    duplicate = client.post("/api/admin/rule-datasets/import", json=import_payload, headers=_admin_headers()).json()
    assert duplicate["code"] == 1001 and "逻辑键已存在" in duplicate["message"], duplicate
    body = _check({
        "profile": _profile(),
        "items": [{"unit_id": "group-hit", "batch": "本科批", "school_id": school_id,
                   "group_code": "T6-GROUP-01", "major_ids": [major_id]}],
    }).json()
    assert body["code"] == 0, body
    item = body["data"]["items"][0]
    assert item["eligible"] is False and any("首选科目" in hit["detail"] for hit in item["blockers"]), item


@case("闸门② 混合批次任一专业规则缺失则整批 3001 且定位目标")
def _() -> None:
    body = _check({
        "profile": _profile(),
        "items": [
            {"unit_id": "known", "batch": "本科批", "major_ids": [_major_id("临床医学")]},
            {"unit_id": "missing", "batch": "本科批", "major_ids": [999999]},
        ],
    }).json()
    assert body["code"] == 3001, body
    assert "data" in body and "items" not in (body.get("data") or {}), body
    assert "unit_id=missing" in body["message"] and "major_id=999999" in body["message"], body


@case("闸门② 目标年份 2025 无任何可得规则 → 3001（不借用 2026 数据）")
def _() -> None:
    body = _check({
        "profile": _profile(year=2025),
        "items": [{"unit_id": "old-year", "batch": "本科批", "major_ids": [_major_id("临床医学")]}],
    }).json()
    assert body["code"] == 3001, body
    assert "2025" in body["message"], body
    # 各规则集在 2025 及以前均无数据 → data_years 全为 null（绝不把 2026 数据标成 2025）
    assert set(body["data"]["data_years"].values()) == {None}, body["data"]["data_years"]


@case("闸门② 河南专业规则不能跨省回退给江西")
def _() -> None:
    with SessionLocal() as db:
        source_id = db.scalar(select(SubjectRequirement.source_id).limit(1))
        assert source_id
        major = Major(name="T6 跨省隔离测试专业", code="T6-PROVINCE-ISOLATION", category="医学类")
        db.add(major)
        db.flush()
        db.add(SubjectRequirement(
            province_code="41", province="河南", year=2026, batch="本科批",
            major_id=major.id, first_subject="物理", secondary_subjects=["化学"],
            logic="all", source_id=source_id,
        ))
        db.commit()
        major_id = major.id
    body = _check({
        "profile": _profile(province="江西"),
        "items": [{"unit_id": "province-isolation", "batch": "本科批", "major_ids": [major_id]}],
    }).json()
    assert body["code"] == 3001, body
    assert "unit_id=province-isolation" in body["message"], body


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
    assert "unit_id=u-x" in body["message"] and "major_id=" in body["message"], body
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


@case("管理16 规则批量导入来源不完整时整批回滚")
def _() -> None:
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(SubjectRequirement).where(
            SubjectRequirement.province_code == "41", SubjectRequirement.year == 2026,
            SubjectRequirement.group_code == "T6-ROLLBACK",
        )) or 0
    payload = {
        "dataset": "subject_requirement", "province_code": "41", "year": 2026,
        "batch_code": "undergraduate_regular", "exam_type": "普通",
        "items": [
            {"group_code": "T6-ROLLBACK", "first_subject": "物理", "logic": "all",
             "source_name": "河南省教育考试院", "source_url": "https://www.haeea.cn/", "year": 2026},
            {"group_code": "T6-ROLLBACK-INVALID", "first_subject": "历史", "logic": "all",
             "source_name": "", "source_url": "", "year": 2026},
        ],
    }
    body = client.post("/api/admin/rule-datasets/import", json=payload, headers=_admin_headers()).json()
    assert body["code"] == 4001, body
    with SessionLocal() as db:
        after = db.scalar(select(func.count()).select_from(SubjectRequirement).where(
            SubjectRequirement.province_code == "41", SubjectRequirement.year == 2026,
            SubjectRequirement.group_code.like("T6-ROLLBACK%"),
        )) or 0
    assert after == before, (before, after)


# --------------------------------------------------------------------------- #
# v1.6 修复：组级多口径（跨科类 / 跨批次）—— 真实招生计划表口径
# 河南按科类（历史类/物理类）独立编组号：同一「校+组号」在不同科类/批次下
# 是不同专业组，各自是独立规则行，导入不得误判为重复。
# --------------------------------------------------------------------------- #
def _school_id() -> int:
    with SessionLocal() as db:
        school = db.scalar(select(School).limit(1))
        assert school is not None, "演示院校缺失"
        return school.id


@case("闸门② 同组多科类变体：导入共存 + 按考生首选选择（河南口径）")
def _() -> None:
    school_id = _school_id()
    base = {
        "province_code": "41", "province": "河南", "year": 2026, "batch": "本科批",
        "school_id": school_id, "group_code": "T6-VARIANT",
        "source_name": "河南省教育考试院", "source_url": "https://www.haeea.cn/", "year": 2026,
    }
    payload = {
        "dataset": "subject_requirement", "province_code": "41", "year": 2026,
        "batch_code": "undergraduate_regular", "exam_type": "普通",
        "items": [
            {**base, "first_subject": "历史", "secondary_subjects": ["思想政治"], "logic": "all"},
            {**base, "first_subject": "物理", "secondary_subjects": ["化学"], "logic": "all"},
        ],
    }
    imported = client.post("/api/admin/rule-datasets/import", json=payload, headers=_admin_headers()).json()
    assert imported["code"] == 0 and imported["data"]["created"] == 2, imported
    duplicate = client.post("/api/admin/rule-datasets/import", json=payload, headers=_admin_headers()).json()
    assert duplicate["code"] == 1001 and "逻辑键已存在" in duplicate["message"], duplicate

    unit = {"unit_id": "variant-unit", "batch": "本科批", "school_id": school_id, "group_code": "T6-VARIANT"}

    # 物理考生 → 只取「物理」变体（再选化学必选 → 缺化学被拦）；不得被「历史」变体的首选要求误拦
    phys = _check({"profile": _profile(second_subjects=["思想政治"]), "items": [unit]}).json()
    assert phys["code"] == 0, phys
    phys_blockers = phys["data"]["items"][0]["blockers"]
    assert any("化学" in hit["detail"] for hit in phys_blockers), phys_blockers
    assert not any("首选科目" in hit["detail"] for hit in phys_blockers), phys_blockers

    # 历史考生 → 只取「历史」变体（再选政治已满足 → 选科零命中）
    hist = _check({"profile": _profile(first_subject="历史", second_subjects=["思想政治"]), "items": [unit]}).json()
    assert hist["code"] == 0, hist
    hist_item = hist["data"]["items"][0]
    assert not any(
        hit["type"] == "subject" for hit in hist_item["blockers"] + hist_item["warnings"] + hist_item["unknowns"]
    ), hist_item


@case("闸门② 同组跨批次独立规则（导入身份含批次 → 共存且防重）")
def _() -> None:
    school_id = _school_id()
    base = {
        "province_code": "41", "province": "河南", "year": 2026,
        "school_id": school_id, "group_code": "T6-BATCH",
        "first_subject": "物理", "secondary_subjects": [], "logic": "all",
        "source_name": "河南省教育考试院", "source_url": "https://www.haeea.cn/", "year": 2026,
    }
    payload = {
        "dataset": "subject_requirement", "province_code": "41", "year": 2026,
        "batch_code": "undergraduate_regular", "exam_type": "普通",
        "items": [
            {**base, "batch": "本科批"},
            {**base, "batch": "专科批"},
        ],
    }
    imported = client.post("/api/admin/rule-datasets/import", json=payload, headers=_admin_headers()).json()
    assert imported["code"] == 0 and imported["data"]["created"] == 2, imported
    duplicate = client.post("/api/admin/rule-datasets/import", json=payload, headers=_admin_headers()).json()
    assert duplicate["code"] == 1001, duplicate


@case("闸门③ 类级体检规则按「专业代码前 4 位 → 专业类名」匹配（真实库口径）")
def _() -> None:
    with SessionLocal() as db:
        db.add(Major(name="药学类", code="1007", category="医学", is_category=True))
        target = Major(name="T6 药学测试专业", code="100701", category="医学")
        sibling = Major(name="T6 中药学测试专业", code="100801", category="医学")
        db.add(target)
        db.add(sibling)
        db.flush()
        target_id, sibling_id = target.id, sibling.id
        db.commit()

    # 先给两个合成专业补选科规则（闸门②放行后才能观察到闸门③），
    # 顺便用「只有体检规则、没有选科规则」的目标验证 3001 也带 data_years。
    missing_rule = _check({
        "profile": _profile(color_vision="色弱"),
        "items": [{"unit_id": "no-subject-rule", "batch": "本科批", "major_ids": [target_id]}],
    }).json()
    assert missing_rule["code"] == 3001, missing_rule
    assert set(missing_rule["data"]) == {"data_status", "missing_rule_sets", "data_years"}, missing_rule["data"]
    assert set(missing_rule["data"]["data_years"]) == {
        "province_exam_rule", "subject_requirement", "physical_restriction",
        "major_tuition", "admission_requirement",
    }, missing_rule["data"]["data_years"]

    subject_payload = {
        "dataset": "subject_requirement", "province_code": "41", "year": 2026,
        "batch_code": "undergraduate_regular", "exam_type": "普通",
        "items": [
            {"province": "河南", "batch": "本科批", "major_id": mid,
             "first_subject": "物理", "secondary_subjects": [], "logic": "all",
             "source_name": "河南省教育考试院", "source_url": "https://www.haeea.cn/", "year": 2026}
            for mid in (target_id, sibling_id)
        ],
    }
    imported_s = client.post(
        "/api/admin/rule-datasets/import", json=subject_payload, headers=_admin_headers()
    ).json()
    assert imported_s["code"] == 0 and imported_s["data"]["created"] == 2, imported_s

    payload = {
        "dataset": "physical_restriction", "province_code": "41", "year": 2026,
        "batch_code": "undergraduate_regular", "exam_type": "普通",
        "items": [{
            "condition": "色弱", "threshold": "", "major_category": "药学类", "major_code": "",
            "level": "reject", "detail": "色弱不能录取药学类专业（测试）", "province": "河南", "year": 2026,
            "source_name": "《普通高等学校招生体检工作指导意见》", "source_url": "http://www.moe.gov.cn/",
        }],
    }
    imported = client.post("/api/admin/rule-datasets/import", json=payload, headers=_admin_headers()).json()
    assert imported["code"] == 0 and imported["data"]["created"] == 1, imported

    # 100701（药学）→ 1007 药学类：命中，且回传来源
    hit = _check({
        "profile": _profile(color_vision="色弱"),
        "items": [{"unit_id": "class-hit", "batch": "本科批", "major_ids": [target_id]}],
    }).json()
    blockers = [h for h in hit["data"]["items"][0]["blockers"] if h["type"] == "physical"]
    assert blockers and any("药学" in h["detail"] for h in blockers), blockers
    assert blockers[0]["citation"]["source_name"], blockers

    # 100801（中药学）→ 1008 中药学类：不得被「药学类」规则误伤（不做任何扩展匹配）
    other = _check({
        "profile": _profile(color_vision="色弱"),
        "items": [{"unit_id": "class-other", "batch": "本科批", "major_ids": [sibling_id]}],
    }).json()
    other_item = other["data"]["items"][0]
    assert not any(
        h["type"] == "physical" for h in other_item["blockers"] + other_item["warnings"]
    ), other_item


@case("边界03 校验响应含 data_years（各规则集实际数据年度）")
def _() -> None:
    data = _check({"profile": _profile(), "items": []}).json()["data"]
    years = data.get("data_years")
    assert isinstance(years, dict), data
    for dataset in (
        "province_exam_rule", "subject_requirement", "physical_restriction",
        "major_tuition", "admission_requirement",
    ):
        assert dataset in years, dataset
    assert years["province_exam_rule"] == 2026 and years["subject_requirement"] == 2026


# --------------------------------------------------------------------------- #
# v1.6 修复：跨数据集年份对齐（选科滞后一年可用并如实标注；绝不借用未来数据）
# --------------------------------------------------------------------------- #
def _snapshot_subject_2026() -> tuple[list[dict[str, Any]], int | None]:
    """移走 2026 全部选科行（返回快照与任一来源 id），供年份对齐用例使用。"""
    with SessionLocal() as db:
        stale = db.scalars(select(SubjectRequirement).where(SubjectRequirement.year == 2026)).all()
        snapshot = [
            {
                "province_code": row.province_code, "province": row.province, "batch": row.batch,
                "school_id": row.school_id, "group_code": row.group_code, "major_id": row.major_id,
                "first_subject": row.first_subject, "secondary_subjects": list(row.secondary_subjects or []),
                "logic": row.logic, "year": row.year, "source_id": row.source_id,
            }
            for row in stale
        ]
        source_id = snapshot[0]["source_id"] if snapshot else None
        for row in stale:
            db.delete(row)
        db.commit()
    return snapshot, source_id


def _restore_subject(snapshot: list[dict[str, Any]], extra_years: tuple[int, ...] = ()) -> None:
    with SessionLocal() as db:
        for year in extra_years:
            for row in db.scalars(select(SubjectRequirement).where(SubjectRequirement.year == year)).all():
                db.delete(row)
        for row in snapshot:
            db.add(SubjectRequirement(**row))
        db.commit()


@case("跨数据集年份对齐：选科滞后一年按最近可得年度取数并标注（partial）")
def _() -> None:
    mid = _major_id("法学")
    snapshot, source_id = _snapshot_subject_2026()
    with SessionLocal() as db:
        db.add(SubjectRequirement(
            province_code="41", province="河南", year=2025, batch="本科批",
            major_id=mid, first_subject="物理", secondary_subjects=["化学"],
            logic="all", source_id=source_id,
        ))
        db.commit()
    try:
        body = _check({
            "profile": _profile(),
            "items": [{"unit_id": "y2026", "batch": "本科批", "major_ids": [mid]}],
        }).json()
        assert body["code"] == 0, body
        data = body["data"]
        assert data["data_years"]["subject_requirement"] == 2025, data["data_years"]
        assert data["data_years"]["province_exam_rule"] == 2026, data["data_years"]
        assert data["data_status"] == "partial", data["data_status"]
        item = data["items"][0]
        assert not any(hit["type"] == "subject" for hit in item["blockers"]), item
        # 选科（2025 年度）、体检、学费、省份规则四闸门全过 → eligible=True
        assert item["eligible"] is True, item
    finally:
        _restore_subject(snapshot, extra_years=(2025,))


@case("跨数据集年份对齐：目标年份之后的数据不借用（3001）")
def _() -> None:
    mid = _major_id("法学")
    snapshot, source_id = _snapshot_subject_2026()
    with SessionLocal() as db:
        db.add(SubjectRequirement(
            province_code="41", province="河南", year=2027, batch="本科批",
            major_id=mid, first_subject="物理", secondary_subjects=["化学"],
            logic="all", source_id=source_id,
        ))
        db.commit()
    try:
        body = _check({
            "profile": _profile(),
            "items": [{"unit_id": "y-future", "batch": "本科批", "major_ids": [mid]}],
        }).json()
        assert body["code"] == 3001, body
        assert DATASET_SUBJECT_REQUIREMENT in body["data"]["missing_rule_sets"], body
        assert body["data"]["data_years"][DATASET_SUBJECT_REQUIREMENT] is None, body
    finally:
        _restore_subject(snapshot, extra_years=(2027,))


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
