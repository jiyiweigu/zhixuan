"""资格判定边界用例测试（tasks.md 4.6 后端侧）。

覆盖三类专项与普通批的边界条件：非农村户籍、县不在名单、学籍年限不足、
户籍年限不足、父母户籍不符、学籍地与户籍地不一致、未通过报名审核、
省份未覆盖、字段缺失、名单未核验、未知检查类型等。

测试用 fixture 注入"已核验"的区域名单，从而覆盖 eligible / ineligible 分支；
真实数据文件中名单为未核验状态，对应 pending 分支（见 CASE 16）。

无需 pytest，直接运行：
    cd backend && .venv\\Scripts\\python.exe test_eligibility.py
"""

from __future__ import annotations

from typing import Any, Callable

from app.core import dataset
from app.core.dataset import DataSourceError, validate_citation
from app.services.eligibility import check_region, evaluate

CATALOG = dataset.load_catalog()
RULES = dataset.load_rules()

# 已核验的测试名单：河南国家专项 2 县、高校专项 3 县、地方专项为全省农村
FIXTURE_REGIONS: list[dict[str, Any]] = [
    {
        "province": "河南",
        "program": "national",
        "program_name": "国家专项计划",
        "scope": "county_list",
        "verified": True,
        "expected_count": 2,
        "counties": ["兰考县", "嵩县"],
        "definition": "测试名单",
        "source_name": "测试来源（非官方）",
        "source_url": "https://example.invalid/test",
        "year": 2026,
    },
    {
        "province": "河南",
        "program": "college",
        "program_name": "高校专项计划",
        "scope": "county_list",
        "verified": True,
        "expected_count": 3,
        "counties": ["兰考县", "嵩县", "淅川县"],
        "definition": "测试名单",
        "source_name": "测试来源（非官方）",
        "source_url": "https://example.invalid/test",
        "year": 2026,
    },
    {
        "province": "河南",
        "program": "local",
        "program_name": "地方专项计划",
        "scope": "province_rural",
        "verified": True,
        "expected_count": None,
        "counties": [],
        "definition": "全省农村地区",
        "source_name": "测试来源（非官方）",
        "source_url": "https://example.invalid/test",
        "year": 2026,
    },
]

# 一份完全满足三大专项条件的河南考生
BASELINE: dict[str, Any] = {
    "province": "河南",
    "score": 620,
    "subject_type": "物理类",
    "household_type": "农村",
    "home_county": "兰考县",
    "enrollment_county": "兰考县",
    "household_years": 3,
    "enrollment_years": 3,
    "parent_household_local": True,
    "registered": True,
}


def run(**overrides: Any) -> dict[str, Any]:
    """以基线为底，覆盖指定字段后执行一次判定（使用已核验的测试名单）。"""
    payload = dict(BASELINE)
    payload.update(overrides)
    return evaluate(payload, regions=FIXTURE_REGIONS)


def status_of(result: dict[str, Any], pathway_id: str) -> str:
    for conclusion in result["conclusions"]:
        if conclusion["pathway_id"] == pathway_id:
            return conclusion["status"]
    raise AssertionError(f"结论中缺少途径 {pathway_id}")


def failed_rules(result: dict[str, Any], pathway_id: str) -> list[str]:
    for conclusion in result["conclusions"]:
        if conclusion["pathway_id"] == pathway_id:
            return [item["rule_id"] for item in conclusion["reasons"] if item["result"] == "failed"]
    raise AssertionError(f"结论中缺少途径 {pathway_id}")


CASES: list[tuple[str, Callable[[], None]]] = []


def case(title: str) -> Callable[[Callable[[], None]], Callable[[], None]]:
    def register(fn: Callable[[], None]) -> Callable[[], None]:
        CASES.append((title, fn))
        return fn

    return register


# --------------------------------------------------------------------------- #
# 正向：完全满足
# --------------------------------------------------------------------------- #
@case("01 满足全部条件时三大专项与普通批均判定为符合")
def _() -> None:
    result = run()
    assert status_of(result, "national-plan") == "eligible", result["pending"]
    assert status_of(result, "college-plan") == "eligible"
    assert status_of(result, "local-plan") == "eligible"
    assert status_of(result, "regular-batch") == "eligible"
    assert result["eligible"] == ["普通批", "国家专项计划", "高校专项计划", "地方专项计划"]
    assert result["ineligible"] == [] and result["pending"] == []


@case("02 国家专项不要求农村户籍：城镇户籍且县在名单内仍判定为符合")
def _() -> None:
    result = run(household_type="城镇")
    assert status_of(result, "national-plan") == "eligible"
    # 但高校专项与地方专项明确要求农村户籍
    assert status_of(result, "college-plan") == "ineligible"
    assert status_of(result, "local-plan") == "ineligible"


@case("03 资格判定与分数无关：低分不影响专项资格结论")
def _() -> None:
    low = run(score=300)
    high = run(score=750)
    for pathway in ("regular-batch", "national-plan", "college-plan", "local-plan"):
        assert status_of(low, pathway) == status_of(high, pathway)


# --------------------------------------------------------------------------- #
# 反向：明确不满足
# --------------------------------------------------------------------------- #
@case("04 户籍连续年限不足 3 年判定为不符合")
def _() -> None:
    result = run(household_years=2)
    assert status_of(result, "national-plan") == "ineligible"
    assert "NATIONAL-R4" in failed_rules(result, "national-plan")


@case("05 学籍连续年限不足 3 年判定为不符合")
def _() -> None:
    result = run(enrollment_years=2)
    assert status_of(result, "national-plan") == "ineligible"
    assert "NATIONAL-R6" in failed_rules(result, "national-plan")


@case("06 户籍所在县不在实施区域名单判定为不符合")
def _() -> None:
    result = run(home_county="金水区", enrollment_county="金水区")
    assert status_of(result, "national-plan") == "ineligible"
    assert "NATIONAL-R3" in failed_rules(result, "national-plan")
    assert status_of(result, "college-plan") == "ineligible"


@case("07 父母或法定监护人户籍不在当地判定为不符合")
def _() -> None:
    result = run(parent_household_local=False)
    assert status_of(result, "national-plan") == "ineligible"
    assert "NATIONAL-R5" in failed_rules(result, "national-plan")


@case("08 未通过高考报名资格审核判定为不符合")
def _() -> None:
    result = run(registered=False)
    assert status_of(result, "national-plan") == "ineligible"
    assert status_of(result, "local-plan") == "ineligible"


@case("09 学籍所在县与户籍所在县不一致判定为不符合")
def _() -> None:
    result = run(enrollment_county="淅川县")
    assert status_of(result, "national-plan") == "ineligible"
    assert "NATIONAL-R7" in failed_rules(result, "national-plan")


@case("10 高校专项要求农村户籍：城镇户籍判定为不符合")
def _() -> None:
    result = run(household_type="城镇")
    assert "COLLEGE-R4" in failed_rules(result, "college-plan")


@case("11 地方专项要求本省农村户籍：城镇户籍判定为不符合")
def _() -> None:
    result = run(household_type="城镇")
    assert "LOCAL-R3" in failed_rules(result, "local-plan")


@case("12 县仅在高校专项名单内时：高校专项符合、国家专项不符合")
def _() -> None:
    result = run(home_county="淅川县", enrollment_county="淅川县")
    assert status_of(result, "college-plan") == "eligible"
    assert status_of(result, "national-plan") == "ineligible"


# --------------------------------------------------------------------------- #
# 不确定：字段缺失或数据未核验，一律不臆测
# --------------------------------------------------------------------------- #
@case("13 户籍类型未知时高校专项与地方专项落为待核验")
def _() -> None:
    result = run(household_type="未知")
    assert status_of(result, "college-plan") == "pending"
    assert status_of(result, "local-plan") == "pending"
    assert "国家专项计划" not in result["ineligible"]


@case("14 未填写户籍所在县时国家专项落为待核验而非不符合")
def _() -> None:
    result = run(home_county="", enrollment_county="")
    assert status_of(result, "national-plan") == "pending"
    assert result["ineligible"] == [] or "国家专项计划" not in result["ineligible"]


@case("15 未填写年限（0 视为未知）时结论为待核验")
def _() -> None:
    result = run(household_years=0, enrollment_years=0)
    assert status_of(result, "national-plan") == "pending"


@case("16 名单未核验（真实数据文件）时只输出待核验，不给确定结论")
def _() -> None:
    result = evaluate({"province": "河南", "score": 620, "subject_type": "物理类"})
    assert result["ineligible"] == []
    assert set(result["pending"]) == {"国家专项计划", "高校专项计划", "地方专项计划"}
    assert result["eligible"] == ["普通批"]


@case("17 父母户籍未确认时落为待核验")
def _() -> None:
    result = run(parent_household_local=None)
    assert status_of(result, "national-plan") == "pending"


@case("18 未覆盖省份（广东）不判定为不符合，而是待核验")
def _() -> None:
    result = run(province="广东")
    assert "国家专项计划" not in result["ineligible"]
    assert status_of(result, "national-plan") == "pending"
    assert status_of(result, "regular-batch") == "eligible"


@case("19 只提交省份/分数/科类（旧契约形态）不报错且返回三态数组")
def _() -> None:
    result = evaluate({"province": "河南", "score": 620, "subject_type": "物理类"})
    for key in ("eligible", "pending", "ineligible"):
        assert isinstance(result[key], list), key
    assert result["profile"]["province"] == "河南"


@case("20 缺失输入被逐项列出，供前端提示补全")
def _() -> None:
    result = evaluate({"province": "河南", "score": 620, "subject_type": "物理类"})
    fields = {item["field"] for item in result["missing_fields"]}
    assert {"household_type", "home_county", "household_years"} <= fields


# --------------------------------------------------------------------------- #
# 可溯源、确定性、结构完整性
# --------------------------------------------------------------------------- #
@case("21 每条结论均附规则条文与来源三要素，无来源不输出")
def _() -> None:
    result = run()
    assert result["citations"], "顶层 citations 不得为空"
    for conclusion in result["conclusions"]:
        assert conclusion["citations"], f"{conclusion['pathway_id']} 缺少来源"
        for reason in conclusion["reasons"]:
            assert reason["rule_id"] and reason["text"], "规则条文不得为空"
            citation = reason["citation"]
            assert citation["source_name"] and citation["source_url"] and citation["year"]


@case("22 相同输入重复判定结果完全一致（确定性，无随机、无模型参与）")
def _() -> None:
    import json

    first = json.dumps(run(), ensure_ascii=False, sort_keys=True)
    second = json.dumps(run(), ensure_ascii=False, sort_keys=True)
    assert first == second


@case("23 未满足的规则给出可读说明，符合的规则不携带整改说明")
def _() -> None:
    result = run(household_years=1)
    conclusion = next(c for c in result["conclusions"] if c["pathway_id"] == "national-plan")
    for reason in conclusion["reasons"]:
        if reason["result"] == "passed":
            assert reason["note"] == ""
        else:
            assert reason["note"], f"{reason['rule_id']} 缺少不满足说明"


@case("24 规划中通道如实标注，不出现虚构录取数据")
def _() -> None:
    result = run()
    assert result["planned"], "应包含数据规划中的通道"
    for item in result["planned"]:
        assert item["status"] == "数据规划中"
        assert "录取数据未接入" in item["reason"] or "规划中" in item["reason"]
        assert item["citation"]["source_name"]


@case("25 结果包含免责声明")
def _() -> None:
    assert "以各省教育考试院官方审核结果为准" in run()["disclaimer"]


# --------------------------------------------------------------------------- #
# 区域判定（tasks.md 4.3）
# --------------------------------------------------------------------------- #
@case("26 区域判定：县在名单内返回所属专项范围")
def _() -> None:
    region = check_region("河南", "兰考县", regions=FIXTURE_REGIONS)
    programs = {item["program"] for item in region["in_region"]}
    assert programs == {"national", "college"}, programs
    assert not region["not_in_region"]


@case("27 区域判定：县只在高校专项名单内")
def _() -> None:
    region = check_region("河南", "淅川县", regions=FIXTURE_REGIONS)
    assert {item["program"] for item in region["in_region"]} == {"college"}
    assert {item["program"] for item in region["not_in_region"]} == {"national"}


@case("28 区域判定：地方专项为全省农村，不按县名单判定")
def _() -> None:
    region = check_region("河南", "兰考县", regions=FIXTURE_REGIONS)
    local = next(item for item in region["undetermined"] if item["program"] == "local")
    assert "农村" in local["reason"]


@case("29 区域判定：真实名单未核验时归入待定，不给出确定归属")
def _() -> None:
    region = check_region("河南", "兰考县")
    assert not region["in_region"] and not region["not_in_region"]
    assert len(region["undetermined"]) == 3
    assert region["citations"], "区域判定同样必须带来源"


# --------------------------------------------------------------------------- #
# 数据来源强制校验（tasks.md 2.6）
# --------------------------------------------------------------------------- #
@case("30 缺来源三要素的数据被拒绝，不得进入系统")
def _() -> None:
    for missing in ("source_name", "source_url", "year"):
        record = {"source_name": "x", "source_url": "y", "year": 2026}
        record.pop(missing)
        try:
            validate_citation(record, "用例数据")
        except DataSourceError:
            continue
        raise AssertionError(f"缺少 {missing} 时未被拒绝")

    for bad_year in (0, 1999, 2101, "2026", None, True):
        record = {"source_name": "x", "source_url": "y", "year": bad_year}
        try:
            validate_citation(record, "用例数据")
        except DataSourceError:
            continue
        raise AssertionError(f"非法年份 {bad_year!r} 未被拒绝")


@case("31 未知 check 类型不崩溃，该条规则落为待核验")
def _() -> None:
    rules = list(RULES) + [
        {
            "rule_id": "REGULAR-RX",
            "pathway_id": "regular-batch",
            "order": 99,
            "title": "未来扩展规则",
            "check": "not_implemented_yet",
            "params": {},
            "text": "占位",
            "remedy": "该规则尚未实现",
            "source_name": "测试来源（非官方）",
            "source_url": "https://example.invalid/test",
            "year": 2026,
        }
    ]
    result = evaluate(BASELINE, catalog=CATALOG, regions=FIXTURE_REGIONS, rules=rules)
    assert status_of(result, "regular-batch") == "pending"


@case("32 真实数据文件的规则与途径 id 一一对应，无孤儿规则")
def _() -> None:
    pathway_ids = {item["id"] for item in CATALOG}
    rule_pathways = {item["pathway_id"] for item in RULES}
    assert rule_pathways <= pathway_ids, f"孤儿规则：{rule_pathways - pathway_ids}"


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
    print(f"\n边界用例：{total - len(failures)}/{total} 通过")
    if failures:
        return 1
    print("eligibility boundary tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
