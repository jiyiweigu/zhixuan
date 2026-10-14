"""跨层词表归一（契约「统一约定 · 跨层词表」）。

把 ③ ``data/`` 侧的**自然语言取值**收敛到库表 / 契约的**枚举取值**。
归一表是显式的、可审计的：任何未命中别名的取值一律返回 ``None``，
由调用方跳过并上报，**不做模糊匹配、不猜**。

已确认的三类断裂（见 ``数据入库对接发现与待裁决_费.md``）：

1. ``source_type``：③ 用中文（官方 / 高校官网 / 其他），模型注释用英文码位。
2. ``data_status``：③ 的 ``pathway`` 用 ``pending``，跨层词表只有
   available / partial / schema_only / unavailable。
3. ``exam_type``：③ 的 ``category_group`` 用 ``普通类`` / ``历史、物理科目组`` /
   ``艺术类 / 体育类``，跨层词表只有 普通 / 艺术 / 体育。
   ``艺术类 / 体育类`` 一行覆盖两类，唯一键无法承载 → 归一失败，跳过上报。
"""

from __future__ import annotations

from app.models.constants import (
    DATA_STATUS_AVAILABLE,
    DATA_STATUS_PARTIAL,
    DATA_STATUS_SCHEMA_ONLY,
    DATA_STATUS_UNAVAILABLE,
    DATA_STATUS_VALUES,
    EXAM_TYPE_ART,
    EXAM_TYPE_NORMAL,
    EXAM_TYPE_SPORTS,
    EXAM_TYPE_VALUES,
    PROVINCE_CODE_HENAN,
    PROVINCE_CODE_JIANGXI,
    PROVINCE_NAME_BY_CODE,
)

# --------------------------------------------------------------------------- #
# source_type：中文 → 英文码位
# --------------------------------------------------------------------------- #
SOURCE_TYPE_ALIAS: dict[str, str] = {
    "官方": "official",
    "高校官网": "school",
    "院校官网": "school",
    "权威媒体": "media",
    "媒体": "media",
    "其他": "other",
}

# --------------------------------------------------------------------------- #
# data_status：③ 自造值 → 跨层词表
# --------------------------------------------------------------------------- #
DATA_STATUS_ALIAS: dict[str, str] = {
    # 数据未采到、仅有结构 → schema_only（不是 unavailable：表结构已就绪）
    "pending": DATA_STATUS_SCHEMA_ONLY,
    # ③ 在 regions / pathways 里用的「已核验」，语义上等价于 available
    "verified": DATA_STATUS_AVAILABLE,
    "available": DATA_STATUS_AVAILABLE,
    "partial": DATA_STATUS_PARTIAL,
    "schema_only": DATA_STATUS_SCHEMA_ONLY,
    "unavailable": DATA_STATUS_UNAVAILABLE,
}

# --------------------------------------------------------------------------- #
# exam_type：数据源 category_group → 契约枚举
# --------------------------------------------------------------------------- #
EXAM_TYPE_ALIAS: dict[str, str] = {
    "普通": EXAM_TYPE_NORMAL,
    "普通类": EXAM_TYPE_NORMAL,
    # 江西 3+1+2 的普通类按首选科目分组，考试类型仍是「普通」
    "历史、物理科目组": EXAM_TYPE_NORMAL,
    "物理类": EXAM_TYPE_NORMAL,
    "历史类": EXAM_TYPE_NORMAL,
    "艺术": EXAM_TYPE_ART,
    "艺术类": EXAM_TYPE_ART,
    "体育": EXAM_TYPE_SPORTS,
    "体育类": EXAM_TYPE_SPORTS,
}

# --------------------------------------------------------------------------- #
# 省份
# --------------------------------------------------------------------------- #
_PROVINCE_NAME_ALIAS: dict[str, str] = {
    "河南省": PROVINCE_NAME_BY_CODE[PROVINCE_CODE_HENAN],
    "河南": PROVINCE_NAME_BY_CODE[PROVINCE_CODE_HENAN],
    "江西省": PROVINCE_NAME_BY_CODE[PROVINCE_CODE_JIANGXI],
    "江西": PROVINCE_NAME_BY_CODE[PROVINCE_CODE_JIANGXI],
}

_PROVINCE_CODE_ALIAS: dict[str, str] = {
    PROVINCE_CODE_HENAN: PROVINCE_CODE_HENAN,
    "410000": PROVINCE_CODE_HENAN,
    f"{PROVINCE_CODE_HENAN}0000": PROVINCE_CODE_HENAN,
    PROVINCE_CODE_JIANGXI: PROVINCE_CODE_JIANGXI,
    "360000": PROVINCE_CODE_JIANGXI,
    f"{PROVINCE_CODE_JIANGXI}0000": PROVINCE_CODE_JIANGXI,
}


def source_type_of(value: str) -> str | None:
    """来源类型归一；未收录返回 None（原样写入会污染枚举，故宁可留空）。"""
    raw = str(value or "").strip()
    if not raw:
        return None
    return SOURCE_TYPE_ALIAS.get(raw, raw if raw.isascii() else None)


def data_status_of(value: str) -> str | None:
    """数据完备度归一；未命中跨层词表返回 None。"""
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw in DATA_STATUS_VALUES:
        return raw
    return DATA_STATUS_ALIAS.get(raw)


def exam_type_of(value: str) -> str | None:
    """考试类型归一；``艺术类 / 体育类`` 这类一行两类返回 None，由调用方跳过上报。"""
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw in EXAM_TYPE_VALUES:
        return raw
    return EXAM_TYPE_ALIAS.get(raw)


def province_name_of(value: str) -> str | None:
    """省名归一（``河南省`` → ``河南``）；未收录返回 None。"""
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw in _PROVINCE_NAME_ALIAS:
        return _PROVINCE_NAME_ALIAS[raw]
    return PROVINCE_NAME_BY_CODE.get(raw)


def province_code_of(value: str) -> str | None:
    """两位省代码归一（``410000`` → ``41``）；未收录返回 None。"""
    raw = str(value or "").strip()
    if not raw:
        return None
    return _PROVINCE_CODE_ALIAS.get(raw)
