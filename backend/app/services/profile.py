"""考生档案业务逻辑（产品书 6.1.4 / 6.1.5；tasks.md 3.4、3.5）。

- 读写：一个用户一份档案，首次读取时自动建立（get_or_create）；
- 校验：分数区间由 Pydantic 拦截（>750 或负数 → 1001）；专项标记必须是已知途径（写入口校验）；
- 局部更新：按「请求显式提供的字段」合并，未提供的字段保持原值，
  避免两段式档案向导只提交第一段时把第二段内容清空；
- completenes：6.1.5 要求 PUT 响应附加 ``completeness: {percent, missing[]}``（M2-13），
  未填项进 ``missing``，前端据此渲染进度条与"未填项影响哪类推荐"提示。

字段名对齐产品书 6.1.4（与前端 types/api.d.ts 的 Profile 同口径）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core import dataset
from app.core.response import BizCode, BizError
from app.db.base import utcnow
from app.models.constants import PHYSICAL_STATE_UNFILLED
from app.models.profile import Profile

# 可写入档案的字段（产品书 6.1.4 可写字段；不含 profile_id 与三个 has_*_special 写回标记）
PROFILE_FIELDS: tuple[str, ...] = (
    "province",
    "exam_type",
    "first_subject",
    "second_subjects",
    "subject_type",
    "score",
    "rank",
    "household_type",
    "home_county",
    "home_county_code",
    "school_years",
    "enrollment_county",
    "household_years",
    "enrollment_years",
    "parent_household_local",
    "preferred_cities",
    "preferred_majors",
    "tuition_budget",
    "color_vision",
    "vision_left",
    "vision_right",
    "height",
    "weight",
    "hepatitis_b",
    "hearing",
    "smell",
    "stutter",
    "batch_preference",
    "accept_adjustment",
)

# 约束校验可写回的字段（6.2.8：写回 accept_adjustment 等）
CONSTRAINT_WRITABLE: tuple[str, ...] = (
    "exam_type",
    "first_subject",
    "second_subjects",
    "score",
    "rank",
    "household_type",
    "home_county",
    "home_county_code",
    "school_years",
    "tuition_budget",
    "color_vision",
    "vision_left",
    "vision_right",
    "height",
    "weight",
    "hepatitis_b",
    "hearing",
    "smell",
    "stutter",
    "batch_preference",
    "accept_adjustment",
)

# 影响推荐质量的关键字段（M2-13「未填项影响哪类推荐」）
COMPLETENESS_FIELDS: tuple[str, ...] = (
    "province",
    "exam_type",
    "first_subject",
    "second_subjects",
    "score",
    "rank",
    "household_type",
    "home_county",
    "school_years",
    "tuition_budget",
    "color_vision",
    "vision_left",
    "vision_right",
)

# 偏好字段（tasks.md 3.5），与 POST /api/plans 的请求字段同名
PREFERENCE_FIELDS: tuple[str, ...] = (
    "strategy",
    "priority",
    "preferred_majors",
    "preferred_provinces",
    "major_adjust",
)

# 资格自检时可用档案补全的字段（含专项标记）
ELIGIBILITY_FIELDS: tuple[str, ...] = PROFILE_FIELDS + ("special_marks",)

DEFAULT_PREFERENCES: dict[str, Any] = {
    "strategy": "稳",
    "priority": "院校优先",
    "preferred_majors": [],
    "preferred_provinces": [],
    "major_adjust": True,
}

_EMPTY_PROFILE: dict[str, Any] = {
    "province": "河南",
    "exam_type": "普通",
    "first_subject": "",
    "second_subjects": [],
    "subject_type": "物理类",
    "score": 0,
    "rank": None,
    "household_type": None,
    "home_county": "",
    "home_county_code": "",
    "school_years": 0,
    "enrollment_county": "",
    "household_years": 0,
    "enrollment_years": 0,
    "parent_household_local": None,
    "preferred_cities": [],
    "preferred_majors": [],
    "tuition_budget": None,
    "color_vision": None,
    "vision_left": None,
    "vision_right": None,
    "height": None,
    "weight": None,
    "hepatitis_b": None,
    "hearing": None,
    "smell": None,
    "stutter": None,
    "batch_preference": [],
    "accept_adjustment": None,
    "special_marks": [],
}

# 契约 §8.1「可空档案项统一用 null 表示未提供」。
# 数据库列历史上以哨兵字符串承载同一语义（列非空，改动需迁移），
# 因此在服务层做一次收敛，保证 API 边界只有 null：
#   read  —— 哨兵 → None
#   write —— None  → 哨兵
# 判定引擎（app/engine/constraints.py）对 None / "" / "未填" 一视同仁，
# 收敛不改变任何"未填不默认放行"的语义。
_SENTINEL_STRINGS: tuple[str, ...] = ("", PHYSICAL_STATE_UNFILLED, "未知")
_DB_SENTINEL: dict[str, str] = {
    "household_type": "未知",
    "hearing": PHYSICAL_STATE_UNFILLED,
    "smell": PHYSICAL_STATE_UNFILLED,
    "stutter": PHYSICAL_STATE_UNFILLED,
}


def _to_api(field: str, value: Any) -> Any:
    """读：DB 哨兵 → None。"""
    if field in _DB_SENTINEL and isinstance(value, str) and value.strip() in _SENTINEL_STRINGS:
        return None
    return value


def _to_db(field: str, value: Any) -> Any:
    """写：None → DB 哨兵（对应列非空）。"""
    if field in _DB_SENTINEL and value is None:
        return _DB_SENTINEL[field]
    return value


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _filled(value: Any) -> bool:
    """判断字段是否已填（产品书 6.1.4「null = 未填」口径）。"""
    if value is None:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip() not in ("", PHYSICAL_STATE_UNFILLED, "未知")
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def completeness(data: Mapping[str, Any]) -> dict[str, Any]:
    """档案完成度：``{percent, missing[]}``（产品书 6.1.5 / M2-13）。"""
    missing = [field for field in COMPLETENESS_FIELDS if not _filled(data.get(field))]
    total = len(COMPLETENESS_FIELDS)
    percent = round((total - len(missing)) * 100 / total) if total else 100
    return {"percent": percent, "missing": missing}


def profile_dict(profile: Profile | None) -> dict[str, Any]:
    """档案的对外表示（产品书 6.1.4 Profile 对象）。"""
    if profile is None:
        data = {**_EMPTY_PROFILE, "special_marks": []}
        data["preferences"] = dict(DEFAULT_PREFERENCES)
        data["updated_at"] = None
        data["has_national_special"] = False
        data["has_local_special"] = False
        data["has_college_special"] = False
        return data

    data: dict[str, Any] = {
        field: _to_api(field, getattr(profile, field, None)) for field in PROFILE_FIELDS
    }
    for mark in ("has_national_special", "has_local_special", "has_college_special"):
        data[mark] = bool(getattr(profile, mark, False))
    data["special_marks"] = list(profile.special_marks or [])
    data["preferences"] = {**DEFAULT_PREFERENCES, **(profile.preferences or {})}
    data["updated_at"] = _iso(profile.updated_at)
    return data


def get_or_create(db: Session, user_id: str) -> dict[str, Any]:
    """读取档案；不存在则建立一份空档案（首次进入档案页即可用）。"""
    profile = db.get(Profile, user_id)
    if profile is None:
        profile = Profile(user_id=user_id)
        db.add(profile)
        db.commit()
    data = profile_dict(profile)
    data["completeness"] = completeness(data)
    return data


def get_saved(db: Session, user_id: str) -> dict[str, Any]:
    """读取已保存档案（不建立），供"补全请求"使用。"""
    return profile_dict(db.get(Profile, user_id))


def validate_marks(marks: Sequence[str]) -> list[str]:
    """专项标记必须是已知途径：接受途径 id 或中文名称，统一存为 id。"""
    catalog = dataset.load_catalog()
    by_id = {str(item["id"]): str(item["id"]) for item in catalog}
    by_name = {str(item["name"]): str(item["id"]) for item in catalog}

    result: list[str] = []
    unknown: list[str] = []
    for raw in marks:
        key = str(raw).strip()
        if not key:
            continue
        resolved = by_id.get(key) or by_name.get(key)
        if resolved is None:
            unknown.append(key)
        elif resolved not in result:
            result.append(resolved)

    if unknown:
        raise BizError(
            "专项标记取值不合法："
            + "、".join(unknown)
            + "；可用取值见 GET /api/pathways 的 id 与 name",
            BizCode.PARAM_ERROR,
        )
    return result


def save(db: Session, user_id: str, payload: BaseModel) -> dict[str, Any]:
    """保存档案：只更新请求中显式提供的字段；响应附加 completeness（6.1.5）。"""
    profile = db.get(Profile, user_id)
    if profile is None:
        profile = Profile(user_id=user_id)
        db.add(profile)

    provided = payload.model_dump(exclude_unset=True)
    provided.pop("preferences", None)
    fields_set = set(payload.model_fields_set or set())

    # 嵌套模型需要单独取"显式提供的子字段"，否则会把未提交的偏好项重置为默认值
    nested_preferences: dict[str, Any] = {}
    if "preferences" in fields_set:
        nested_preferences = payload.preferences.model_dump(exclude_unset=True)

    for field in PROFILE_FIELDS:
        if field in provided:
            setattr(profile, field, _to_db(field, provided[field]))

    if "special_marks" in provided:
        profile.special_marks = validate_marks(provided["special_marks"])

    if nested_preferences:
        profile.preferences = {**(profile.preferences or {}), **nested_preferences}

    profile.updated_at = utcnow()
    db.commit()

    data = profile_dict(profile)
    data["completeness"] = completeness(data)
    return data


def save_from_constraint_profile(
    db: Session, user_id: str, payload: BaseModel
) -> dict[str, Any]:
    """把资格校验请求里显式提供的档案字段写回（产品书 6.2.8）。"""
    profile = db.get(Profile, user_id)
    if profile is None:
        profile = Profile(user_id=user_id)
        db.add(profile)

    provided = payload.model_dump(exclude_unset=True)
    changed = False
    for field in CONSTRAINT_WRITABLE:
        value = provided.get(field)
        if field in provided and value is not None:
            setattr(profile, field, value)
            changed = True
    if changed:
        profile.updated_at = utcnow()
        db.commit()

    data = profile_dict(profile)
    data["completeness"] = completeness(data)
    return data


def meaningful(value: Any) -> bool:
    """判断已保存的值是否可用于补全请求：空串 / 空列表 / 0 / None 视为未填写。"""
    if value is None:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, (str, list, tuple, set, dict)):
        return len(value) > 0
    return True


def merge_saved(
    payload: BaseModel,
    saved: Mapping[str, Any] | None,
    fields: Sequence[str],
) -> dict[str, Any]:
    """用已保存档案补全请求中「未显式提供」的字段（tasks.md 3.5）。

    客户端显式传值一律以客户端为准，只在字段缺席时回退到档案。
    """
    merged = payload.model_dump()
    if not saved:
        return merged
    provided = set(payload.model_fields_set or set())
    for field in fields:
        if field in provided:
            continue
        value = saved.get(field)
        if meaningful(value):
            merged[field] = value
    return merged


def saved_preferences(saved: Mapping[str, Any] | None) -> dict[str, Any]:
    """取出档案中的偏好字段，用于补全方案生成请求。"""
    if not saved:
        return {}
    preferences = saved.get("preferences") or {}
    return {key: preferences[key] for key in PREFERENCE_FIELDS if key in preferences}
