"""报考约束引擎（产品书 8.5「四道闸门」）—— 纯函数实现。

设计纪律（8.5，不可协商）：

1. **纯函数**：无数据库 IO、无网络、无大模型。所有规则数据由调用方（services 层）
   传入，便于单元测试与离线复算。
2. **同输入必得同输出**；每条结论必须带 ``citation``（来源名称 + URL + 年份）。
3. 规则数据缺失由 services 层返回 ``3001``，本层只负责"已有规则"的判定。
4. ``null``（未填）**不等于**合格：进 ``unknowns[]``，标"待核验"。
5. 本层与 ``app/services/`` 分离：② 写引擎、③ 填规则数据，用 6.2.7 的 JSON 契约对接。

链路（8.5）：

    考生档案 ─► [1 省份规则] ─► [2 选科匹配] ─► [3 身体条件] ─► [4 学费预算]
              ─► 每个志愿单位：eligible / blockers / warnings / unknowns

三档语义（6.2.7 / 8.5，前后端统一，禁止一刀切）：

- 🔴 ``blockers``（``reject``）→ 默认不进推荐候选，但用户主动搜索时仍展示 + 原因
- 🟡 ``warnings``（``not_suitable`` / 超预算 / 单科 / 语种）→ 必须保留，显著标注
- ⚪ ``unknowns``（档案缺项）→ 既不放行也不拦截，标"待核验"
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from app.models.constants import (
    COLOR_VISION_BLIND,
    COLOR_VISION_NORMAL,
    COLOR_VISION_NO_DISTINCT,
    CONSTRAINT_TYPE_BATCH,
    CONSTRAINT_TYPE_FEE,
    CONSTRAINT_TYPE_PHYSICAL,
    CONSTRAINT_TYPE_PROVINCE_RULE,
    CONSTRAINT_TYPE_SUBJECT,
    LEVEL_NOT_SUITABLE,
    LEVEL_REJECT,
    LEVEL_UNKNOWN,
    PHYSICAL_STATE_ABNORMAL,
    PHYSICAL_STATE_UNFILLED,
    RESTRICTION_LEVEL_VALUES,
    RESTRICTION_REJECT,
    SUBJECT_LOGIC_ANY,
    VISION_LINE_48,
    VISION_LINE_50,
)

BLOCKERS = "blockers"
WARNINGS = "warnings"
UNKNOWNS = "unknowns"

# 科目取值
SUBJECT_PHYSICS = "物理"
SUBJECT_HISTORY = "历史"
SUBJECT_UNLIMITED = "不限"
SUBJECT_ANY = ""

# 体检条件名（与 physical_restriction.condition 约定一致）
COND_COLOR_VISION = "色觉"
COND_COLOR_WEAK = "色弱"
COND_COLOR_BLIND = "色盲"
COND_COLOR_NO_DISTINCT = "不能识别红黄绿蓝紫任一色"
COND_VISION = "裸眼视力"
COND_HEPATITIS = "乙肝"
COND_HEIGHT = "身高"
COND_WEIGHT = "体重"
COND_HEARING = "听力"
COND_SMELL = "嗅觉"
COND_STUTTER = "口吃"

# 视力阈值写法 → 判定线
_VISION_THRESHOLDS = {"<5.0": VISION_LINE_50, "<4.8": VISION_LINE_48, "<4.5": 4.5, "5.0": VISION_LINE_50, "4.8": VISION_LINE_48, "4.5": 4.5}


def _hit(
    type_: str,
    level: str,
    detail: str,
    *,
    major_ids: Iterable[Any] | None = None,
    major_names: Iterable[str] | None = None,
    fields: Iterable[str] | None = None,
    citation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """构造一条约束命中记录（契约 8.4 / 产品书 6.2.7 的三档条目形状）。

    ``major_ids`` / ``major_names`` 可选，用于指出受影响专业；
    ``fields`` 用于 ``unknown`` 指明还缺哪些档案项（契约 8.4 示例）。
    """
    hit: dict[str, Any] = {"type": type_, "level": level, "detail": detail}
    ids = [mid for mid in (major_ids or []) if mid is not None]
    if ids:
        hit["major_ids"] = ids
    names = [str(name) for name in (major_names or []) if str(name).strip()]
    if names:
        hit["major_names"] = names
    missing_fields = [str(field) for field in (fields or []) if str(field).strip()]
    if missing_fields:
        hit["fields"] = missing_fields
    if citation:
        hit["citation"] = {
            "source_name": str(citation.get("source_name") or ""),
            "source_url": str(citation.get("source_url") or ""),
            "year": citation.get("year") or 0,
        }
    return hit


def _unfilled(value: Any) -> bool:
    """未填判定：``None`` / 空串 / ``"未填"`` 均视为未填（6.1.4「未填」语义）。"""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() in ("", PHYSICAL_STATE_UNFILLED, "未知")
    return False


def _profile_get(profile: Any, key: str, default: Any = None) -> Any:
    """同时兼容 Mapping 与 pydantic 模型取字段。"""
    if isinstance(profile, Mapping):
        return profile.get(key, default)
    return getattr(profile, key, default)


def _subjects_of(profile: Any) -> list[str]:
    raw = _profile_get(profile, "second_subjects", []) or []
    if isinstance(raw, str):
        return [item.strip() for item in raw.replace("，", ",").split(",") if item.strip() not in ("", "未填", "未知")]
    return [str(item).strip() for item in raw if str(item).strip() not in ("", "未填", "未知")]


# --------------------------------------------------------------------------- #
# 闸门 2｜选科匹配（产品书 8.5；M2-7）
# --------------------------------------------------------------------------- #
def subject_match(profile: Any, requirement: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """判定考生选科是否满足某专业的选科要求。

    教育部四类要求（8.5）：不限 / 只限首选 / 只限再选 / 首选 + 再选。
    ``logic ∈ all|any`` 只作用于再选科目。

    返回 ``None`` 表示通过；否则返回一条命中记录（不符 → ``reject``，未填 → ``unknown``）。
    """
    if not requirement:
        return None

    req_first = str(requirement.get("first_subject") or "").strip()
    req_secondary = [str(x).strip() for x in (requirement.get("secondary_subjects") or []) if str(x).strip()]
    logic = str(requirement.get("logic") or "all").strip().lower()
    citation = requirement.get("citation")
    label = _major_label(requirement)

    def _subject_hit(level: str, detail: str, *, with_citation: bool = False) -> dict[str, Any]:
        return _hit(
            CONSTRAINT_TYPE_SUBJECT, level, detail,
            major_ids=requirement.get("major_ids"),
            major_names=requirement.get("major_names"),
            citation=citation if with_citation else None,
        )

    has_first_rule = req_first not in (SUBJECT_ANY, SUBJECT_UNLIMITED)
    has_secondary_rule = bool(req_secondary)

    if not has_first_rule and not has_secondary_rule:
        return None  # 不限

    cand_first = str(_profile_get(profile, "first_subject", "") or "").strip()
    cand_secondary = _subjects_of(profile)

    # 首选科目缺失 → 待核验（不得默认放行）
    if has_first_rule and _unfilled(cand_first):
        return _subject_hit(
            LEVEL_UNKNOWN, f"未填写首选科目，无法校验{label}的选科要求"
        )
    # 需要再选校验但再选科目缺失 → 待核验
    if has_secondary_rule and not cand_secondary:
        return _subject_hit(
            LEVEL_UNKNOWN, f"未填写再选科目，无法校验{label}的选科要求"
        )

    # 艺术 / 体育类考生报普通类 → 软提示（8.5 选科用例）
    exam_type = str(_profile_get(profile, "exam_type", "普通") or "普通").strip()
    notes: list[str] = []
    if exam_type in ("艺术", "体育"):
        notes.append(f"{exam_type}类考生按普通类选科校验，请核对当年报考政策")

    if has_first_rule and cand_first != req_first:
        return _subject_hit(
            LEVEL_REJECT,
            f"首选科目为「{cand_first}」，{label}要求首选「{req_first}」，不可报",
            with_citation=True,
        )

    if has_secondary_rule:
        hit_names = [s for s in req_secondary if s in cand_secondary]
        missing = [s for s in req_secondary if s not in cand_secondary]
        if logic == SUBJECT_LOGIC_ANY:
            ok = bool(hit_names)
            need = "、".join(req_secondary) + " 任选其一"
        else:
            ok = not missing
            need = "、".join(req_secondary) + " 全部必选"
        if not ok:
            return _subject_hit(
                LEVEL_REJECT,
                f"再选科目需 {need}；你当前选科为 {'、'.join(cand_secondary) or '未填写'}，"
                f"缺少 {'、'.join(missing)}，不可报",
                with_citation=True,
            )

    if notes:
        return _subject_hit(LEVEL_NOT_SUITABLE, "；".join(notes), with_citation=True)
    return None


def _major_label(rule: Mapping[str, Any]) -> str:
    names = rule.get("major_names") or []
    if names:
        return "、".join(str(x) for x in names)
    return str(rule.get("major_name") or "该专业")


# --------------------------------------------------------------------------- #
# 闸门 3｜身体条件（产品书 8.5；M2-8）
# --------------------------------------------------------------------------- #
def _infer_condition_key(restriction: Mapping[str, Any]) -> str:
    """把规则的 condition / detail 归一到一个判定键。"""
    condition = str(restriction.get("condition") or "").strip()
    detail = str(restriction.get("detail") or "")
    for key in (
        COND_COLOR_NO_DISTINCT, COND_COLOR_WEAK, COND_COLOR_BLIND, COND_COLOR_VISION,
        COND_VISION, COND_HEPATITIS, COND_HEIGHT, COND_WEIGHT,
        COND_HEARING, COND_SMELL, COND_STUTTER,
    ):
        if key and (key in condition or key in detail):
            return key
    return condition


def _match_restriction(profile: Any, restriction: Mapping[str, Any]) -> str | None:
    """判断考生是否命中一条身体条件限制。

    返回 ``"hit"`` / ``"miss"`` / ``"unknown"``。
    """
    key = _infer_condition_key(restriction)
    threshold = str(restriction.get("threshold") or "").strip()

    if key in (COND_COLOR_WEAK, COND_COLOR_BLIND, COND_COLOR_NO_DISTINCT, COND_COLOR_VISION):
        color = _profile_get(profile, "color_vision")
        if _unfilled(color):
            return "unknown"
        color = str(color).strip()
        if key == COND_COLOR_WEAK:
            # 色弱：正常以外的色觉异常中，色弱为最轻；色盲与"不能识别"更严重，同样不满足
            return "hit" if color != COLOR_VISION_NORMAL else "miss"
        if key == COND_COLOR_BLIND:
            return "hit" if color in (COLOR_VISION_BLIND, COLOR_VISION_NO_DISTINCT) else "miss"
        if key == COND_COLOR_NO_DISTINCT:
            return "hit" if color == COLOR_VISION_NO_DISTINCT else "miss"
        # 泛"色觉"要求：任一异常即命中
        return "hit" if color != COLOR_VISION_NORMAL else "miss"

    if key == COND_VISION:
        line = None
        for token, value in _VISION_THRESHOLDS.items():
            if token in threshold:
                line = value
                break
        left = _profile_get(profile, "vision_left")
        right = _profile_get(profile, "vision_right")
        # Both eyes are needed to prove the minimum-eye rule; a missing eye is not a pass.
        if _unfilled(left) or _unfilled(right):
            return "unknown"
        if line is None:
            return "unknown"
        worst = min(float(left), float(right))  # 裸眼视力取较差眼
        return "hit" if worst < line else "miss"

    if key == COND_HEPATITIS:
        hepatitis = _profile_get(profile, "hepatitis_b")
        if hepatitis is None:
            return "unknown"
        need_carrier = "携带" in threshold or not threshold
        if need_carrier:
            return "hit" if hepatitis else "miss"
        return "hit" if hepatitis else "miss"

    if key == COND_HEIGHT:
        if "军队院校" in str(restriction.get("condition") or "") or "公安院校" in str(restriction.get("condition") or ""):
            return "unknown"  # 档案没有性别字段，不能套用性别阈值
        height = _profile_get(profile, "height")
        if height is None:
            return "unknown"
        limit = _parse_number(threshold)
        if limit is None:
            return "miss"
        if threshold.strip().startswith("<"):
            return "hit" if height < limit else "miss"
        return "hit" if height < limit else "miss"

    if key == COND_WEIGHT:
        if "BMI" in str(restriction.get("condition") or "").upper() or "BMI" in str(restriction.get("detail") or "").upper():
            return "unknown"  # 复杂区间暂不按体重单字段估算
        weight = _profile_get(profile, "weight")
        if weight is None:
            return "unknown"
        limit = _parse_number(threshold)
        if limit is None:
            return "miss"
        return "hit" if weight < limit else "miss"

    if key in (COND_HEARING, COND_SMELL, COND_STUTTER):
        field = {COND_HEARING: "hearing", COND_SMELL: "smell", COND_STUTTER: "stutter"}[key]
        state = _profile_get(profile, field)
        if _unfilled(state) or str(state).strip() == PHYSICAL_STATE_UNFILLED:
            return "unknown"
        return "hit" if str(state).strip() == PHYSICAL_STATE_ABNORMAL else "miss"

    return "unknown"  # 无法识别的条件，交由调用方决定（保守起见不判合格）


def _parse_number(text: str) -> float | None:
    cleaned = "".join(ch for ch in text if ch.isdigit() or ch == ".")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


_CONDITION_FIELDS: dict[str, tuple[str, ...]] = {
    COND_COLOR_NO_DISTINCT: ("color_vision",),
    COND_COLOR_WEAK: ("color_vision",),
    COND_COLOR_BLIND: ("color_vision",),
    COND_COLOR_VISION: ("color_vision",),
    COND_VISION: ("vision_left", "vision_right"),
    COND_HEPATITIS: ("hepatitis_b",),
    COND_HEIGHT: ("height",),
    COND_WEIGHT: ("weight",),
    COND_HEARING: ("hearing",),
    COND_SMELL: ("smell",),
    COND_STUTTER: ("stutter",),
}


def physical_check(
    profile: Any,
    restrictions: Sequence[Mapping[str, Any]] | None,
    unit: Mapping[str, Any] | None = None,
    *,
    pathway_id: str | None = None,
) -> list[dict[str, Any]]:
    """校验一批身体条件限制，返回命中记录列表。

    ``reject`` → ``blockers`` 档；``not_suitable`` → ``warnings`` 档；
    档案缺项 → ``unknown`` 档（契约 8.4：``unknowns[].fields`` 指明缺哪些档案项）。
    **level 值非法 → 报错不吞**（8.5 边界用例）。
    """
    hits: list[dict[str, Any]] = []
    unit = unit or {}
    unit_major_ids = set(unit.get("major_ids") or [])
    for restriction in restrictions or []:
        scoped_units = restriction.get("scope_unit_ids")
        if scoped_units and str(unit.get("unit_id") or "") not in {str(value) for value in scoped_units}:
            continue
        condition_text = str(restriction.get("condition") or "")
        scope = "military" if "军队院校" in condition_text else "police" if "公安院校" in condition_text else "national"
        if (scope == "military" and pathway_id != "military") or (scope == "police" and pathway_id != "police"):
            continue
        rule_major_ids = set(restriction.get("major_ids") or [])
        if rule_major_ids and not unit_major_ids and not scoped_units:
            continue
        if unit_major_ids and rule_major_ids and not unit_major_ids.intersection(rule_major_ids):
            continue
        level = str(restriction.get("level") or "").strip()
        if level not in RESTRICTION_LEVEL_VALUES:
            raise ValueError(f"physical_restriction.level 取值非法：{level!r}")

        outcome = _match_restriction(profile, restriction)
        if outcome == "miss":
            continue

        detail = str(restriction.get("detail") or "").strip()
        category = str(restriction.get("major_category") or restriction.get("major_name") or "").strip()
        affected_ids = restriction.get("major_ids") or unit.get("major_ids")
        affected_names = restriction.get("major_names") or unit.get("major_names")
        common = {
            "major_ids": affected_ids,
            "major_names": affected_names,
        }
        if outcome == "unknown":
            key = _infer_condition_key(restriction)
            hits.append(
                _hit(
                    CONSTRAINT_TYPE_PHYSICAL, LEVEL_UNKNOWN,
                    detail or f"未填写体检结论，无法校验{category}的身体条件要求",
                    fields=(
                        (["gender"] if key == COND_HEIGHT and ("军队院校" in condition_text or "公安院校" in condition_text) else None)
                        or _CONDITION_FIELDS.get(key)
                        or (["height", "weight"] if "BMI" in condition_text.upper() or "BMI" in detail.upper() else None)
                        or (["major_category", "major_code"] if "适用范围未知" in condition_text else None)
                        or (["corrected_vision"] if "矫正视力" in condition_text or "矫正视力" in detail else None)
                    ),
                    **common,
                )
            )
            continue

        if level == RESTRICTION_REJECT:
            hits.append(
                _hit(
                    CONSTRAINT_TYPE_PHYSICAL, LEVEL_REJECT,
                    detail or f"身体条件不符合{category}的录取要求（不予录取）",
                    citation=restriction.get("citation"),
                    **common,
                )
            )
        else:  # not_suitable
            hits.append(
                _hit(
                    CONSTRAINT_TYPE_PHYSICAL, LEVEL_NOT_SUITABLE,
                    detail or f"身体条件不宜就读{category}（不影响报考，建议谨慎）",
                    citation=restriction.get("citation"),
                    **common,
                )
            )
    return hits


# --------------------------------------------------------------------------- #
# 闸门 4｜学费预算（产品书 8.5；M2-9）
# --------------------------------------------------------------------------- #
def fee_check(profile: Any, tuition: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """学费超出预算 → ``warnings``（软提示，不得隐藏）；学费或预算未知 → ``unknowns``。

    **不得静默放行**（契约 8.1）：缺少学费数据或学费数额未知时，同样返回 ``unknown``，
    而不是 ``None``——``None`` 表示"该闸门确认无问题"，与"无法判断"是两回事。
    """
    if not tuition:
        return _hit(
            CONSTRAINT_TYPE_FEE, LEVEL_UNKNOWN,
            "该志愿单位缺少学费数据，无法校验是否在预算内",
            fields=["tuition"],
        )
    amount = tuition.get("amount")
    budget = _profile_get(profile, "tuition_budget")

    if amount is None:
        return _hit(
            CONSTRAINT_TYPE_FEE, LEVEL_UNKNOWN,
            "该志愿单位学费数额未知，无法校验是否在预算内",
            fields=["tuition"],
        )
    if budget is None:
        return _hit(
            CONSTRAINT_TYPE_FEE, LEVEL_UNKNOWN,
            f"未填写年学费预算，无法校验学费 {amount} 元/年是否在预算内",
            fields=["tuition_budget"],
        )

    try:
        amount_value = float(amount)
        budget_value = float(budget)
    except (TypeError, ValueError):
        return _hit(
            CONSTRAINT_TYPE_FEE, LEVEL_UNKNOWN,
            "学费或预算数值无法解析，无法完成校验",
            fields=["tuition"],
        )

    if amount_value <= budget_value:
        return None

    ownership = str(tuition.get("ownership") or "").strip()
    note = str(tuition.get("note") or "").strip()
    detail = f"学费 {amount_value:.0f} 元/年，超出你的预算上限 {budget_value:.0f} 元"
    if ownership:
        detail += f"（{ownership}）"
    detail += "；可了解国家助学贷款、奖学金与勤工助学政策"
    if note:
        detail += f"。{note}"
    return _hit(CONSTRAINT_TYPE_FEE, LEVEL_NOT_SUITABLE, detail, citation=tuition.get("citation"))


# --------------------------------------------------------------------------- #
# 闸门 1｜省份规则（产品书 8.5；M2-10）
# --------------------------------------------------------------------------- #
def province_rule_check(
    profile: Any, rule: Mapping[str, Any] | None, unit: Mapping[str, Any] | None = None
) -> list[dict[str, Any]]:
    """校验批次是否开放、志愿单位结构是否合法、是否存在兼报冲突。"""
    hits: list[dict[str, Any]] = []
    if not rule:
        return hits

    citation = rule.get("citation")
    unit = unit or {}
    unit_batch = str(unit.get("batch") or "").strip()

    # 批次开放：unit 自带的 batch 必须与模板批次一致（提前批与本科批结构不同）
    rule_batch = str(rule.get("batch") or "").strip()
    if unit_batch and rule_batch and unit_batch != rule_batch:
        hits.append(
            _hit(
                CONSTRAINT_TYPE_BATCH, LEVEL_REJECT,
                f"志愿单位批次为「{unit_batch}」，当前模板为「{rule_batch}」，批次不匹配",
                citation=citation,
            )
        )

    # 兼报互斥：档案意向批次同时勾选了互斥组 → 软提示
    mutex_groups = [str(x).strip() for x in (rule.get("mutex_groups") or []) if str(x).strip()]
    preferences = _profile_get(profile, "batch_preference", []) or []
    if mutex_groups and preferences and len([p for p in preferences if str(p).strip()]) > 1:
        hits.append(
            _hit(
                CONSTRAINT_TYPE_PROVINCE_RULE, LEVEL_NOT_SUITABLE,
                "你勾选了两个及以上意向批次，注意：" + "；".join(mutex_groups),
                citation=citation,
            )
        )
    return hits


# --------------------------------------------------------------------------- #
# 汇总：一个志愿单位过四道闸门
# --------------------------------------------------------------------------- #
def _eligible_of(
    blockers: Sequence[Mapping[str, Any]], unknowns: Sequence[Mapping[str, Any]]
) -> bool | None:
    """契约 8.1 的三态 ``eligible``。

    - ``False``：至少一个 ``blocker``（硬性不符合，优先于 unknown）；
    - ``None`` ：无 blocker 但存在 ``unknown``（资料/规则不足以判断，**不得判为合格**）；
    - ``True`` ：无 blocker 且无 unknown。

    ``warnings`` 不改变 ``eligible``（可报但有风险，不等于不能报）。
    """
    if blockers:
        return False
    if unknowns:
        return None
    return True


def check_units(
    profile: Any,
    items: Sequence[Mapping[str, Any]],
    rules: Mapping[str, Any],
) -> dict[str, Any]:
    """对一批志愿单位逐条过四道闸门，返回三档结果与汇总。

    ``rules`` 由 services 层组装，形状：

        {
          "province_rule": {...} | None,          # 闸门 1 模板
          "subject_requirements": {unit_id: req}, # 闸门 2，按志愿单位
          "physical_restrictions": [ {...}, ... ],# 闸门 3
          "tuition": {unit_id: {...}},            # 闸门 4
        }

    纯函数：同输入必得同输出；空 ``items`` 返回 ``summary.total = 0`` 而非报错。
    """
    province_rule = rules.get("province_rule")
    subject_requirements = rules.get("subject_requirements") or {}
    physical_restrictions = rules.get("physical_restrictions") or []
    tuition_map = rules.get("tuition") or {}
    pathway_id = rules.get("pathway_id")

    results: list[dict[str, Any]] = []
    blocked = warned = unknown = 0

    for item in items or []:
        unit_id = item.get("unit_id")
        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        unknowns: list[dict[str, Any]] = []

        # 闸门 1｜省份规则
        for hit in province_rule_check(profile, province_rule, item):
            (blockers if hit["level"] == LEVEL_REJECT else warnings).append(hit)

        # 闸门 2｜选科（按志愿单位内的专业逐条）
        reqs = subject_requirements.get(unit_id) or []
        for requirement in reqs:
            hit = subject_match(profile, requirement)
            if hit is None:
                continue
            (blockers if hit["level"] == LEVEL_REJECT else unknowns if hit["level"] == LEVEL_UNKNOWN else warnings).append(hit)

        # 闸门 3｜身体条件
        for hit in physical_check(profile, physical_restrictions, item, pathway_id=pathway_id):
            (blockers if hit["level"] == LEVEL_REJECT else unknowns if hit["level"] == LEVEL_UNKNOWN else warnings).append(hit)

        # 闸门 4｜学费
        fee_hit = fee_check(profile, tuition_map.get(unit_id))
        if fee_hit is not None:
            (unknowns if fee_hit["level"] == LEVEL_UNKNOWN else warnings).append(fee_hit)

        eligible = _eligible_of(blockers, unknowns)

        # summary 的四个计数互相独立：单位可同时计入 warned 与 unknown（契约 8.4）。
        # 早期实现用 if/elif 链，有 blocker 的单位不再计入 warned/unknown，属系统性少计。
        if blockers:
            blocked += 1
        if warnings:
            warned += 1
        if unknowns:
            unknown += 1

        citations = _collect_citations(blockers, warnings)
        results.append(
            {
                "unit_id": unit_id,
                "eligible": eligible,
                BLOCKERS: blockers,
                WARNINGS: warnings,
                UNKNOWNS: unknowns,
                "citations": citations,
            }
        )

    return {
        "items": results,
        "summary": {
            "total": len(results),
            "blocked": blocked,
            "warned": warned,
            "unknown": unknown,
        },
    }


def _collect_citations(*groups: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, Any]] = set()
    out: list[dict[str, Any]] = []
    for group in groups:
        for hit in group:
            citation = hit.get("citation")
            if not citation:
                continue
            key = (citation.get("source_name"), citation.get("source_url"), citation.get("year"))
            if key in seen:
                continue
            seen.add(key)
            out.append(dict(citation))
    return out
