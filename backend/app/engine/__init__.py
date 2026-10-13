"""报考约束引擎包（产品书 8.5 四道闸门）。

纯函数实现，与 ``app/services/`` 分离：② 写引擎、③ 填规则数据，
两者用 6.2.7 的 JSON 契约对接（8.5 实现纪律第 5 条）。

对外入口见 app/engine/constraints.py：
    subject_match / physical_check / fee_check / province_rule_check / check_units
"""

from __future__ import annotations

from app.engine.constraints import (
    BLOCKERS,
    UNKNOWNS,
    WARNINGS,
    check_units,
    fee_check,
    physical_check,
    province_rule_check,
    subject_match,
)

__all__ = [
    "BLOCKERS",
    "UNKNOWNS",
    "WARNINGS",
    "check_units",
    "fee_check",
    "physical_check",
    "province_rule_check",
    "subject_match",
]
