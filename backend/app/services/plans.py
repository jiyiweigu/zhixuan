"""志愿方案生成与风险预警（tasks.md 6.3、6.4、6.5）。

与资格判定同源的设计原则：结论由确定性逻辑产出，逐项标注依据，全部事实数据带来源。

- 分档（6.3）：按 score_gap = 考生分数 - 上一年度最低录取分 划入 冲 / 稳 / 保；
  阈值、方案倾向配额见 app/data/plans/strategies.json。
- 排序（6.4）：院校优先 / 专业优先 / 城市优先，档间顺序固定为 冲 → 稳 → 保，
  切换策略只改变档内次序，不破坏梯度。
- 风险预警（6.5）：声明式规则解释执行，见 app/data/plans/risk_rules.json，
  每条风险附等级、说明与规则来源；无来源的规则在加载阶段即被拒绝。

候选数据源当前为演示数据（app/data/plans/candidates_demo.json）。
接入 tasks.md 2.1、2.2 的真实录取数据时，只需替换 dataset.load_candidates 的实现，
本模块的分档、排序与风险逻辑无需改动。
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from app.core import dataset
from app.core.dataset import citation_of

TIER_ORDER = ("冲", "稳", "保")
PRIORITY_OPTIONS = ("院校优先", "专业优先", "城市优先")

TIER_RISK_LEVEL = {"冲": "medium", "稳": "low", "保": "low"}
RISK_LEVEL_ORDER = {"high": 3, "medium": 2, "low": 1}

DISCLAIMER = (
    "本方案基于往年录取数据生成，仅供参考，不构成录取承诺；"
    "填报前请以各省教育考试院与高校当年招生章程发布的信息为准。"
)


# --------------------------------------------------------------------------- #
# 上下文
# --------------------------------------------------------------------------- #
class _PlanContext:
    """一次方案生成所需的输入与中间结果。"""

    __slots__ = (
        "province",
        "score",
        "subject_type",
        "strategy",
        "priority",
        "limit",
        "preferred_majors",
        "preferred_provinces",
        "major_adjust",
        "batch_line",
        "items",
        "tier_counts",
        "total",
    )

    def __init__(self, payload: Any) -> None:
        data: dict[str, Any] = (
            payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
        )
        profile = data.get("profile") or {}
        if hasattr(profile, "model_dump"):
            profile = profile.model_dump()
        profile = dict(profile)

        self.province = str(profile.get("province") or "").strip()
        self.score = int(profile.get("score") or 0)
        self.subject_type = str(profile.get("subject_type") or "").strip()

        self.strategy = str(data.get("strategy") or "稳").strip()
        self.priority = str(data.get("priority") or "院校优先").strip()
        self.limit = int(data.get("limit") or 9)
        self.preferred_majors = [str(item) for item in (data.get("preferred_majors") or [])]
        self.preferred_provinces = [str(item) for item in (data.get("preferred_provinces") or [])]
        self.major_adjust = data.get("major_adjust", True)
        self.batch_line = data.get("batch_line")

        self.items: list[dict[str, Any]] = []
        self.tier_counts: dict[str, int] = {label: 0 for label in TIER_ORDER}
        self.total = 0


# --------------------------------------------------------------------------- #
# 分档与排序（tasks.md 6.3、6.4）
# --------------------------------------------------------------------------- #
def _classify(gap: int, strategies: list[dict[str, Any]]) -> dict[str, Any] | None:
    """把分差划入档位；超出全部区间时返回 None。"""
    for item in strategies:
        if item["min_gap"] <= gap <= item["max_gap"]:
            return item
    return None


def _subject_check(actual: str, required: str) -> tuple[str, str]:
    """判定选科是否满足要求。

    返回 (状态, 说明)，状态为 ok / unmet / unknown。
    考生档案只记录"物理类 / 历史类"这类科类，无法反映具体选考科目，
    因此对"物理+化学"这类附加要求不做武断判定，而是标为需本人确认。
    """
    required_raw = str(required or "").strip()
    if not required_raw:
        return "ok", ""

    def normalize(text: str) -> list[str]:
        for sep in ("+", "、", "，", ",", "/", "和"):
            text = text.replace(sep, "|")
        return [part.strip().removesuffix("类") for part in text.split("|") if part.strip()]

    actual_subjects = normalize(actual)
    required_subjects = normalize(required_raw)
    if not actual_subjects:
        return "unknown", f"未填写科类，无法确认是否满足『{required_raw}』要求"

    base = required_subjects[0]
    if base not in actual_subjects:
        return "unmet", f"本人科类为{actual}，该专业要求{base}，不符合选科要求"

    extra = [item for item in required_subjects[1:] if item not in actual_subjects]
    if extra:
        return "unknown", f"该专业还要求选考{'、'.join(extra)}，请本人确认是否已选考"

    return "ok", ""


def _item_sort_key(item: dict[str, Any], ctx: _PlanContext) -> tuple[int, int]:
    """档内排序键：命中偏好的优先，其次按录取分由高到低。"""
    matched = 0
    if ctx.priority == "专业优先" and item["major"] in ctx.preferred_majors:
        matched = 1
    elif ctx.priority == "城市优先" and (
        item["province"] in ctx.preferred_provinces or item["city"] in ctx.preferred_provinces
    ):
        matched = 1
    return (-matched, -item["min_score"])


def _order_items(items: list[dict[str, Any]], ctx: _PlanContext) -> list[dict[str, Any]]:
    """档间按 冲→稳→保 固定顺序，档内按策略排序。"""
    ordered: list[dict[str, Any]] = []
    for label in TIER_ORDER:
        group = [item for item in items if item["tier"] == label]
        ordered.extend(sorted(group, key=lambda item: _item_sort_key(item, ctx)))
    return ordered


# --------------------------------------------------------------------------- #
# 风险预警检查（tasks.md 6.5）
# --------------------------------------------------------------------------- #
def _risk_tier_empty(rule: Mapping[str, Any], ctx: _PlanContext) -> tuple[bool, str]:
    tier = rule["params"]["tier"]
    count = ctx.tier_counts.get(tier, 0)
    return count == 0, f"方案中『{tier}』档志愿数量为 {count}"


def _risk_tier_count_below(rule: Mapping[str, Any], ctx: _PlanContext) -> tuple[bool, str]:
    tier = rule["params"]["tier"]
    need = int(rule["params"]["count"])
    count = ctx.tier_counts.get(tier, 0)
    # count == 0 的情形由 tier_empty 规则负责，避免重复提示
    return 0 < count < need, f"『{tier}』档仅 {count} 个，少于建议的 {need} 个"


def _risk_tier_ratio_imbalanced(rule: Mapping[str, Any], ctx: _PlanContext) -> tuple[bool, str]:
    if ctx.total < 3:
        return False, ""
    threshold = float(rule["params"]["dominant_ratio"])
    top_label = max(TIER_ORDER, key=lambda label: ctx.tier_counts.get(label, 0))
    top_count = ctx.tier_counts.get(top_label, 0)
    ratio = top_count / ctx.total
    if ratio > threshold:
        return True, f"『{top_label}』档占 {top_count}/{ctx.total}（{ratio:.0%}），分布过于集中"
    return False, ""


def _risk_gradient_too_small(rule: Mapping[str, Any], ctx: _PlanContext) -> tuple[bool, str]:
    min_delta = int(rule["params"]["min_delta"])
    scores = [item["min_score"] for item in ctx.items]
    if len(scores) < 2:
        return False, ""
    tight = [
        (scores[index], scores[index + 1])
        for index in range(len(scores) - 1)
        if scores[index] - scores[index + 1] < min_delta
    ]
    if not tight:
        return False, ""
    preview = "、".join(f"{high}分/{low}分" for high, low in tight[:3])
    return True, f"相邻志愿录取分差过小（{preview}），未形成有效梯度"


def _risk_subject_requirement_unmet(rule: Mapping[str, Any], ctx: _PlanContext) -> tuple[bool, str]:
    unmet: list[str] = []
    unknown: list[str] = []
    for item in ctx.items:
        status, note = _subject_check(ctx.subject_type, item.get("subject_requirement", ""))
        if status == "unmet":
            unmet.append(f"{item['name']}·{item['major']}（{note}）")
        elif status == "unknown":
            unknown.append(f"{item['name']}·{item['major']}（{note}）")
    triggered = bool(unmet or unknown)
    if not triggered:
        return False, ""
    preview = "；".join((unmet + unknown)[:2])
    return True, preview


def _risk_all_in_tier(rule: Mapping[str, Any], ctx: _PlanContext) -> tuple[bool, str]:
    if ctx.total == 0:
        return False, ""
    tier = rule["params"]["tier"]
    return ctx.tier_counts.get(tier, 0) == ctx.total, f"全部 {ctx.total} 个志愿均属『{tier}』档"


def _risk_near_batch_line(rule: Mapping[str, Any], ctx: _PlanContext) -> tuple[bool, str]:
    if ctx.batch_line is None:
        # 批次控制线由数据工程按 tasks.md 2.2 入库，未提供时不判定，避免凭空推测
        return False, ""
    margin = int(rule["params"]["margin"])
    try:
        line = int(ctx.batch_line)
    except (TypeError, ValueError):
        return False, ""
    diff = ctx.score - line
    if diff < 0:
        return True, f"本人 {ctx.score} 分低于批次控制线 {line} 分"
    if diff <= margin:
        return True, f"本人 {ctx.score} 分，仅高出批次控制线 {line} 分 {diff} 分"
    return False, ""


def _risk_major_adjust_refused(rule: Mapping[str, Any], ctx: _PlanContext) -> tuple[bool, str]:
    if ctx.major_adjust is None:
        return False, ""
    return (not ctx.major_adjust), "本人选择不服从专业调剂"


RISK_CHECKS: dict[str, Callable[[Mapping[str, Any], _PlanContext], tuple[bool, str]]] = {
    "tier_empty": _risk_tier_empty,
    "tier_count_below": _risk_tier_count_below,
    "tier_ratio_imbalanced": _risk_tier_ratio_imbalanced,
    "gradient_too_small": _risk_gradient_too_small,
    "subject_requirement_unmet": _risk_subject_requirement_unmet,
    "all_in_tier": _risk_all_in_tier,
    "near_batch_line": _risk_near_batch_line,
    "major_adjust_refused": _risk_major_adjust_refused,
}


def _collect_risks(rule_data: tuple[dict[str, Any], ...], ctx: _PlanContext) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    for rule in rule_data:
        checker = RISK_CHECKS.get(str(rule.get("check")))
        if checker is None:
            continue
        triggered, evidence = checker(rule, ctx)
        if not triggered:
            continue
        risks.append(
            {
                "code": rule["code"],
                "level": rule["level"],
                "title": rule["title"],
                "detail": rule["detail"],
                "evidence": evidence,
                "remedy": rule.get("remedy", ""),
                "citation": citation_of(rule),
            }
        )
    risks.sort(key=lambda item: RISK_LEVEL_ORDER.get(item["level"], 0), reverse=True)
    return risks


# --------------------------------------------------------------------------- #
# 配额
# --------------------------------------------------------------------------- #
def _scale_quota(quota: Mapping[str, int], limit: int) -> dict[str, int]:
    """按志愿总数缩放各档配额，用最大余数法修正舍入。"""
    base = sum(quota.values()) or 1
    exact = {label: value * limit / base for label, value in quota.items()}
    scaled = {label: int(value) for label, value in exact.items()}
    remainder = limit - sum(scaled.values())
    for label in sorted(exact, key=lambda key: exact[key] - scaled[key], reverse=True):
        if remainder <= 0:
            break
        scaled[label] += 1
        remainder -= 1
    return scaled


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


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def build_plan(
    payload: Any,
    *,
    candidates: Any = None,
    strategies: Any = None,
    risk_rules: Any = None,
) -> dict[str, Any]:
    """生成冲—稳—保志愿方案并给出风险预警。

    candidates / strategies / risk_rules 可注入，供测试与管理端复用；缺省从数据文件加载。
    """
    strategy_config: dict[str, Any] = (
        dict(strategies) if strategies is not None else dataset.load_strategy_config()
    )
    strategy_list: list[dict[str, Any]] = list(strategy_config.get("strategies") or [])
    plan_profiles: dict[str, Any] = dict(strategy_config.get("plan_profiles") or {})
    out_of_range: dict[str, str] = dict(strategy_config.get("out_of_range") or {})
    candidate_data = tuple(candidates if candidates is not None else dataset.load_candidates())
    rule_data = tuple(risk_rules if risk_rules is not None else dataset.load_risk_rules())

    ctx = _PlanContext(payload)

    # —— 分档 ——
    classified: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for candidate in candidate_data:
        # 只保留同一省份的招生数据（跨省招生计划差异由数据层体现，此处为演示口径）
        if candidate.get("province") and ctx.province and candidate["province"] != ctx.province:
            pass  # 演示数据中保留外省院校，以便演示地域偏好；真实实现按招生计划过滤
        gap = ctx.score - int(candidate["min_score"])
        tier = _classify(gap, strategy_list)
        if tier is None:
            reason = out_of_range.get("too_high" if gap < 0 else "too_low", "超出档位区间")
            excluded.append(
                {
                    "school_id": candidate["school_id"],
                    "name": candidate["name"],
                    "major": candidate.get("major", ""),
                    "min_score": candidate["min_score"],
                    "score_gap": gap,
                    "reason": reason,
                }
            )
            continue

        status, subject_note = _subject_check(ctx.subject_type, candidate.get("subject_requirement", ""))
        item: dict[str, Any] = {
            "school_id": candidate["school_id"],
            "name": candidate["name"],
            "province": candidate.get("province", ""),
            "city": candidate.get("city", ""),
            "major": candidate.get("major", ""),
            "subject_requirement": candidate.get("subject_requirement", ""),
            "tier": tier["label"],
            "min_score": candidate["min_score"],
            "admission_year": candidate.get("admission_year"),
            "score_gap": gap,
            "risk_level": TIER_RISK_LEVEL.get(tier["label"], "medium"),
            "subject_status": status,
            "reasons": [],
            "citations": [citation_of(candidate)],
            **citation_of(candidate),
        }
        if status == "unmet":
            item["risk_level"] = "high"
        elif status == "unknown" and item["risk_level"] == "low":
            item["risk_level"] = "medium"
        item["reasons"].append(
            f"{candidate.get('admission_year')} 年最低录取分 {candidate['min_score']}，"
            f"与本人 {ctx.score} 分相差 {gap:+d} 分，属『{tier['label']}』档。"
        )
        if subject_note:
            item["reasons"].append(subject_note)
        classified.append(item)

    # —— 排序：先档间，后档内 ——
    ordered = _order_items(classified, ctx)

    # —— 按配额选取 ——
    # 倾向值非法时回退到「稳」，避免因数据缺项生成空方案
    if ctx.strategy not in plan_profiles and plan_profiles:
        ctx.strategy = "稳" if "稳" in plan_profiles else next(iter(plan_profiles))
    profile_cfg = plan_profiles.get(ctx.strategy) or {}
    raw_quota = profile_cfg.get("quota") or {label: 0 for label in TIER_ORDER}
    quota = _scale_quota(raw_quota, max(1, ctx.limit))
    selected: list[dict[str, Any]] = []
    shortage: list[dict[str, Any]] = []
    for label in TIER_ORDER:
        group = [item for item in ordered if item["tier"] == label]
        want = quota.get(label, 0)
        selected.extend(group[:want])
        if len(group) < want:
            shortage.append({"tier": label, "expected": want, "actual": len(group)})

    ctx.items = selected
    ctx.total = len(selected)
    ctx.tier_counts = {label: sum(1 for item in selected if item["tier"] == label) for label in TIER_ORDER}

    # —— 排序依据补充（在最终顺序确定后写入，保证 reasons 与实际次序一致）——
    for index, item in enumerate(selected):
        item["order"] = index + 1
        if ctx.priority == "专业优先" and item["major"] in ctx.preferred_majors:
            item["reasons"].append(f"命中偏好专业（{item['major']}），在『{item['tier']}』档内优先排列。")
        elif ctx.priority == "城市优先" and (
            item["province"] in ctx.preferred_provinces or item["city"] in ctx.preferred_provinces
        ):
            item["reasons"].append(
                f"命中偏好地区（{item['province']}{item['city']}），在『{item['tier']}』档内优先排列。"
            )
        elif ctx.priority == "院校优先":
            item["reasons"].append("按录取分由高到低排列（办学层次数据待 tasks.md 2.5 接入）。")

    # —— 风险预警 ——
    # 空方案不逐条报"缺少某档"，否则会堆出多条同源提示；此时由 summary 说明原因
    risks = _collect_risks(rule_data, ctx) if ctx.total else []

    risk_notes = [
        f"[{item['level'].upper()}] {item['title']}：{item['detail']}"
        + (f"（{item['evidence']}）" if item.get("evidence") else "")
        for item in risks
    ]
    if ctx.total:
        for item in shortage:
            risk_notes.append(
                f"[INFO] 『{item['tier']}』档候选不足：目标 {item['expected']} 个，"
                f"实际仅 {item['actual']} 个，未硬凑。"
            )

    citations = _dedupe(
        [citation for item in selected for citation in item["citations"]]
        + [item["citation"] for item in risks]
        + [citation_of(config) for config in strategy_list]
    )

    tier_text = "、".join(f"{label} {ctx.tier_counts[label]} 个" for label in TIER_ORDER if ctx.tier_counts[label])
    summary = (
        f"按『{ctx.strategy}』倾向生成 {ctx.total} 个志愿：{tier_text}。"
        f"排序采用『{ctx.priority}』。"
    ) if ctx.total else "当前条件下未匹配到可纳入方案的志愿，请检查分数与省份设置。"

    return {
        # —— 契约字段（docs/api-contract.md 第 5 节）——
        "items": selected,
        "risk_notes": risk_notes,
        "citations": citations,
        # —— 扩展字段（新增，需队长补入契约，见 PR 描述）——
        "strategy": ctx.strategy,
        "priority": ctx.priority,
        "tiers": ctx.tier_counts,
        "quota": quota,
        "shortage": shortage,
        "excluded": excluded,
        "risks": risks,
        "summary": summary,
        "data_status": "演示数据（非官方），真实录取数据请以省教育考试院发布为准",
        "disclaimer": DISCLAIMER,
    }
