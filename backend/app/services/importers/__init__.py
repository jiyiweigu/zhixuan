"""③ 数据工程产出物 → 数据库 的导入层（tasks.md 2.x 的消费侧，责任人 ② 费）。

定位
----
``data/`` 下是 ③ 的产出物（字典、规则、采集结果），``backend/app/models/`` 是 ② 的表结构，
本包是二者之间**唯一**的落库通道。服务层（``app/services/schools.py`` 等）只查库表，
不读 ``data/``，因此「数据一入库，接口即生效」。

三条铁律（与 ``app/services/source_guard.py``、``app/core/dataset.py`` 同源）
----------------------------------------------------------------------------
1. **来源三要素缺一不入库**：事实表行必须能解析出 source_name / source_url / year，
   否则跳过并计入 ``report.skip_reasons``，绝不静默写入（产品书 6.0.4 错误码 4001 的口径）。
2. **幂等**：同一份数据重复执行，第二次的 ``created`` 必须为 0。
3. **不推断**：字段缺失留 NULL / 空串，不拿外部知识补；口径歧义一律跳过并上报，
   交由 ③ / 队长裁决（见 ``数据入库对接发现与待裁决_费.md``）。

数据根目录
----------
``data/`` 的数据**本体**自 2026-10-13 起不再随仓库分发（授权与体积原因，
见 ``data/DOWNLOAD.md``），仓库只留字典、脚本与小样本。因此数据根可配置：

- 环境变量 ``ZHIXUAN_DATA_ROOT`` 优先；
- 未设置时回落到仓库根 ``data/``。

调用
----
    cd backend && .venv/Scripts/python.exe -m app.services.importers
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.source import Source
from app.services import source_guard

# app/services/importers/__init__.py → importers → services → app → backend → 仓库根
BACKEND_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = BACKEND_ROOT.parent
DEFAULT_DATA_ROOT = REPO_ROOT / "data"

DATA_ROOT_ENV = "ZHIXUAN_DATA_ROOT"


def data_root() -> Path:
    """数据根目录：``ZHIXUAN_DATA_ROOT`` 优先，否则仓库根 ``data/``。"""
    override = os.environ.get(DATA_ROOT_ENV, "").strip()
    return Path(override) if override else DEFAULT_DATA_ROOT


# --------------------------------------------------------------------------- #
# 导入报告
# --------------------------------------------------------------------------- #
@dataclass
class ImportReport:
    """单个数据集的一次导入结果。``skipped`` 必须能由 ``skip_reasons`` 完全解释。"""

    dataset: str
    read: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    missing_file: str | None = None

    def skip(self, reason: str) -> None:
        self.skipped += 1
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1

    def note(self, message: str) -> None:
        self.notes.append(message)

    @property
    def accounted(self) -> int:
        """已被解释的行数，应恒等于 ``read``。"""
        return self.created + self.updated + self.unchanged + self.skipped

    @property
    def clean(self) -> bool:
        """无异常跳过即视为干净（幂等命中不计为异常）。"""
        return self.skipped == 0

    def describe(self) -> str:
        parts = [
            f"读入 {self.read}",
            f"新增 {self.created}",
            f"更新 {self.updated}",
            f"幂等 {self.unchanged}",
            f"跳过 {self.skipped}",
        ]
        line = f"{self.dataset:<22s} " + " / ".join(parts)
        if self.skip_reasons:
            detail = "、".join(f"{k}×{v}" for k, v in sorted(self.skip_reasons.items()))
            line += f"（{detail}）"
        if self.missing_file:
            line += f"  数据文件缺失：{self.missing_file}"
        return line


def load_dataset(path: Path) -> dict[str, Any] | None:
    """读 JSON；文件不存在返回 None（数据本体不随仓库分发，属正常情况）。"""
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else None


def rows_of(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """取出数据集里的行数组；缺键或非数组一律返回空列表。"""
    value = payload.get(key)
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    return []


def load_rows(path: Path, key: str = "records") -> list[dict[str, Any]] | None:
    """读 JSON 行数组；文件不存在返回 ``None``（数据本体不随仓库分发，属正常情况）。

    ③ 的产出有两种形状，本函数统一接收：
    - **顶层数组**：``data/output/discipline_eval.json``、``pathway_score.json``；
    - **带键包装**：``{"<key>": [...]}``（``data/schools/*_rows.json`` 用 ``records``）。
    """
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        return rows_of(payload, key)
    return []


# --------------------------------------------------------------------------- #
# 取值助手
# --------------------------------------------------------------------------- #
def text_of(row: dict[str, Any], key: str) -> str:
    """取非空字符串；缺失 / 空白 / 非标量一律返回 ``""``。"""
    value = row.get(key)
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    return ""


def int_of(row: dict[str, Any], key: str) -> int | None:
    """取整数；无法解析（含浮点截断失败）返回 None，绝不猜测。"""
    value = row.get(key)
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.lstrip("+-").isdigit():
            return int(stripped)
    return None


def float_of(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def bool_of(row: dict[str, Any], key: str, default: bool = False) -> bool:
    value = row.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "是"}:
            return True
        if lowered in {"false", "0", "no", "否"}:
            return False
    return default


# --------------------------------------------------------------------------- #
# 来源解析
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class SourceTriplet:
    """``source_guard.ensure_source`` 需要的三要素载体。"""

    source_name: str
    source_url: str
    year: int
    source_type: str | None = None


class SourceRegistry:
    """③ 的字符串来源 id（``SRC-XXX``）→ 数据库 ``source.id`` 的解析器。

    ``data/`` 侧的规则行用 ``source_id: "SRC-HENAN-EXAM"`` 这类**字符串**引用来源，
    而库表用自增整数外键，两者之间没有持久映射列（``source`` 表不含外部 id）。
    本类每次导入时从 ``source-table.json`` 重建映射，保证幂等且不新增表结构。

    解析优先级：
    1. 行内自带的 ``source_name`` / ``source_url`` / ``year``（最权威，直接用）；
    2. 行内 ``source_id`` 命中 ``source-table.json``；
    3. 数据集级 ``meta`` 的三要素（③ 的 2026 一分一段把溯源放在 ``meta``，行内不带）；
    4. 都拿不到 → 返回 None，由调用方按「缺来源」跳过。
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._registry: dict[str, SourceTriplet] = {}
        self._cache: dict[tuple[str, str, int], Source] = {}
        self.unresolved: dict[str, int] = {}

    def load_registry(self, path: Path) -> int:
        """载入来源表；返回登记条数（数据文件缺失时返回 0）。"""
        payload = load_dataset(path)
        if payload is None:
            return 0
        for row in rows_of(payload, "sources"):
            external_id = text_of(row, "id")
            name = text_of(row, "source_name")
            url = text_of(row, "source_url")
            year = int_of(row, "year")
            if not external_id or not name or not url or year is None:
                continue
            self._registry[external_id] = SourceTriplet(
                source_name=name,
                source_url=url,
                year=year,
                source_type=text_of(row, "source_type") or None,
            )
        return len(self._registry)

    def triplet_for(self, external_id: str) -> SourceTriplet | None:
        return self._registry.get(external_id)

    def resolve(self, row: dict[str, Any], meta: dict[str, Any] | None = None) -> Source | None:
        """按优先级解析出一行 ``source``；解析不到返回 None。"""
        triplet = self._triplet_of(row, meta)
        if triplet is None:
            external_id = text_of(row, "source_id") or "(空)"
            self.unresolved[external_id] = self.unresolved.get(external_id, 0) + 1
            return None
        key = (triplet.source_name, triplet.source_url, triplet.year)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        source_guard.require_source(triplet.source_name, triplet.source_url, triplet.year)
        source_guard.require_year(triplet.year)
        source = source_guard.ensure_source(self._db, triplet)
        self._cache[key] = source
        return source

    def year_for(self, row: dict[str, Any], meta: dict[str, Any] | None = None) -> int | None:
        """取规则行应落的年份。

        ``pathway_eligibility`` 的行**没有 year 字段**，年份只能从其引用的来源取——
        来源表里哪一年登记的，规则就落在哪一年，可追溯而非编造。
        """
        inline = int_of(row, "year")
        if inline is not None:
            return inline
        triplet = self._triplet_of(row, meta)
        return triplet.year if triplet is not None else None

    def _triplet_of(
        self, row: dict[str, Any], meta: dict[str, Any] | None = None
    ) -> SourceTriplet | None:
        inline = _complete_triplet(row)
        if inline is not None:
            return inline
        external_id = text_of(row, "source_id")
        if external_id:
            registered = self._registry.get(external_id)
            if registered is not None:
                return registered
        if meta:
            return _complete_triplet(meta)
        return None


def _complete_triplet(container: dict[str, Any]) -> SourceTriplet | None:
    """从任意 dict 抽三要素；任一缺失即返回 None（不做部分拼装）。"""
    name = text_of(container, "source_name")
    url = text_of(container, "source_url")
    year = int_of(container, "year")
    if name and url and year is not None:
        return SourceTriplet(
            source_name=name,
            source_url=url,
            year=year,
            source_type=text_of(container, "source_type") or None,
        )
    return None
