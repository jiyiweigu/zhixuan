"""院校检索、画像与并排对比测试（tasks.md 7.1、7.2；产品书 6.5.1–6.5.7）。

覆盖 7.1 的验收条件「组合条件筛选结果正确」与 7.2 的「各类信息按来源展示」，并补齐边界：
- 单条件 / 组合条件筛选结果数正确，无结果时返回空但 total 为 0；
- 分页包形状固定，翻页不重不漏，越界页空 items 但 total 不变，非法参数 1001；
- 列表每项带来源三要素（契约第 6 节的逐项溯源要求）；
- 详情含 website / intro 与来源清单；不存在 → 1001；
- 画像字段齐全、``source_note`` 必填非空、``campus_list`` 为 {name,address,city} 对象数组；
  无画像数据时 available=False 而非报错；
- 生活信息按 category 过滤、每条带可靠性标注与非官方/官方区分；
- 专业检索与详情；6.5.7 暂无来源的字段如实为空并在 data_status 说明；
- 院校并排对比（6.5.5）：按入参顺序、去重、指标与画像一致、无画像如实留空并记 missing、
  非正 id / 空数组 / 超 5 校 / 不存在的院校一律 1001；
- 演示数据入库幂等。

纯脚本，无 pytest 依赖，直接运行：
    cd backend && .venv\\Scripts\\python.exe test_schools.py
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

# 环境变量必须在导入 app.* 之前设置：settings 在首次导入时读取一次
_WORK = Path(tempfile.mkdtemp(prefix="zhixuan_school_test_"))
os.environ["ZHIXUAN_DATABASE_URL"] = f"sqlite:///{(_WORK / 'school.db').as_posix()}"
os.environ["ZHIXUAN_SECRET_KEY"] = "test-secret-key-school-suite-at-least-32-bytes"
os.environ["ZHIXUAN_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import update  # noqa: E402

from app.core import dataset  # noqa: E402
from app.db.session import SessionLocal, create_all  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base_data import School  # noqa: E402
from app.services.school_seed import seed_demo  # noqa: E402

create_all()
with SessionLocal() as _db:
    SEEDED = seed_demo(_db)

client = TestClient(app)
logging.getLogger("zhixuan").setLevel(logging.CRITICAL)

PAGINATION_KEYS = {"items", "total", "page", "page_size"}

# 并排对比中「可能缺失」的画像指标（与 app/services/schools.py 的 PROFILE_METRICS 对应）
PROFILE_METRIC_FIELDS = {
    "tuition_range",
    "accommodation_fee",
    "campus_count",
    "established_year",
    "master_phd_points",
    "first_class_major_count",
    "faculty_count",
    "student_faculty_ratio",
}

# 演示数据集的既定规模（与 app/data/schools/schools_demo.json 对应）
TOTAL_SCHOOLS = 8
HENAN_SCHOOLS = 6
HUBEI_SCHOOLS = 2
TOTAL_MAJORS = 8

CASES: list[tuple[str, Callable[[], None]]] = []


def case(title: str) -> Callable:
    def decorator(func: Callable[[], None]) -> Callable[[], None]:
        CASES.append((title, func))
        return func

    return decorator


# --------------------------------------------------------------------------- #
# 辅助
# --------------------------------------------------------------------------- #
def get(path: str, **params) -> dict:
    resp = client.get(path, params=params)
    assert resp.status_code == 200, (path, resp.text)
    return resp.json()


def data(path: str, **params) -> dict:
    body = get(path, **params)
    assert body["code"] == 0, (path, params, body)
    return body["data"]


def error_code(path: str, **params) -> int:
    return get(path, **params)["code"]


def post(path: str, payload: dict) -> dict:
    resp = client.post(path, json=payload)
    assert resp.status_code == 200, (path, resp.text)
    return resp.json()


def post_data(path: str, payload: dict) -> dict:
    body = post(path, payload)
    assert body["code"] == 0, (path, payload, body)
    return body["data"]


def post_error_code(path: str, payload: dict) -> int:
    return post(path, payload)["code"]


def school_id_by_name(name: str) -> int:
    items = data("/api/schools", keyword=name)["items"]
    matched = [item for item in items if item["name"] == name]
    assert matched, f"演示数据中找不到院校：{name}"
    return matched[0]["school_id"]


def major_id_by_name(name: str) -> int:
    items = data("/api/majors", keyword=name)["items"]
    matched = [item for item in items if item["name"] == name]
    assert matched, f"演示数据中找不到专业：{name}"
    return matched[0]["major_id"]


# --------------------------------------------------------------------------- #
# 演示数据集
# --------------------------------------------------------------------------- #
@case("01 演示数据集通过来源与引用完整性校验")
def _() -> None:
    payload = dataset.load_schools_demo()
    for key in ("sources", "schools", "majors", "scores", "profiles", "life"):
        assert payload.get(key), f"演示数据集缺少 {key}"
    for item in payload["sources"]:
        for field in ("source_name", "source_url", "year"):
            assert item.get(field), f"来源 {item.get('key')} 缺少 {field}"


@case("02 演示数据入库幂等：重复执行不新增行")
def _() -> None:
    assert all(count >= 0 for count in SEEDED.values())
    assert SEEDED["school"] == TOTAL_SCHOOLS, SEEDED
    assert SEEDED["major"] == TOTAL_MAJORS, SEEDED
    with SessionLocal() as db:
        again = seed_demo(db)
    assert set(again.values()) == {0}, f"重复入库产生了新行：{again}"


# --------------------------------------------------------------------------- #
# 检索：单条件与组合条件（tasks.md 7.1 验收）
# --------------------------------------------------------------------------- #
@case("03 无参检索返回全部院校并分页")
def _() -> None:
    result = data("/api/schools")
    assert result["total"] == TOTAL_SCHOOLS, result["total"]
    assert len(result["items"]) == TOTAL_SCHOOLS


@case("04 单条件：按省份过滤")
def _() -> None:
    assert data("/api/schools", province="河南")["total"] == HENAN_SCHOOLS
    assert data("/api/schools", province="湖北")["total"] == HUBEI_SCHOOLS
    assert data("/api/schools", province="西藏")["total"] == 0


@case("05 单条件：按办学层次过滤")
def _() -> None:
    assert data("/api/schools", level="本科")["total"] == TOTAL_SCHOOLS - 1
    assert data("/api/schools", level="专科")["total"] == 1


@case("06 单条件：按院校类型与办学性质过滤")
def _() -> None:
    assert data("/api/schools", type="理工")["total"] == 4
    assert data("/api/schools", type="综合")["total"] == 4
    assert data("/api/schools", ownership="公办")["total"] == TOTAL_SCHOOLS
    assert data("/api/schools", ownership="民办")["total"] == 0


@case("07 组合条件：省份 + 层次，取交集而非并集")
def _() -> None:
    result = data("/api/schools", province="河南", level="本科")
    assert result["total"] == 5, result["total"]


@case("08 组合条件：省份 + 类型 + 层次三条件叠加")
def _() -> None:
    assert data("/api/schools", province="河南", type="理工")["total"] == 4
    assert data("/api/schools", province="河南", type="理工", level="本科")["total"] == 3


@case("09 关键词分别命中名称、城市与简介")
def _() -> None:
    assert data("/api/schools", keyword="河南大学")["total"] == 1, "命中名称"
    assert data("/api/schools", keyword="开封")["total"] == 1, "命中城市"
    assert data("/api/schools", keyword="水利")["total"] >= 1, "命中简介"


@case("10 组合条件无匹配时返回空列表且 total 为 0，不报错")
def _() -> None:
    result = data("/api/schools", province="河南", type="师范")
    assert result["items"] == []
    assert result["total"] == 0


@case("11 关键词与省市条件同时生效")
def _() -> None:
    items = data("/api/schools", province="河南", keyword="轻工业")["items"]
    assert [item["name"] for item in items] == ["郑州轻工业大学"]


# --------------------------------------------------------------------------- #
# 分页边界
# --------------------------------------------------------------------------- #
@case("12 分页包形状固定为 items/total/page/page_size")
def _() -> None:
    result = data("/api/schools", page_size=3)
    assert set(result) == PAGINATION_KEYS, sorted(result)


@case("13 翻页不重不漏，末页条数正确")
def _() -> None:
    first = data("/api/schools", page=1, page_size=3)
    second = data("/api/schools", page=2, page_size=3)
    third = data("/api/schools", page=3, page_size=3)
    assert (len(first["items"]), len(second["items"]), len(third["items"])) == (3, 3, 2)
    ids = [item["school_id"] for item in first["items"] + second["items"] + third["items"]]
    assert len(ids) == len(set(ids)) == TOTAL_SCHOOLS, ids
    for page_result in (first, second, third):
        assert page_result["total"] == TOTAL_SCHOOLS, "翻页不改变 total"


@case("14 越界页码返回空 items，但 total 不变")
def _() -> None:
    result = data("/api/schools", page=99, page_size=20)
    assert result["items"] == []
    assert result["total"] == TOTAL_SCHOOLS
    assert result["page"] == 99


@case("15 非法分页参数返回 1001")
def _() -> None:
    assert error_code("/api/schools", page=0) == 1001
    assert error_code("/api/schools", page_size=0) == 1001
    assert error_code("/api/schools", page_size=101) == 1001
    assert error_code("/api/schools", page="abc") == 1001


# --------------------------------------------------------------------------- #
# 来源可追溯（契约第 6 节）
# --------------------------------------------------------------------------- #
@case("16 列表每项都带来源三要素")
def _() -> None:
    for item in data("/api/schools")["items"]:
        assert item["citations"], f"{item['name']} 缺少 citations"
        for citation in item["citations"]:
            for field in ("source_name", "source_url", "year"):
                assert citation.get(field), f"{item['name']} 的来源缺少 {field}"


@case("17 列表项字段与产品书 6.5.1 一致")
def _() -> None:
    item = data("/api/schools", keyword="郑州大学")["items"][0]
    for field in ("school_id", "name", "code", "province", "city", "level", "type", "ownership"):
        assert field in item, field
    assert item["name"] == "郑州大学"
    assert item["province"] == "河南"


# --------------------------------------------------------------------------- #
# 详情（6.5.2）
# --------------------------------------------------------------------------- #
@case("18 院校详情含概况、简介与来源清单")
def _() -> None:
    detail = data(f"/api/schools/{school_id_by_name('郑州大学')}")
    assert detail["name"] == "郑州大学"
    assert detail["website"].startswith("http")
    assert "双一流" in detail["intro"]
    assert detail["sources"], "详情缺少来源清单（产品书 6.5.2 的 sources[]）"


@case("19 详情来源覆盖录取分与画像两类来源")
def _() -> None:
    detail = data(f"/api/schools/{school_id_by_name('郑州大学')}")
    names = {citation["source_name"] for citation in detail["sources"]}
    assert any("教育考试院" in name for name in names), names
    assert any("招生网" in name for name in names), names


@case("20 院校不存在返回 1001")
def _() -> None:
    assert error_code("/api/schools/999999") == 1001
    assert error_code("/api/schools/999999/profile") == 1001
    assert error_code("/api/schools/999999/life") == 1001


# --------------------------------------------------------------------------- #
# 画像（tasks.md 7.2）
# --------------------------------------------------------------------------- #
@case("21 画像字段齐全，source_note 必填非空")
def _() -> None:
    profile = data(f"/api/schools/{school_id_by_name('郑州大学')}/profile")
    assert profile["available"] is True
    assert profile["source_note"], "source_note 必须非空（产品书 6.5.3）"
    assert "郑州大学本科招生网" in profile["source_note"]
    assert profile["tuition_range"]
    assert isinstance(profile["faculty_count"], int) and profile["faculty_count"] > 0
    assert isinstance(profile["first_class_major_count"], int)
    assert profile["established_year"] == 1956
    assert profile["student_faculty_ratio"]
    assert profile["master_phd_points"] == {"master": 60, "phd": 31}, "产品书 6.5.3 定为对象"
    assert profile["citations"], "画像缺少来源"


@case("22 campus_list 为 {name, address, city} 对象数组")
def _() -> None:
    profile = data(f"/api/schools/{school_id_by_name('河南大学')}/profile")
    campuses = profile["campus_list"]
    assert len(campuses) == 3, campuses
    for campus in campuses:
        assert set(campus) == {"name", "address", "city"}, campus
        assert all(campus.values()), campus


@case("23 暂无画像数据时返回 available=False 的空态而非报错")
def _() -> None:
    profile = data(f"/api/schools/{school_id_by_name('河南工业大学')}/profile")
    assert profile["available"] is False
    assert profile["source_note"] == ""
    assert profile["campus_list"] == []
    assert profile["data_status"], "空态需要说明原因"
    assert profile["citations"] == []


# --------------------------------------------------------------------------- #
# 生活信息（tasks.md 7.3；6.5.4）
# --------------------------------------------------------------------------- #
@case("24 生活信息按分类返回，并给出分类总集")
def _() -> None:
    life = data(f"/api/schools/{school_id_by_name('郑州大学')}/life")
    assert life["total"] == 2, life
    assert set(life["categories"]) == {"宿舍", "食堂"}, life["categories"]
    categories = {item["category"] for item in life["items"]}
    assert categories == {"宿舍", "食堂"}


@case("25 按 category 过滤后 items 收敛，但 categories 仍为全集")
def _() -> None:
    life = data(f"/api/schools/{school_id_by_name('郑州大学')}/life", category="宿舍")
    assert life["total"] == 1
    assert life["items"][0]["category"] == "宿舍"
    assert set(life["categories"]) == {"宿舍", "食堂"}, "分类总集不随过滤变化"


@case("26 每条生活信息都带来源三要素与可靠性标注")
def _() -> None:
    life = data(f"/api/schools/{school_id_by_name('郑州大学')}/life")
    reliabilities = set()
    for item in life["items"]:
        for field in ("source_name", "source_url", "year", "source_type"):
            assert item.get(field) is not None, (item, field)
        assert item["reliability"] in {"official", "unofficial"}, item
        assert item["content"], "生活信息内容不得为空"
        reliabilities.add(item["reliability"])
    assert reliabilities == {"official", "unofficial"}, "演示数据应同时覆盖官方与非官方"


@case("27 官方与非官方来源按 source_type 区分，供前端默认折叠")
def _() -> None:
    life = data(f"/api/schools/{school_id_by_name('郑州大学')}/life")
    by_category = {item["category"]: item for item in life["items"]}
    assert by_category["宿舍"]["reliability"] == "official"
    assert by_category["宿舍"]["source_type"] == "official"
    assert by_category["食堂"]["reliability"] == "unofficial"
    assert by_category["食堂"]["source_type"] != "official"


@case("28 无生活信息的院校返回空 items")
def _() -> None:
    life = data(f"/api/schools/{school_id_by_name('华中科技大学')}/life")
    assert life["items"] == []
    assert life["total"] == 0
    assert life["categories"] == []


@case("29 不存在的分类过滤返回空 items，不报错")
def _() -> None:
    life = data(f"/api/schools/{school_id_by_name('郑州大学')}/life", category="校园环境")
    assert life["items"] == []
    assert life["total"] == 0


# --------------------------------------------------------------------------- #
# 专业检索与详情（6.5.6、6.5.7）
# --------------------------------------------------------------------------- #
@case("30 专业检索：无参返回全部，按门类过滤")
def _() -> None:
    assert data("/api/majors")["total"] == TOTAL_MAJORS
    assert data("/api/majors", category="工学")["total"] == 4
    assert data("/api/majors", category="经济学")["total"] == 1
    assert data("/api/majors", category="军事学")["total"] == 0


@case("31 专业检索：关键词命中名称与专业代码")
def _() -> None:
    names = [item["name"] for item in data("/api/majors", keyword="土木")["items"]]
    assert names == ["土木工程"], names
    codes = [item["code"] for item in data("/api/majors", keyword="0809")["items"]]
    assert codes == ["080901", "080902"], codes


@case("32 专业检索：组合条件与分页")
def _() -> None:
    result = data("/api/majors", category="工学", keyword="工程")
    assert result["total"] == 3, result["total"]
    paged = data("/api/majors", page=1, page_size=3)
    assert set(paged) == PAGINATION_KEYS
    assert len(paged["items"]) == 3 and paged["total"] == TOTAL_MAJORS


@case("33 专业列表项字段与产品书 6.5.6 一致")
def _() -> None:
    item = data("/api/majors", keyword="计算机")["items"][0]
    for field in ("major_id", "name", "code", "category", "degree"):
        assert field in item, field
    assert item["name"] == "计算机科学与技术"
    assert item["category"] == "工学"


@case("34 专业详情：实有字段齐全，无来源字段如实为空并说明")
def _() -> None:
    detail = data(f"/api/majors/{major_id_by_name('计算机科学与技术')}")
    assert detail["name"] == "计算机科学与技术"
    assert detail["code"] == "080901"
    assert detail["degree"] == "工学学士"
    assert detail["first_class"].startswith("国家级")
    assert detail["intro"] == "", "第 7 章 major 表无 intro 列，不得编造"
    assert detail["first_class_schools"] == [], "无对应数据来源，不得编造"
    assert detail["data_status"], "需说明字段缺失原因"


@case("35 专业不存在返回 1001")
def _() -> None:
    assert error_code("/api/majors/999999") == 1001


# --------------------------------------------------------------------------- #
# 并排对比（产品书 6.5.5）
# --------------------------------------------------------------------------- #
@case("36 两校并排：行数、顺序与字段齐全")
def _() -> None:
    zzu = school_id_by_name("郑州大学")
    henu = school_id_by_name("河南大学")
    result = post_data("/api/schools/compare", {"school_ids": [henu, zzu]})
    assert [item["school_id"] for item in result["items"]] == [henu, zzu], "顺序应与入参一致"
    assert result["count"] == 2
    assert result["max_compare"] == 5
    for item in result["items"]:
        for field in (
            "school_id", "name", "code", "province", "city", "level", "type", "ownership",
            "tuition_range", "accommodation_fee", "campus_count", "established_year",
            "master_phd_points", "first_class_major_count", "faculty_count",
            "student_faculty_ratio", "profile_available", "missing", "sources",
        ):
            assert field in item, (item["name"], field)


@case("37 并排指标取值与画像一致，硕博点为 {master, phd} 对象")
def _() -> None:
    item = post_data("/api/schools/compare", {"school_ids": [school_id_by_name("郑州大学")]})["items"][0]
    assert item["profile_available"] is True
    assert item["tuition_range"] == "4400-5700 元/年"
    assert item["campus_count"] == 2, "校区数应为 campus_list 的长度"
    assert item["established_year"] == 1956
    assert item["master_phd_points"] == {"master": 60, "phd": 31}, item["master_phd_points"]
    assert item["first_class_major_count"] == 65
    assert item["faculty_count"] == 5800
    assert item["student_faculty_ratio"] == "17:1"
    assert item["missing"] == [], item["missing"]
    assert item["sources"], "并排行需带来源"


@case("38 无画像院校如实留空并标记 missing，不报错")
def _() -> None:
    item = post_data("/api/schools/compare", {"school_ids": [school_id_by_name("河南工业大学")]})["items"][0]
    assert item["profile_available"] is False
    assert item["tuition_range"] is None
    assert item["campus_count"] is None
    assert item["master_phd_points"] is None
    assert set(item["missing"]) == PROFILE_METRIC_FIELDS, item["missing"]
    assert item["sources"] == []
    assert item["name"] == "河南工业大学", "基础属性仍并排展示"
    assert item["level"] == "本科"


@case("39 重复 id 去重后保留首次出现顺序")
def _() -> None:
    zzu = school_id_by_name("郑州大学")
    henu = school_id_by_name("河南大学")
    result = post_data("/api/schools/compare", {"school_ids": [henu, zzu, henu]})
    assert [item["school_id"] for item in result["items"]] == [henu, zzu]
    assert result["count"] == 2


@case("40 空数组 / 非正 id / 超 5 校 / 类型错误一律 1001")
def _() -> None:
    assert post_error_code("/api/schools/compare", {"school_ids": []}) == 1001
    assert post_error_code("/api/schools/compare", {"school_ids": [0]}) == 1001
    assert post_error_code("/api/schools/compare", {"school_ids": [1, 2, 3, 4, 5, 6]}) == 1001
    assert post_error_code("/api/schools/compare", {"school_ids": ["abc"]}) == 1001
    assert post_error_code("/api/schools/compare", {}) == 1001


@case("41 含不存在的院校返回 1001（不静默丢校）")
def _() -> None:
    zzu = school_id_by_name("郑州大学")
    assert post_error_code("/api/schools/compare", {"school_ids": [zzu, 999999]}) == 1001


@case("42 恰好 5 校在上限内可对比")
def _() -> None:
    ids = [item["school_id"] for item in data("/api/schools", page_size=5)["items"]]
    assert len(ids) == 5
    result = post_data("/api/schools/compare", {"school_ids": ids})
    assert result["count"] == 5
    assert [item["school_id"] for item in result["items"]] == ids


@case("43 院校层次：列表项带标记，支持按 985 / 211 / 双一流 筛选")
def _() -> None:
    # 列表项必须带层次字段（缺数据时如实为 false / ""，不推断）
    items = data("/api/schools")["items"]
    assert all({"is_985", "is_211", "dual_class"} <= set(item) for item in items)

    # 演示数据未标层次：is_985=true 命中 0（而非报错或返回全部）
    assert data("/api/schools", is_985=True)["total"] == 0
    assert data("/api/schools", is_985=False)["total"] == TOTAL_SCHOOLS

    zzu = school_id_by_name("郑州大学")
    with SessionLocal() as db:
        db.execute(
            update(School)
            .where(School.id == zzu)
            .values(is_985=True, is_211=True, dual_class="双一流")
        )
        db.commit()
    try:
        assert data("/api/schools", is_985=True)["total"] == 1
        assert data("/api/schools", is_211=True)["total"] == 1
        assert data("/api/schools", dual_class="双一流")["total"] == 1
        assert data("/api/schools", is_985=False)["total"] == TOTAL_SCHOOLS - 1
        # 层次与其它条件为「与」关系
        assert data("/api/schools", is_985=True, keyword="郑州")["total"] == 1
        assert data("/api/schools", is_985=True, province="湖北")["total"] == 0
        marked = data("/api/schools", keyword="郑州大学")["items"][0]
        assert marked["is_985"] is True and marked["is_211"] is True
        assert marked["dual_class"] == "双一流"
    finally:
        with SessionLocal() as db:
            db.execute(
                update(School)
                .where(School.id == zzu)
                .values(is_985=False, is_211=False, dual_class="")
            )
            db.commit()
    assert data("/api/schools", is_985=True)["total"] == 0


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
    print(f"\n院校与专业用例：{total - len(failures)}/{total} 通过")
    if failures:
        return 1
    print("school & major tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
