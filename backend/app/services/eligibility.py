"""确定性资格规则引擎：升学途径资格自检（tasks.md 4.2、4.3、4.5）。

design.md D6：资格判定结论 SHALL 由确定性规则引擎产出，SHALL NOT 由大模型生成。
本模块不调用任何模型、不读数据库，相同输入恒定输出相同结论；每条结论附所依据的
规则条文与来源，而来源缺失的规则在数据加载阶段即被拒绝（app/core/dataset.py），
因此机制上不存在"无来源结论"。

判定三态（不得臆测）：
- eligible    全部规则通过
- ineligible  存在明确不满足的规则
- pending     输入缺失、或区域名单尚未核验，此时给出"待核验"而非确定结论

对应前端 frontend/src/mocks/index.ts 的三种 mock（eligible / pending / ineligible）。

输入的补充说明：考生档案中的专项标记（special_marks）只在结论里回显为 marked，
不参与规则判定本身 —— 判定只看户籍、学籍、年限等事实输入。
"""

from __future__ import annotations

from typing import Any, Callable

from app.core import dataset
from app.core.dataset import citation_of
from app.schemas.core import EligibilityRequest

STATUS_ELIGIBLE = "eligible"
STATUS_INELIGIBLE = "ineligible"
STATUS_PENDING = "pending"

STATUS_LABELS = {
    STATUS_ELIGIBLE: "符合",
    STATUS_INELIGIBLE: "不符合",
    STATUS_PENDING: "待核验",
}

DISCLAIMER = "本结论为辅助判断，最终资格以各省教育考试院官方审核结果为准。"

PROGRAM_ORDER = ("national", "college", "local")
PROGRAM_NAMES = {
    "national": "国家专项计划",
    "college": "高校专项计划",
    "local": "地方专项计划",
}

UNFILLED = "未填写"

# 输入字段 → 展示名，用于 missing_fields
FIELD_LABELS = {
    "household_type": "户籍类型",
    "home_county": "户籍所在县",
    "enrollment_county": "学籍所在县",
    "household_years": "户籍连续年限",
    "enrollment_years": "学籍连续年限",
    "parent_household_local": "父母或法定监护人户籍",
}

CheckResult = tuple[bool | None, str, str]


# --------------------------------------------------------------------------- #
# 判定输入与区域索引
# --------------------------------------------------------------------------- #
class _Inputs:
    """一次判定所需的输入。字段缺失一律为 None，语义为"未知"而非"否"。"""

    __slots__ = (
        "province",
        "score",
        "subject_type",
        "household_type",
        "home_county",
        "enrollment_county",
        "household_years",
        "enrollment_years",
        "parent_household_local",
        "registered",
        "special_marks",
    )

    def __init__(self, payload: Any) -> None:
        data: dict[str, Any] = (
            payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
        )
        self.province = str(data.get("province") or "").strip()
        self.score = data.get("score")
        self.subject_type = str(data.get("subject_type") or "").strip()
        self.household_type = str(data.get("household_type") or "未知").strip() or "未知"
        self.home_county = str(data.get("home_county") or "").strip()
        self.enrollment_county = str(data.get("enrollment_county") or "").strip()
        self.household_years = _norm_years(data.get("household_years"))
        self.enrollment_years = _norm_years(data.get("enrollment_years"))
        self.parent_household_local = data.get("parent_household_local")
        self.registered = data.get("registered", True)
        self.special_marks = _norm_marks(data.get("special_marks"))

    def as_dict(self) -> dict[str, Any]:
        return {
            "province": self.province,
            "score": self.score,
            "subject_type": self.subject_type,
            "household_type": self.household_type,
            "home_county": self.home_county,
            "enrollment_county": self.enrollment_county,
            "household_years": self.household_years or 0,
            "enrollment_years": self.enrollment_years or 0,
            "parent_household_local": self.parent_household_local,
            "registered": self.registered,
            "special_marks": list(self.special_marks),
        }


def _norm_years(value: Any) -> int | None:
    """0 或非法值一律视为未知。"""
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return None if number <= 0 else number


def _norm_marks(value: Any) -> tuple[str, ...]:
    """专项标记：去空、去重并保持顺序。"""
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    try:
        items = list(value)
    except TypeError:
        return ()
    result: list[str] = []
    for raw in items:
        key = str(raw).strip()
        if key and key not in result:
            result.append(key)
    return tuple(result)


class _RegionIndex:
    """(省份, 专项) → 区域条目的索引。"""

    def __init__(self, regions: Any) -> None:
        self._map = {(item["province"], item["program"]): item for item in regions}
        self.provinces = {item["province"] for item in self._map.values()}

    def get(self, province: str, program: str) -> dict[str, Any] | None:
        return self._map.get((province, program))

    def entries(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._map.values())


# --------------------------------------------------------------------------- #
# 各类检查（声明式规则的解释执行）
# --------------------------------------------------------------------------- #
def _check_always(rule, inputs: _Inputs, index: _RegionIndex) -> CheckResult:
    return True, "无专项前置条件", "无"


def _check_province_supported(rule, inputs: _Inputs, index: _RegionIndex) -> CheckResult:
    """省份是否在试点范围。未覆盖时返回未知，而不是判定为"不符合"。"""
    required = "属试点省份（" + "、".join(sorted(index.provinces)) + "）" if index.provinces else "属试点省份"
    if inputs.province not in index.provinces:
        return None, inputs.province or UNFILLED, required
    return True, inputs.province, required


def _check_region_verified(rule, inputs: _Inputs, index: _RegionIndex) -> CheckResult:
    program = str(rule.get("params", {}).get("program") or "")
    name = PROGRAM_NAMES.get(program, program)
    required = f"{name}实施区域名单已核验"
    entry = index.get(inputs.province, program)
    if entry is None:
        return None, "该省未录入此专项的实施区域数据", required
    if not entry.get("verified"):
        return None, "名单尚未完成核验录入", required
    return True, "名单已核验", required


def _check_county_in_region(rule, inputs: _Inputs, index: _RegionIndex) -> CheckResult:
    program = str(rule.get("params", {}).get("program") or "")
    name = PROGRAM_NAMES.get(program, program)
    required = f"户籍所在县属{name}实施区域"
    if not inputs.home_county:
        return None, UNFILLED, required
    entry = index.get(inputs.province, program)
    if entry is None or not entry.get("counties"):
        return None, inputs.home_county, required
    counties = {str(item).strip() for item in entry["counties"]}
    if inputs.home_county in counties:
        return True, inputs.home_county, required
    return False, inputs.home_county, required


def _check_min_household_years(rule, inputs: _Inputs, index: _RegionIndex) -> CheckResult:
    need = int(rule.get("params", {}).get("years", 3))
    required = f"连续户籍 ≥ {need} 年"
    if inputs.household_years is None:
        return None, UNFILLED, required
    return inputs.household_years >= need, f"{inputs.household_years} 年", required


def _check_min_enrollment_years(rule, inputs: _Inputs, index: _RegionIndex) -> CheckResult:
    need = int(rule.get("params", {}).get("years", 3))
    required = f"连续学籍 ≥ {need} 年"
    if inputs.enrollment_years is None:
        return None, UNFILLED, required
    return inputs.enrollment_years >= need, f"{inputs.enrollment_years} 年", required


def _check_parent_household_local(rule, inputs: _Inputs, index: _RegionIndex) -> CheckResult:
    required = "父母或法定监护人具有当地户籍"
    value = inputs.parent_household_local
    if value is None:
        return None, UNFILLED, required
    return bool(value), "是" if value else "否", required


def _check_registered(rule, inputs: _Inputs, index: _RegionIndex) -> CheckResult:
    required = "已完成高考报名并通过资格审核"
    value = inputs.registered
    if value is None:
        return None, UNFILLED, required
    return bool(value), "是" if value else "否", required


def _check_household_type_is(rule, inputs: _Inputs, index: _RegionIndex) -> CheckResult:
    want = str(rule.get("params", {}).get("value") or "")
    required = f"户籍类型为{want}"
    actual = inputs.household_type
    if not actual or actual == "未知":
        return None, UNFILLED, required
    return actual == want, actual, required


def _check_enrollment_in_household_county(rule, inputs: _Inputs, index: _RegionIndex) -> CheckResult:
    required = "学籍所在县与户籍所在县一致"
    if not inputs.home_county or not inputs.enrollment_county:
        return None, UNFILLED, required
    same = inputs.enrollment_county == inputs.home_county
    return same, f"学籍 {inputs.enrollment_county} / 户籍 {inputs.home_county}", required


CHECKERS: dict[str, Callable[[dict, _Inputs, _RegionIndex], CheckResult]] = {
    "always": _check_always,
    "province_supported": _check_province_supported,
    "region_verified": _check_region_verified,
    "county_in_region": _check_county_in_region,
    "min_household_years": _check_min_household_years,
    "min_enrollment_years": _check_min_enrollment_years,
    "parent_household_local": _check_parent_household_local,
    "registered": _check_registered,
    "household_type_is": _check_household_type_is,
    "enrollment_in_household_county": _check_enrollment_in_household_county,
}

_RESULT_LABELS = {True: "passed", False: "failed", None: "unknown"}


# --------------------------------------------------------------------------- #
# 判定主流程
# --------------------------------------------------------------------------- #
def _dedupe(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple] = set()
    result: list[dict[str, Any]] = []
    for item in citations:
        key = (item["source_name"], item["source_url"], item["year"])
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _evaluate_pathway(
    pathway: dict[str, Any],
    pathway_rules: list[dict[str, Any]],
    inputs: _Inputs,
    index: _RegionIndex,
) -> dict[str, Any]:
    """对单条途径逐条执行规则，并聚合为三态结论。"""
    reasons: list[dict[str, Any]] = []
    for rule in sorted(pathway_rules, key=lambda item: item.get("order", 0)):
        checker = CHECKERS.get(str(rule.get("check")))
        if checker is None:
            passed, actual, required = None, f"未知检查类型 {rule.get('check')}", "—"
        else:
            passed, actual, required = checker(rule, inputs, index)

        result = _RESULT_LABELS[passed]
        reasons.append(
            {
                "rule_id": rule["rule_id"],
                "title": rule.get("title", ""),
                "text": rule.get("text", ""),
                "result": result,
                "actual": actual,
                "required": required,
                "note": "" if result == "passed" else str(rule.get("remedy") or ""),
                "citation": citation_of(rule),
            }
        )

    if any(item["result"] == "failed" for item in reasons):
        status = STATUS_INELIGIBLE
    elif any(item["result"] == "unknown" for item in reasons):
        status = STATUS_PENDING
    else:
        status = STATUS_ELIGIBLE

    return {
        "pathway_id": pathway["id"],
        "pathway_name": pathway["name"],
        "status": status,
        "status_label": STATUS_LABELS[status],
        # 考生档案中自行标记过该专项（tasks.md 3.5）。
        # 注意：标记只作回显，不参与判定 —— 判定只看事实输入，避免"自述即通过"。
        "marked": pathway["id"] in inputs.special_marks,
        "reasons": reasons,
        "blocking": [item for item in reasons if item["result"] != "passed"],
        "citations": _dedupe([item["citation"] for item in reasons]),
    }


def _missing_fields(inputs: _Inputs) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    if not inputs.household_type or inputs.household_type == "未知":
        missing.append({"field": "household_type", "label": FIELD_LABELS["household_type"]})
    if not inputs.home_county:
        missing.append({"field": "home_county", "label": FIELD_LABELS["home_county"]})
    if not inputs.enrollment_county:
        missing.append({"field": "enrollment_county", "label": FIELD_LABELS["enrollment_county"]})
    if inputs.household_years is None:
        missing.append({"field": "household_years", "label": FIELD_LABELS["household_years"]})
    if inputs.enrollment_years is None:
        missing.append({"field": "enrollment_years", "label": FIELD_LABELS["enrollment_years"]})
    if inputs.parent_household_local is None:
        missing.append(
            {"field": "parent_household_local", "label": FIELD_LABELS["parent_household_local"]}
        )
    return missing


def evaluate(
    payload: EligibilityRequest | dict[str, Any],
    *,
    catalog: Any = None,
    regions: Any = None,
    rules: Any = None,
) -> dict[str, Any]:
    """执行资格自检，返回可报考通道清单与逐条依据。

    catalog / regions / rules 可注入，供测试与管理端规则维护复用；缺省从数据文件加载。
    """
    catalog_data = tuple(catalog if catalog is not None else dataset.load_catalog())
    region_data = tuple(regions if regions is not None else dataset.load_regions())
    rule_data = tuple(rules if rules is not None else dataset.load_rules())

    index = _RegionIndex(region_data)
    inputs = _Inputs(payload)

    rules_by_pathway: dict[str, list[dict[str, Any]]] = {}
    for rule in rule_data:
        rules_by_pathway.setdefault(rule["pathway_id"], []).append(rule)

    conclusions: list[dict[str, Any]] = []
    evaluated: set[str] = set()
    for pathway in catalog_data:
        if not pathway.get("rule_set"):
            continue
        pathway_rules = rules_by_pathway.get(pathway["id"], [])
        if not pathway_rules:
            continue
        conclusions.append(_evaluate_pathway(pathway, pathway_rules, inputs, index))
        evaluated.add(pathway["id"])

    planned = [
        {
            "pathway_id": item["id"],
            "pathway_name": item["name"],
            "status": item.get("status", "数据规划中"),
            "reason": "该通道的判定规则与录取数据尚未接入，如实标注为规划中。",
            "citation": citation_of(item),
        }
        for item in catalog_data
        if item["id"] not in evaluated
    ]

    grouped: dict[str, list[str]] = {STATUS_ELIGIBLE: [], STATUS_PENDING: [], STATUS_INELIGIBLE: []}
    for conclusion in conclusions:
        grouped[conclusion["status"]].append(conclusion["pathway_name"])

    citations = _dedupe(
        [citation for conclusion in conclusions for citation in conclusion["citations"]]
        + [item["citation"] for item in planned]
    )

    return {
        # —— 契约字段（docs/api-contract.md 第 3 节）：中文名称数组，与前端 mock 一致 ——
        "eligible": grouped[STATUS_ELIGIBLE],
        "pending": grouped[STATUS_PENDING],
        "ineligible": grouped[STATUS_INELIGIBLE],
        "profile": inputs.as_dict(),
        "citations": citations,
        # —— 扩展字段（新增，需队长补入契约，见 PR 描述）——
        "conclusions": conclusions,
        "planned": planned,
        "region": check_region(inputs.province, inputs.home_county, regions=region_data),
        "missing_fields": _missing_fields(inputs),
        "disclaimer": DISCLAIMER,
    }


def check_region(
    province: str,
    county: str = "",
    *,
    regions: Any = None,
) -> dict[str, Any]:
    """专项实施区域判定：按省份与县名返回所属专项范围（tasks.md 4.3）。"""
    region_data = tuple(regions if regions is not None else dataset.load_regions())
    index = _RegionIndex(region_data)
    province = str(province or "").strip()
    county = str(county or "").strip()

    in_region: list[dict[str, Any]] = []
    not_in_region: list[dict[str, Any]] = []
    undetermined: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []

    for program in PROGRAM_ORDER:
        name = PROGRAM_NAMES[program]
        entry = index.get(province, program)
        base = {"program": program, "program_name": name}
        if entry is None:
            undetermined.append({**base, "reason": "该省未录入此专项的实施区域数据"})
            continue

        citations.append(citation_of(entry))

        if entry.get("scope") == "province_rural":
            undetermined.append(
                {
                    **base,
                    "reason": "实施区域为全省农村地区，不按县名单判定，以农村户籍为准",
                    "definition": entry.get("definition", ""),
                }
            )
            continue

        if not entry.get("verified") or not entry.get("counties"):
            undetermined.append(
                {
                    **base,
                    "reason": "实施区域名单尚未完成核验录入",
                    "expected_count": entry.get("expected_count"),
                    "definition": entry.get("definition", ""),
                }
            )
            continue

        if not county:
            undetermined.append({**base, "reason": "未提供县名"})
            continue

        if county in {str(item).strip() for item in entry["counties"]}:
            in_region.append({**base, "reason": "属于该专项实施区域"})
        else:
            not_in_region.append({**base, "reason": "不属于该专项实施区域"})

    return {
        "province": province,
        "county": county,
        "in_region": in_region,
        "not_in_region": not_in_region,
        "undetermined": undetermined,
        "citations": _dedupe(citations),
        "disclaimer": DISCLAIMER,
    }
