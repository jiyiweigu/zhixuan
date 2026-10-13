"""途径、规则、区域名单与志愿方案数据集：加载与来源强制校验。

约定（docs/api-contract.md 统一约定 + tasks.md 2.6）：
所有事实数据必须携带来源三要素 source_name / source_url / year，
缺失则拒绝加载并抛出 DataSourceError —— 宁可接口不可用，也不输出无来源结论。

数据文件位于 backend/app/data/ 下，由数据工程按 tasks.md 2.1、2.2、2.3、2.4、2.5 更新；
本模块只负责加载与校验，不含任何判定逻辑（判定见 app/services/ 下同名业务模块）。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.models.constants import RELIABILITY_OFFICIAL, RELIABILITY_UNOFFICIAL

DATA_ROOT = Path(__file__).resolve().parent.parent / "data"

CITATION_FIELDS = ("source_name", "source_url", "year")
MIN_YEAR = 2000
MAX_YEAR = 2100


class DataSourceError(RuntimeError):
    """数据集缺失来源三要素或结构非法，拒绝加载。"""


def _read_json(relative_path: str) -> dict[str, Any]:
    path = DATA_ROOT / relative_path
    if not path.is_file():
        raise DataSourceError(f"数据集不存在：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DataSourceError(f"数据集不是合法 JSON：{path}（{exc}）") from exc
    if not isinstance(payload, dict):
        raise DataSourceError(f"数据集根节点必须是对象：{path}")
    return payload


def validate_citation(record: dict[str, Any], context: str) -> None:
    """校验来源三要素，任一缺失或非法即抛错。"""
    missing = [
        field
        for field in CITATION_FIELDS
        if record.get(field) is None
        or (isinstance(record.get(field), str) and not str(record[field]).strip())
    ]
    if missing:
        raise DataSourceError(f"{context} 缺少来源字段：{', '.join(missing)}")

    year = record.get("year")
    if isinstance(year, bool) or not isinstance(year, int) or not MIN_YEAR <= year <= MAX_YEAR:
        raise DataSourceError(f"{context} 的 year 非法：{year!r}，应为 {MIN_YEAR}-{MAX_YEAR} 的整数")


def citation_of(record: dict[str, Any]) -> dict[str, Any]:
    """抽取来源三要素，用于响应体中的 citations。"""
    return {field: record[field] for field in CITATION_FIELDS}


# --------------------------------------------------------------------------- #
# 升学途径（tasks.md 4.1）
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def load_catalog() -> tuple[dict[str, Any], ...]:
    """加载升学途径目录。"""
    pathways = _read_json("pathways/catalog.json").get("pathways") or []
    seen: set[str] = set()
    for item in pathways:
        pathway_id = str(item.get("id") or "")
        if not pathway_id:
            raise DataSourceError("途径条目缺少 id")
        if pathway_id in seen:
            raise DataSourceError(f"途径 id 重复：{pathway_id}")
        seen.add(pathway_id)
        if not str(item.get("name") or "").strip():
            raise DataSourceError(f"途径 {pathway_id} 缺少 name")
        validate_citation(item, f"途径 {pathway_id}")
    return tuple(pathways)


# --------------------------------------------------------------------------- #
# 专项实施区域（tasks.md 2.3、4.3）
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def load_regions() -> tuple[dict[str, Any], ...]:
    """加载专项计划实施区域名单。"""
    regions = _read_json("pathways/region_quotas.json").get("regions") or []
    for item in regions:
        context = f"区域条目 {item.get('province')}/{item.get('program')}"
        if not str(item.get("province") or "").strip():
            raise DataSourceError(f"{context} 缺少 province")
        if not str(item.get("program") or "").strip():
            raise DataSourceError(f"{context} 缺少 program")
        # 已核验的自名单区域必须有内容，避免"标了已核验却是空名单"导致静默误判
        if item.get("verified") and item.get("scope") == "county_list" and not item.get("counties"):
            raise DataSourceError(f"{context} 标记为已核验（verified=true）但县名单为空")
        validate_citation(item, context)
    return tuple(regions)


# --------------------------------------------------------------------------- #
# 资格判定规则（tasks.md 4.2、8.6）
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def load_rules() -> tuple[dict[str, Any], ...]:
    """加载路径资格判定规则库。"""
    rules = _read_json("pathways/eligibility_rules.json").get("rules") or []
    seen: set[str] = set()
    for rule in rules:
        rule_id = str(rule.get("rule_id") or "")
        if not rule_id:
            raise DataSourceError("规则缺少 rule_id")
        if rule_id in seen:
            raise DataSourceError(f"规则 ID 重复：{rule_id}")
        seen.add(rule_id)
        if not str(rule.get("pathway_id") or "").strip():
            raise DataSourceError(f"规则 {rule_id} 缺少 pathway_id")
        if not str(rule.get("check") or "").strip():
            raise DataSourceError(f"规则 {rule_id} 缺少 check 类型")
        validate_citation(rule, f"规则 {rule_id}")
    return tuple(rules)


# --------------------------------------------------------------------------- #
# 志愿方案：档位定义、风险规则、候选数据（tasks.md 6.3、6.4、6.5）
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def load_strategy_config() -> dict[str, Any]:
    """加载冲—稳—保档位定义，并校验档位区间不重叠。"""
    payload = _read_json("plans/strategies.json")
    strategies = payload.get("strategies") or []
    if not strategies:
        raise DataSourceError("档位定义不能为空")

    for item in strategies:
        label = str(item.get("label") or "")
        context = f"档位 {label or '?'}"
        if not label:
            raise DataSourceError("档位缺少 label")
        for field in ("min_gap", "max_gap"):
            if not isinstance(item.get(field), int):
                raise DataSourceError(f"{context} 的 {field} 必须是整数")
        if item["min_gap"] > item["max_gap"]:
            raise DataSourceError(f"{context} 的 min_gap 大于 max_gap")
        validate_citation(item, context)

    ordered = sorted(strategies, key=lambda item: item["min_gap"])
    for previous, current in zip(ordered, ordered[1:]):
        if current["min_gap"] <= previous["max_gap"]:
            raise DataSourceError(
                f"档位区间重叠：{previous['label']} 与 {current['label']}"
            )
    return payload


@lru_cache(maxsize=1)
def load_risk_rules() -> tuple[dict[str, Any], ...]:
    """加载志愿方案风险预警规则。"""
    rules = _read_json("plans/risk_rules.json").get("rules") or []
    seen: set[str] = set()
    for rule in rules:
        code = str(rule.get("code") or "")
        if not code:
            raise DataSourceError("风险规则缺少 code")
        if code in seen:
            raise DataSourceError(f"风险规则 code 重复：{code}")
        seen.add(code)
        for field in ("check", "level", "title", "detail"):
            if not str(rule.get(field) or "").strip():
                raise DataSourceError(f"风险规则 {code} 缺少 {field}")
        validate_citation(rule, f"风险规则 {code}")
    return tuple(rules)


@lru_cache(maxsize=1)
def load_candidates() -> tuple[dict[str, Any], ...]:
    """加载候选院校专业数据。

    当前为演示数据；接入 tasks.md 2.1、2.2 的真实录取数据后替换本函数实现即可。
    """
    candidates = _read_json("plans/candidates_demo.json").get("candidates") or []
    seen: set[str] = set()
    for item in candidates:
        school_id = str(item.get("school_id") or "")
        if not school_id:
            raise DataSourceError("候选数据缺少 school_id")
        if school_id in seen:
            raise DataSourceError(f"候选数据 school_id 重复：{school_id}")
        seen.add(school_id)
        if not str(item.get("name") or "").strip():
            raise DataSourceError(f"候选 {school_id} 缺少 name")
        if not isinstance(item.get("min_score"), int):
            raise DataSourceError(f"候选 {school_id} 的 min_score 必须是整数")
        validate_citation(item, f"候选 {school_id}")
    return tuple(candidates)


@lru_cache(maxsize=1)
def load_schools_demo() -> dict[str, Any]:
    """加载院校/专业演示数据集（tasks.md 7.1、7.2 的本地种子）。

    真实数据由 ③ 号按 tasks.md 2.5 采集后入库；本数据集用于本地开发与测试，
    结构上与第 7 章各表一一对应，因此 ③ 号数据到位后只需停用本文件，服务层不改。

    校验要点：来源三要素、school/major/source 三类 key 的引用完整性、
    生活信息的 reliability 取值。缺来源或引用悬空一律拒收（宁可接口不可用，
    也不输出无来源结论，口径同 tasks.md 2.6）。
    """
    payload = _read_json("schools/schools_demo.json")

    sources: dict[str, dict[str, Any]] = {}
    for item in payload.get("sources") or []:
        key = str(item.get("key") or "")
        if not key:
            raise DataSourceError("院校数据集：source 缺少 key")
        if key in sources:
            raise DataSourceError(f"院校数据集：source key 重复：{key}")
        validate_citation(item, f"来源 {key}")
        sources[key] = item
    if not sources:
        raise DataSourceError("院校数据集：sources 不能为空")

    def _index_unique(items: list[Any], label: str) -> dict[str, dict[str, Any]]:
        indexed: dict[str, dict[str, Any]] = {}
        for item in items:
            key = str(item.get("key") or "")
            if not key:
                raise DataSourceError(f"院校数据集：{label} 缺少 key")
            if key in indexed:
                raise DataSourceError(f"院校数据集：{label} key 重复：{key}")
            if not str(item.get("name") or "").strip():
                raise DataSourceError(f"院校数据集：{label} {key} 缺少 name")
            indexed[key] = item
        return indexed

    schools = _index_unique(payload.get("schools") or [], "school")
    majors = _index_unique(payload.get("majors") or [], "major")
    if not schools or not majors:
        raise DataSourceError("院校数据集：schools 与 majors 均不能为空")

    def _require(key: Any, table: str, context: str) -> None:
        if str(key or "") not in table:
            raise DataSourceError(f"院校数据集：{context} 引用了不存在的 {key!r}")

    for item in payload.get("scores") or []:
        context = f"录取分 {item.get('school')}/{item.get('major')}/{item.get('year')}"
        _require(item.get("school"), schools, context)
        _require(item.get("major"), majors, context)
        _require(item.get("source"), sources, context)
        min_score = item.get("min_score")
        if min_score is not None and not isinstance(min_score, int):
            raise DataSourceError(f"{context} 的 min_score 必须是整数或 null")
        validate_citation(sources[str(item["source"])], context)

    for item in payload.get("profiles") or []:
        context = f"画像 {item.get('school')}"
        _require(item.get("school"), schools, context)
        _require(item.get("source"), sources, context)
        validate_citation(sources[str(item["source"])], context)
        campuses = item.get("campus_list")
        if campuses is not None and not isinstance(campuses, list):
            raise DataSourceError(f"{context} 的 campus_list 必须是数组")
        for campus in campuses or []:
            if not isinstance(campus, dict) or not str(campus.get("name") or "").strip():
                raise DataSourceError(f"{context} 的 campus_list 元素须为含 name 的对象")
        points = item.get("master_phd_points")
        if points is not None and not isinstance(points, dict):
            raise DataSourceError(
                f"{context} 的 master_phd_points 须为 {{master, phd}} 对象或 null（产品书 6.5.3）"
            )

    for item in payload.get("life") or []:
        context = f"生活信息 {item.get('school')}/{item.get('category')}"
        _require(item.get("school"), schools, context)
        validate_citation(item, context)
        reliability = str(item.get("reliability") or "")
        if reliability not in {RELIABILITY_OFFICIAL, RELIABILITY_UNOFFICIAL}:
            raise DataSourceError(
                f"{context} 的 reliability 非法：{reliability!r}，"
                f"应为 {RELIABILITY_OFFICIAL} 或 {RELIABILITY_UNOFFICIAL}"
            )

    return payload


def clear_cache() -> None:
    """清空数据缓存，供管理端重建索引或测试使用。"""
    load_catalog.cache_clear()
    load_regions.cache_clear()
    load_rules.cache_clear()
    load_strategy_config.cache_clear()
    load_risk_rules.cache_clear()
    load_candidates.cache_clear()
    load_schools_demo.cache_clear()
