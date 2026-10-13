"""志愿方案边界用例测试（tasks.md 6.3 / 6.4 / 6.5 后端侧）。

覆盖：档位边界分数（正好落在临界值）、档位顺序、策略切换排序、配额缩放、
候选不足不硬凑、六类风险预警触发与不触发、依据与来源完整性、确定性等。

无需 pytest，直接运行：
    cd backend && .venv\\Scripts\\python.exe test_plans.py
"""

from __future__ import annotations

from typing import Any, Callable

from app.core import dataset
from app.services.plans import (
    TIER_ORDER,
    _scale_quota,
    build_plan,
)

STRATEGY_CONFIG = dataset.load_strategy_config()
RISK_RULES = dataset.load_risk_rules()

# 以 600 分考生为基准，构造刚好覆盖各档边界与超范围两侧的候选
BOUNDARY_SCORES = [585, 590, 600, 601, 615, 616, 569, 570]


def _cand(index: int, min_score: int, **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "school_id": f"t{index:02d}",
        "name": f"测试院校{index:02d}",
        "province": "河南",
        "city": "郑州",
        "major": "测试专业",
        "subject_requirement": "物理类",
        "min_score": min_score,
        "admission_year": 2025,
        "source_name": "测试来源（非官方）",
        "source_url": "https://example.invalid/test",
        "year": 2026,
    }
    item.update(overrides)
    return item


BOUNDARY_CANDIDATES = [_cand(index, score) for index, score in enumerate(BOUNDARY_SCORES)]

BASE_PAYLOAD: dict[str, Any] = {
    "profile": {"province": "河南", "score": 600, "subject_type": "物理类"},
    "strategy": "稳",
}


def run(**overrides: Any) -> dict[str, Any]:
    """使用边界候选与测试规则执行一次方案生成。"""
    payload = {**BASE_PAYLOAD, **overrides}
    return build_plan(
        payload,
        candidates=BOUNDARY_CANDIDATES,
        strategies=STRATEGY_CONFIG,
        risk_rules=RISK_RULES,
    )


def tier_of(result: dict[str, Any], min_score: int) -> str | None:
    for item in result["items"]:
        if item["min_score"] == min_score:
            return item["tier"]
    return None


def risk_codes(result: dict[str, Any]) -> set[str]:
    return {item["code"] for item in result["risks"]}


CASES: list[tuple[str, Callable[[], None]]] = []


def case(title: str) -> Callable[[Callable[[], None]], Callable[[], None]]:
    def register(fn: Callable[[], None]) -> Callable[[], None]:
        CASES.append((title, fn))
        return fn

    return register


# --------------------------------------------------------------------------- #
# 档位边界（tasks.md 6.3）
# --------------------------------------------------------------------------- #
@case("01 分档边界：-15 / -1 归入冲，0 / +10 归入稳，+11 / +30 归入保")
def _() -> None:
    result = run()
    assert tier_of(result, 615) == "冲", "gap=-15 应为冲档下界"
    assert tier_of(result, 601) == "冲", "gap=-1 应为冲档上界"
    assert tier_of(result, 600) == "稳", "gap=0 应为稳档下界"
    assert tier_of(result, 590) == "稳", "gap=+10 应为稳档上界"
    assert tier_of(result, 585) == "保", "gap=+15 应为保档"
    assert tier_of(result, 570) == "保", "gap=+30 应为保档上界"


@case("02 超范围候选被排除：gap=-16 过高、gap=+31 过低，均不入方案")
def _() -> None:
    result = run()
    assert tier_of(result, 616) is None, "gap=-16 超出冲档范围，不应入选"
    assert tier_of(result, 569) is None, "gap=+31 超出保档范围，不应入选"
    excluded = {item["min_score"] for item in result["excluded"]}
    assert excluded == {616, 569}, excluded


@case("03 排除项给出可读原因，不静默丢弃")
def _() -> None:
    for item in run()["excluded"]:
        assert item["reason"], f"被排除的 {item['min_score']} 分候选缺少原因"
        assert "15" in item["reason"] or "30" in item["reason"], item["reason"]


@case("04 档间顺序固定为 冲 → 稳 → 保，不因排序策略改变")
def _() -> None:
    for priority in ("院校优先", "专业优先", "城市优先"):
        tiers = [item["tier"] for item in run(priority=priority)["items"]]
        order_index = [TIER_ORDER.index(tier) for tier in tiers]
        assert order_index == sorted(order_index), f"{priority} 下档位乱序：{tiers}"


@case("05 每个入选志愿都带分档依据，且依据与档位一致")
def _() -> None:
    for item in run()["items"]:
        assert item["reasons"], f"{item['name']} 缺少依据"
        joined = " ".join(item["reasons"])
        assert item["tier"] in joined, f"{item['name']} 的依据未说明档位"
        assert str(item["min_score"]) in joined, f"{item['name']} 的依据未给出分数"


@case("06 每个入选志愿都带来源三要素（契约 PlanItem 继承 Citation）")
def _() -> None:
    for item in run()["items"]:
        for field in ("source_name", "source_url", "year"):
            assert item.get(field), f"{item['name']} 缺少 {field}"
        assert item["citations"], f"{item['name']} 缺少 citations"


# --------------------------------------------------------------------------- #
# 排序策略（tasks.md 6.4）
# --------------------------------------------------------------------------- #
@case("07 院校优先：档内按录取分由高到低排列")
def _() -> None:
    scores = [item["min_score"] for item in run(priority="院校优先")["items"]]
    assert scores[:2] == [615, 601], scores[:2]
    assert scores[2:4] == [600, 590], scores[2:4]


@case("08 专业优先：命中偏好专业的候选在档内前置，并标注原因")
def _() -> None:
    result = build_plan(
        {**BASE_PAYLOAD, "priority": "专业优先", "preferred_majors": ["测试专业"]},
        candidates=[_cand(0, 600, major="普通专业"), _cand(1, 598, major="测试专业")],
        strategies=STRATEGY_CONFIG,
        risk_rules=RISK_RULES,
    )
    assert [item["major"] for item in result["items"]] == ["测试专业", "普通专业"]
    assert "命中偏好专业" in " ".join(result["items"][0]["reasons"])


@case("09 城市优先：命中偏好城市的候选在档内前置，并标注原因")
def _() -> None:
    result = build_plan(
        {**BASE_PAYLOAD, "priority": "城市优先", "preferred_provinces": ["武汉"]},
        candidates=[
            _cand(0, 600, province="河南", city="郑州"),
            _cand(1, 598, province="湖北", city="武汉"),
        ],
        strategies=STRATEGY_CONFIG,
        risk_rules=RISK_RULES,
    )
    assert [item["city"] for item in result["items"]] == ["武汉", "郑州"]
    assert "命中偏好地区" in " ".join(result["items"][0]["reasons"])


@case("10 切换排序策略不改变档位与入选集合，只改变档内次序")
def _() -> None:
    def snapshot(priority: str) -> tuple:
        result = run(priority=priority)
        return (
            sorted((item["min_score"], item["tier"]) for item in result["items"]),
            result["tiers"],
        )

    assert snapshot("院校优先") == snapshot("专业优先") == snapshot("城市优先")


@case("11 每条志愿带顺序号，与实际排列一致")
def _() -> None:
    for index, item in enumerate(run()["items"], start=1):
        assert item["order"] == index


# --------------------------------------------------------------------------- #
# 配额与候选不足（tasks.md 6.3）
# --------------------------------------------------------------------------- #
@case("12 配额缩放：各档配额之和等于方案志愿总数")
def _() -> None:
    for limit in (1, 3, 6, 9, 12, 45):
        result = run(limit=limit)
        assert sum(result["quota"].values()) == limit, (limit, result["quota"])


@case("13 缺额按比例分配，缩放函数不丢不超")
def _() -> None:
    quota = {"冲": 2, "稳": 4, "保": 3}
    for limit in range(1, 21):
        scaled = _scale_quota(quota, limit)
        assert sum(scaled.values()) == limit, (limit, scaled)
        assert all(value >= 0 for value in scaled.values())


@case("14 候选不足时不硬凑，shortage 如实记录缺口")
def _() -> None:
    result = build_plan(
        {**BASE_PAYLOAD, "strategy": "保"},
        candidates=[_cand(0, 600)],
        strategies=STRATEGY_CONFIG,
        risk_rules=RISK_RULES,
    )
    assert result["tiers"]["稳"] == 1
    shortage = {item["tier"]: item for item in result["shortage"]}
    assert shortage["稳"]["expected"] == 3 and shortage["稳"]["actual"] == 1
    assert shortage["保"]["actual"] == 0
    assert any("候选不足" in note for note in result["risk_notes"])


@case("15 非法倾向值回退到「稳」，不产出空方案")
def _() -> None:
    result = run(strategy="非常激进")
    assert result["strategy"] == "稳"
    assert result["items"]


@case("16 无任何候选时返回空方案并给出提示，不抛异常")
def _() -> None:
    result = build_plan(BASE_PAYLOAD, candidates=[], strategies=STRATEGY_CONFIG, risk_rules=RISK_RULES)
    assert result["items"] == []
    assert result["risk_notes"] == []
    assert "未匹配到" in result["summary"]


# --------------------------------------------------------------------------- #
# 风险预警（tasks.md 6.5）
# --------------------------------------------------------------------------- #
@case("17 缺少保底志愿触发高风险提示")
def _() -> None:
    result = build_plan(
        BASE_PAYLOAD,
        candidates=[_cand(0, 601), _cand(1, 600)],
        strategies=STRATEGY_CONFIG,
        risk_rules=RISK_RULES,
    )
    assert "NO_BAO" in risk_codes(result)
    level = next(item["level"] for item in result["risks"] if item["code"] == "NO_BAO")
    assert level == "high"


@case("18 全部为冲刺志愿触发高风险提示")
def _() -> None:
    result = build_plan(
        BASE_PAYLOAD,
        candidates=[_cand(0, 601), _cand(1, 605)],
        strategies=STRATEGY_CONFIG,
        risk_rules=RISK_RULES,
    )
    assert "ALL_CHONG" in risk_codes(result)


@case("19 缺少稳妥志愿触发中风险提示")
def _() -> None:
    result = build_plan(
        BASE_PAYLOAD,
        candidates=[_cand(0, 601), _cand(1, 585)],
        strategies=STRATEGY_CONFIG,
        risk_rules=RISK_RULES,
    )
    assert "NO_WEN" in risk_codes(result)


@case("20 相邻志愿分差过小触发梯度不足提示")
def _() -> None:
    result = build_plan(
        BASE_PAYLOAD,
        candidates=[_cand(0, 600), _cand(1, 599)],
        strategies=STRATEGY_CONFIG,
        risk_rules=RISK_RULES,
    )
    assert "GRADIENT_TOO_SMALL" in risk_codes(result)
    evidence = next(item["evidence"] for item in result["risks"] if item["code"] == "GRADIENT_TOO_SMALL")
    assert "600" in evidence and "599" in evidence


@case("21 梯度充足时不误报梯度风险")
def _() -> None:
    result = build_plan(
        BASE_PAYLOAD,
        candidates=[_cand(0, 610), _cand(1, 600), _cand(2, 585)],
        strategies=STRATEGY_CONFIG,
        risk_rules=RISK_RULES,
    )
    assert "GRADIENT_TOO_SMALL" not in risk_codes(result)


@case("22 选科要求不满足触发高风险提示")
def _() -> None:
    result = build_plan(
        BASE_PAYLOAD,
        candidates=[_cand(0, 600, subject_requirement="历史类")],
        strategies=STRATEGY_CONFIG,
        risk_rules=RISK_RULES,
    )
    assert "SUBJECT_REQUIREMENT" in risk_codes(result)
    assert result["items"][0]["risk_level"] == "high"
    assert result["items"][0]["subject_status"] == "unmet"


@case("23 附加选考科目无法确认时标为需本人确认，不武断判为不符合")
def _() -> None:
    result = build_plan(
        BASE_PAYLOAD,
        candidates=[_cand(0, 600, subject_requirement="物理+化学")],
        strategies=STRATEGY_CONFIG,
        risk_rules=RISK_RULES,
    )
    item = result["items"][0]
    assert item["subject_status"] == "unknown"
    assert item["risk_level"] == "medium"
    assert "确认" in " ".join(item["reasons"])


@case("24 不服从专业调剂触发风险提示")
def _() -> None:
    assert "NO_MAJOR_ADJUST" in risk_codes(run(major_adjust=False))
    assert "NO_MAJOR_ADJUST" not in risk_codes(run(major_adjust=True))


@case("25 提供批次线且贴近时触发提示；未提供批次线时不判定")
def _() -> None:
    assert "NEAR_BATCH_LINE" in risk_codes(run(batch_line=595))
    assert "NEAR_BATCH_LINE" not in risk_codes(run(batch_line=500))
    assert "NEAR_BATCH_LINE" not in risk_codes(run())


@case("26 保底志愿不足 2 个触发中风险提示")
def _() -> None:
    result = build_plan(
        BASE_PAYLOAD,
        candidates=[_cand(0, 600), _cand(1, 590), _cand(2, 585)],
        strategies=STRATEGY_CONFIG,
        risk_rules=RISK_RULES,
    )
    assert "BAO_TOO_FEW" in risk_codes(result)


@case("27 档位分布失衡触发提示")
def _() -> None:
    result = build_plan(
        BASE_PAYLOAD,
        candidates=[_cand(index, 600 - index) for index in range(6)],
        strategies=STRATEGY_CONFIG,
        risk_rules=RISK_RULES,
    )
    assert result["tiers"]["稳"] == result["quota"]["稳"]
    assert "TIER_UNBALANCED" in risk_codes(result)


@case("28 风险按等级降序排列，高风险在前")
def _() -> None:
    result = run(major_adjust=False, batch_line=595)
    order = {"high": 3, "medium": 2, "low": 1}
    levels = [order[item["level"]] for item in result["risks"]]
    assert levels == sorted(levels, reverse=True), levels


@case("29 每条风险都带说明、整改建议与来源")
def _() -> None:
    for item in run(major_adjust=False, batch_line=595)["risks"]:
        assert item["title"] and item["detail"], item["code"]
        assert item["remedy"], f"{item['code']} 缺少整改建议"
        for field in ("source_name", "source_url", "year"):
            assert item["citation"].get(field), f"{item['code']} 缺少 {field}"


@case("30 契约字段完整：items / risk_notes / citations 均存在且形状正确")
def _() -> None:
    result = run()
    assert isinstance(result["items"], list) and result["items"]
    assert isinstance(result["risk_notes"], list)
    assert all(isinstance(note, str) for note in result["risk_notes"])
    assert isinstance(result["citations"], list) and result["citations"]
    for item in result["items"]:
        assert item["risk_level"] in {"low", "medium", "high"}
        assert item["tier"] in TIER_ORDER


@case("31 citations 去重，不重复堆叠同一来源")
def _() -> None:
    keys = [(item["source_name"], item["source_url"], item["year"]) for item in run()["citations"]]
    assert len(keys) == len(set(keys))


@case("32 相同输入重复生成结果完全一致（确定性）")
def _() -> None:
    import json

    assert json.dumps(run(), ensure_ascii=False, sort_keys=True) == json.dumps(
        run(), ensure_ascii=False, sort_keys=True
    )


@case("33 每个入选志愿都标注风险等级，且依据与等级自洽")
def _() -> None:
    result = build_plan(
        BASE_PAYLOAD,
        candidates=[_cand(0, 601), _cand(1, 600), _cand(2, 585, subject_requirement="历史类")],
        strategies=STRATEGY_CONFIG,
        risk_rules=RISK_RULES,
    )
    for item in result["items"]:
        if item["subject_status"] == "unmet":
            assert item["risk_level"] == "high"
        elif item["tier"] == "冲":
            assert item["risk_level"] in {"medium", "high"}


@case("34 档位定义不重叠且区间自洽（数据不变式）")
def _() -> None:
    strategies = sorted(STRATEGY_CONFIG["strategies"], key=lambda item: item["min_gap"])
    for previous, current in zip(strategies, strategies[1:]):
        assert current["min_gap"] > previous["max_gap"], (previous, current)


@case("35 数据文件中的候选与风险规则均通过来源校验")
def _() -> None:
    assert dataset.load_candidates(), "候选数据不得为空"
    assert dataset.load_risk_rules(), "风险规则不得为空"
    for rule in dataset.load_risk_rules():
        assert rule["level"] in {"low", "medium", "high"}, rule["code"]


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
    print(f"\n方案边界用例：{total - len(failures)}/{total} 通过")
    if failures:
        return 1
    print("plan boundary tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
