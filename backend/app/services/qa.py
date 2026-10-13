"""可溯源问答业务逻辑。

正式实现为混合检索 + 重排 + 受限生成，见 tasks.md 第 5 组与 6.1。
当前为演示实现：固定回答 + 固定置信度，引用为演示来源。
"""

from __future__ import annotations

from app.core.demo import demo_citation

DEMO_ANSWER = "请先完善考生档案，我会基于你的省份、分数与选科给出可核验建议。"
DEMO_CONFIDENCE = 0.62


def answer(question: str) -> dict[str, object]:
    """回答问题，返回答案、置信度与引用。"""
    return {
        "answer": DEMO_ANSWER,
        "confidence": DEMO_CONFIDENCE,
        "citations": [demo_citation()],
    }
