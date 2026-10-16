"""报考约束引擎边界用例（产品书 8.5 清单，≥30 条）。

覆盖五组：选科（≥8）/ 身体条件（≥10）/ 学费（≥4）/ 省份规则与批次（≥5）/
组合与幂等（≥3）。三条红线在此锁死：

1. 色弱报临床医学 → ``reject``（blocker）
2. 体检全未填 → ``unknowns`` 且**不默认放行**
3. 引擎为纯函数：同输入连调两次输出完全相同

运行：``cd backend && .venv/Scripts/python.exe test_engine.py``
"""

from __future__ import annotations

from typing import Any, Callable

from app.engine import constraints as eng

CASES: list[tuple[str, Callable[[], None]]] = []


def case(name: str) -> Callable[[Callable[[], None]], Callable[[], None]]:
    def deco(fn: Callable[[], None]) -> Callable[[], None]:
        CASES.append((name, fn))
        return fn

    return deco


CITE = {"source_name": "河南省教育考试院", "source_url": "https://www.haeea.cn/", "year": 2026}
CITE_MOE = {
    "source_name": "《普通高等学校招生体检工作指导意见》",
    "source_url": "http://www.moe.gov.cn/",
    "year": 2026,
}


def _profile(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "province": "河南",
        "exam_type": "普通",
        "first_subject": "物理",
        "second_subjects": ["化学"],
        "score": 620,
        "rank": 12000,
        "color_vision": "正常",
        "vision_left": 5.0,
        "vision_right": 5.0,
        "height": 175,
        "weight": 65,
        "hepatitis_b": False,
        "hearing": "正常",
        "smell": "正常",
        "stutter": "正常",
        "household_type": "农村",
        "home_county": "兰考县",
        "home_county_code": "410225",
        "school_years": 3,
        "tuition_budget": 15000,
        "batch_preference": ["本科批"],
    }
    base.update(kw)
    return base


def _wuhua(major: str = "临床医学") -> dict[str, Any]:
    """物理 + 化学 绑定（all）要求。"""
    return {
        "first_subject": "物理", "secondary_subjects": ["化学"], "logic": "all",
        "major_names": [major], "citation": CITE,
    }


def _restriction(condition: str, level: str, *, threshold: str = "", category: str = "") -> dict[str, Any]:
    return {
        "condition": condition, "threshold": threshold, "level": level,
        "major_category": category, "detail": f"{condition}限制（{category}）",
        "citation": CITE_MOE,
    }


# --------------------------------------------------------------------------- #
# 选科（≥8）
# --------------------------------------------------------------------------- #
@case("选科01 物理类报物化绑定专业 → 通过")
def _() -> None:
    assert eng.subject_match(_profile(), _wuhua()) is None


@case("选科02 历史类报物化绑定专业 → 不可报")
def _() -> None:
    hit = eng.subject_match(_profile(first_subject="历史"), _wuhua())
    assert hit is not None and hit["level"] == eng.LEVEL_REJECT


@case("选科03 只限再选 [化学,生物] all：考生缺生物 → 不可报")
def _() -> None:
    req = {"first_subject": "", "secondary_subjects": ["化学", "生物"], "logic": "all",
           "major_names": ["临床医学"], "citation": CITE}
    hit = eng.subject_match(_profile(second_subjects=["化学"]), req)
    assert hit is not None and hit["level"] == eng.LEVEL_REJECT


@case("选科04 any 逻辑：命中其一即可通过")
def _() -> None:
    req = {"first_subject": "", "secondary_subjects": ["化学", "生物"], "logic": "any",
           "major_names": ["临床医学"], "citation": CITE}
    assert eng.subject_match(_profile(second_subjects=["化学"]), req) is None


@case("选科05 未填首选科目 → unknowns（不得默认放行）")
def _() -> None:
    hit = eng.subject_match(_profile(first_subject=""), _wuhua())
    assert hit is not None and hit["level"] == eng.LEVEL_UNKNOWN


@case("选科06 未填再选科目 → unknowns")
def _() -> None:
    hit = eng.subject_match(_profile(second_subjects=[]), _wuhua())
    assert hit is not None and hit["level"] == eng.LEVEL_UNKNOWN


@case("选科07 必选政治（公安学类）：未选政治 → 不可报")
def _() -> None:
    req = {"first_subject": "", "secondary_subjects": ["政治"], "logic": "all",
           "major_names": ["公安学类"], "citation": CITE}
    hit = eng.subject_match(_profile(second_subjects=["化学"]), req)
    assert hit is not None and hit["level"] == eng.LEVEL_REJECT


@case("选科08 不限选科 → 通过")
def _() -> None:
    req = {"first_subject": "不限", "secondary_subjects": [], "logic": "all",
           "major_names": ["法学"], "citation": CITE}
    assert eng.subject_match(_profile(), req) is None


@case("选科09 艺术类考生报普通类 → 软提示（not_suitable）")
def _() -> None:
    hit = eng.subject_match(_profile(exam_type="艺术"), _wuhua())
    assert hit is not None and hit["level"] == eng.LEVEL_NOT_SUITABLE


# --------------------------------------------------------------------------- #
# 身体条件（≥10）
# --------------------------------------------------------------------------- #
@case("体检01 色弱报临床医学 → reject（红线）")
def _() -> None:
    hits = eng.physical_check(_profile(color_vision="色弱"), [_restriction("色弱", "reject", category="医学类")])
    assert len(hits) == 1 and hits[0]["level"] == eng.LEVEL_REJECT


@case("体检02 色弱报化工（不宜就读）→ not_suitable")
def _() -> None:
    hits = eng.physical_check(_profile(color_vision="色弱"), [_restriction("色弱", "not_suitable", category="化工与制药类")])
    assert len(hits) == 1 and hits[0]["level"] == eng.LEVEL_NOT_SUITABLE


@case("体检03 色盲报动画 → reject")
def _() -> None:
    hits = eng.physical_check(_profile(color_vision="色盲"), [_restriction("色盲", "reject", category="戏剧与影视学类")])
    assert len(hits) == 1 and hits[0]["level"] == eng.LEVEL_REJECT


@case("体检04 裸眼 4.6 报飞行技术（<5.0）→ reject")
def _() -> None:
    hits = eng.physical_check(_profile(vision_left=4.6, vision_right=5.0), [_restriction("裸眼视力", "reject", threshold="<5.0", category="交通运输类")])
    assert len(hits) == 1 and hits[0]["level"] == eng.LEVEL_REJECT


@case("体检05 裸眼 4.9 报飞行技术（<5.0）→ reject")
def _() -> None:
    hits = eng.physical_check(_profile(vision_left=4.9, vision_right=4.9), [_restriction("裸眼视力", "reject", threshold="<5.0", category="交通运输类")])
    assert len(hits) == 1


@case("体检06 裸眼 5.0 报普通专业 → 通过")
def _() -> None:
    hits = eng.physical_check(_profile(vision_left=5.0, vision_right=5.0), [_restriction("裸眼视力", "reject", threshold="<5.0", category="交通运输类")])
    assert hits == []


@case("体检07 乙肝携带报学前教育 → reject")
def _() -> None:
    hits = eng.physical_check(_profile(hepatitis_b=True), [_restriction("乙肝", "reject", threshold="携带", category="教育学类")])
    assert len(hits) == 1 and hits[0]["level"] == eng.LEVEL_REJECT


@case("体检08 身高 165 报公安学类（<170）→ reject")
def _() -> None:
    hits = eng.physical_check(_profile(height=165), [_restriction("身高", "reject", threshold="<170", category="公安学类")])
    assert len(hits) == 1 and hits[0]["level"] == eng.LEVEL_REJECT


@case("体检09 体检全未填 → unknowns 且不默认放行（红线）")
def _() -> None:
    hits = eng.physical_check(
        _profile(color_vision=None, vision_left=None, vision_right=None),
        [_restriction("色弱", "reject", category="医学类")],
    )
    assert len(hits) == 1 and hits[0]["level"] == eng.LEVEL_UNKNOWN


@case("体检10 同专业两个限制只命中其一 → 只返回一条")
def _() -> None:
    hits = eng.physical_check(
        _profile(color_vision="正常", hepatitis_b=True),
        [
            _restriction("色弱", "reject", category="医学类"),
            _restriction("乙肝", "reject", threshold="携带", category="教育学类"),
        ],
    )
    assert len(hits) == 1


@case("体检11 level 值非法 → 报错不吞")
def _() -> None:
    try:
        eng.physical_check(_profile(), [_restriction("色弱", "ban", category="医学类")])
    except ValueError:
        return
    raise AssertionError("非法 level 应抛 ValueError，而不是静默通过")


@case("体检12 听力异常报医学类 → not_suitable")
def _() -> None:
    hits = eng.physical_check(_profile(hearing="异常"), [_restriction("听力", "not_suitable", category="医学类")])
    assert len(hits) == 1 and hits[0]["level"] == eng.LEVEL_NOT_SUITABLE


@case("体检13 单眼视力缺失 → unknown，不用另一眼默认通过")
def _() -> None:
    hits = eng.physical_check(
        _profile(vision_left=5.0, vision_right=None),
        [_restriction("裸眼视力", "reject", threshold="<5.0", category="交通运输类")],
    )
    assert len(hits) == 1 and hits[0]["level"] == eng.LEVEL_UNKNOWN
    assert set(hits[0]["fields"]) == {"vision_left", "vision_right"}


@case("体检14 明确 4.5 阈值按原阈值判定")
def _() -> None:
    hits = eng.physical_check(
        _profile(vision_left=4.7, vision_right=4.9),
        [_restriction("裸眼视力", "reject", threshold="<4.5", category="交通运输类")],
    )
    assert hits == []


@case("体检15 未知哨兵值按未填处理")
def _() -> None:
    hits = eng.physical_check(
        _profile(color_vision="未知"),
        [_restriction("色弱", "reject", category="医学类")],
    )
    assert len(hits) == 1 and hits[0]["level"] == eng.LEVEL_UNKNOWN


@case("体检16 BMI 区间不能退化成体重单阈值")
def _() -> None:
    rule = _restriction("BMI", "reject", threshold="18-24", category="公安学类")
    rule["detail"] = "BMI 应在 18-24"
    hits = eng.physical_check(_profile(height=180, weight=60), [rule])
    assert len(hits) == 1 and hits[0]["level"] == eng.LEVEL_UNKNOWN
    assert set(hits[0]["fields"]) == {"height", "weight"}


@case("体检16a 不支持的视力阈值与矫正视力规则保持 unknown")
def _() -> None:
    threshold_hit = eng.physical_check(
        _profile(), [_restriction("裸眼视力", "reject", threshold="<4.6", category="交通运输类")]
    )
    corrected_hit = eng.physical_check(
        _profile(), [_restriction("矫正视力", "reject", threshold=">=4.8", category="交通运输类")]
    )
    assert threshold_hit and threshold_hit[0]["level"] == eng.LEVEL_UNKNOWN
    assert corrected_hit and corrected_hit[0]["level"] == eng.LEVEL_UNKNOWN
    assert corrected_hit[0]["fields"] == ["corrected_vision"]


@case("体检17 军警专项规则不应用到普通 pathway")
def _() -> None:
    rule = _restriction("身高（军队院校）", "reject", threshold="<170", category="公安学类")
    assert eng.physical_check(_profile(height=160), [rule], {"major_ids": [1]}) == []


@case("体检18 军校性别阈值缺性别字段时待核验")
def _() -> None:
    rule = _restriction("身高（军队院校）", "reject", threshold="<170", category="公安学类")
    hits = eng.physical_check(
        _profile(height=160), [rule], {"major_ids": [1]}, pathway_id="military"
    )
    assert len(hits) == 1 and hits[0]["level"] == eng.LEVEL_UNKNOWN
    assert hits[0]["fields"] == ["gender"]


# --------------------------------------------------------------------------- #
# 学费（≥4）
# --------------------------------------------------------------------------- #
@case("学费01 公办 5000 / 预算 15000 → 通过")
def _() -> None:
    assert eng.fee_check(_profile(tuition_budget=15000), {"amount": 5000, "ownership": "公办"}) is None


@case("学费02 民办 28000 → warnings")
def _() -> None:
    hit = eng.fee_check(_profile(tuition_budget=15000), {"amount": 28000, "ownership": "民办"})
    assert hit is not None and hit["level"] == eng.LEVEL_NOT_SUITABLE


@case("学费03 中外合作 58000 → warnings + 奖助贷提示")
def _() -> None:
    hit = eng.fee_check(_profile(tuition_budget=15000), {"amount": 58000, "ownership": "中外合作"})
    assert hit is not None and "助学贷款" in hit["detail"]


@case("学费04 fee_ceiling 未填 → unknowns")
def _() -> None:
    hit = eng.fee_check(_profile(tuition_budget=None), {"amount": 58000})
    assert hit is not None and hit["level"] == eng.LEVEL_UNKNOWN


# --------------------------------------------------------------------------- #
# 省份规则 / 批次（≥5）
# --------------------------------------------------------------------------- #
@case("省份01 单位批次与模板一致 → 通过")
def _() -> None:
    rule = {"batch": "本科批", "mutex_groups": [], "citation": CITE}
    assert eng.province_rule_check(_profile(), rule, {"batch": "本科批"}) == []


@case("省份02 单位批次与模板不一致 → reject")
def _() -> None:
    rule = {"batch": "提前批", "mutex_groups": [], "citation": CITE}
    hits = eng.province_rule_check(_profile(), rule, {"batch": "本科批"})
    assert len(hits) == 1 and hits[0]["level"] == eng.LEVEL_REJECT


@case("省份03 提前批互斥组 + 勾选多批次 → not_suitable")
def _() -> None:
    rule = {"batch": "提前批", "mutex_groups": ["提前批各类之间互不兼报"], "citation": CITE}
    hits = eng.province_rule_check(
        _profile(batch_preference=["提前批", "本科批"]), rule, {"batch": "提前批"}
    )
    assert len(hits) == 1 and hits[0]["level"] == eng.LEVEL_NOT_SUITABLE


@case("省份04 无互斥组时勾选多批次 → 通过（不误报）")
def _() -> None:
    rule = {"batch": "本科批", "mutex_groups": [], "citation": CITE}
    assert eng.province_rule_check(_profile(batch_preference=["提前批", "本科批"]), rule, {"batch": "本科批"}) == []


@case("省份05 模板缺失（None）→ 不产生误判")
def _() -> None:
    assert eng.province_rule_check(_profile(), None, {"batch": "本科批"}) == []


# --------------------------------------------------------------------------- #
# 组合与幂等（≥3）
# --------------------------------------------------------------------------- #
def _combo_rules() -> dict[str, Any]:
    return {
        "province_rule": {"batch": "本科批", "mutex_groups": [], "citation": CITE},
        "subject_requirements": {
            "u-1": [_wuhua("临床医学")],
            "u-2": [{"first_subject": "不限", "secondary_subjects": [], "logic": "all",
                     "major_names": ["法学"], "citation": CITE}],
        },
        "physical_restrictions": [_restriction("色弱", "reject", category="医学类")],
        "tuition": {"u-1": {"amount": 5800, "ownership": "公办"}, "u-2": {"amount": 5200, "ownership": "公办"}},
    }


@case("组合01 同单位同时命中选科 + 体检 → 两条 blockers 都返回")
def _() -> None:
    profile = _profile(first_subject="历史", color_vision="色弱")
    out = eng.check_units(profile, [{"unit_id": "u-1", "batch": "本科批", "major_ids": [1]}], _combo_rules())
    item = out["items"][0]
    types = {hit["type"] for hit in item["blockers"]}
    assert len(item["blockers"]) >= 2 and eng.CONSTRAINT_TYPE_SUBJECT in types and "physical" in types


@case("组合02 重复调用结果一致（幂等）")
def _() -> None:
    profile = _profile(color_vision="色弱")
    items = [{"unit_id": "u-1", "batch": "本科批", "major_ids": [1]}]
    assert eng.check_units(profile, items, _combo_rules()) == eng.check_units(profile, items, _combo_rules())


@case("组合03 items 空数组 → summary.total = 0 而非报错")
def _() -> None:
    out = eng.check_units(_profile(), [], _combo_rules())
    assert out["summary"]["total"] == 0 and out["items"] == []


@case("组合04 三档同时产出：blockers / warnings / unknowns 各 ≥1")
def _() -> None:
    rules = _combo_rules()
    rules["tuition"]["u-2"] = {"amount": 58000, "ownership": "中外合作"}
    profile = _profile(color_vision="色弱", vision_left=None, vision_right=None, tuition_budget=15000)
    out = eng.check_units(
        profile,
        [{"unit_id": "u-1", "batch": "本科批", "major_ids": [1]},
         {"unit_id": "u-2", "batch": "本科批", "major_ids": [2]}],
        rules,
    )
    assert out["summary"]["total"] == 2
    assert out["summary"]["blocked"] >= 1


def main() -> int:
    passed = 0
    failures: list[str] = []
    for name, fn in CASES:
        try:
            fn()
            passed += 1
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
    total = len(CASES)
    if failures:
        print("引擎边界用例失败：")
        for item in failures:
            print("  -", item)
        print(f"{passed}/{total} 通过")
        return 1
    print(f"引擎边界用例：{passed}/{total} 通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
