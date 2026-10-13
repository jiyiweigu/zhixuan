"""AI 支撑服务的可运行测试（tasks.md 5.1；原先只有 4 个裸函数、无 runner，从未真正执行）。

约定与 ``backend/test_*.py`` 一致：无需 pytest，直接运行
    cd backend && .venv\\Scripts\\python.exe tests/test_ai_support.py

覆盖：
- 趋势判定：两年位次上升 → ``rising``；仅一年数据 → ``insufficient_data``；
- 无证据回答必须标 ``needs_review``（缺引用的结论不得展示）；
- 安全解释：中性表述通过，"保证录取" 一类违规承诺被拒。
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

# 允许直接 `python tests/test_ai_support.py`：把 backend/ 放进 sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.ai_support import (  # noqa: E402
    analyze_trend,
    restricted_answer,
    safe_explanation,
)

CASES: list[tuple[str, Callable[[], None]]] = []


def case(title: str) -> Callable[[Callable[[], None]], Callable[[], None]]:
    def deco(fn: Callable[[], None]) -> Callable[[], None]:
        CASES.append((title, fn))
        return fn

    return deco


def _rows(*pairs: tuple[int, int]) -> list[dict[str, object]]:
    return [
        {"year": year, "min_rank": rank, "source_name": "河南省教育考试院", "source_url": "https://www.haeea.cn/"}
        for year, rank in pairs
    ]


@case("趋势01 两年位次上升（18000 → 15000）→ rising")
def _() -> None:
    assert analyze_trend(_rows((2023, 18000), (2024, 15000)))["trend"] == "rising"


@case("趋势02 仅一年数据 → insufficient_data（不臆测趋势）")
def _() -> None:
    assert analyze_trend(_rows((2024, 1)))["trend"] == "insufficient_data"


@case("趋势03 位次下降 → falling")
def _() -> None:
    assert analyze_trend(_rows((2023, 15000), (2024, 18000)))["trend"] == "falling"


@case("引用01 无证据回答 → needs_review 为真")
def _() -> None:
    assert restricted_answer("q", [])["needs_review"]


@case("引用02 有证据回答 → citations 带三要素与序号，不强制复核")
def _() -> None:
    citations = [{"source_name": "河南省教育考试院", "source_url": "https://www.haeea.cn/", "year": 2026}]
    answer = restricted_answer("河南本科批能填几个志愿？", citations)
    assert len(answer["citations"]) == 1
    assert answer["citations"][0]["source_name"] == "河南省教育考试院"
    assert answer["citations"][0]["source_url"] == "https://www.haeea.cn/"
    assert answer["citations"][0]["year"] == 2026
    assert not answer["needs_review"]


@case("引用03 片段缺来源三要素 → 等同无证据，进 needs_review")
def _() -> None:
    answer = restricted_answer("q", [{"source_name": "", "source_url": "", "year": 0}])
    assert answer["needs_review"] and answer["citations"] == []


@case("安全01 中性表述通过；违规承诺被拒")
def _() -> None:
    assert safe_explanation("历史趋势")
    assert not safe_explanation("保证录取")


def main() -> int:
    passed = 0
    failures: list[str] = []
    for title, fn in CASES:
        try:
            fn()
            passed += 1
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{title}: {type(exc).__name__}: {exc}")
    total = len(CASES)
    if failures:
        print("AI 支撑服务测试失败：")
        for item in failures:
            print("  -", item)
        print(f"{passed}/{total} 通过")
        return 1
    print(f"AI 支撑服务测试：{passed}/{total} 通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
