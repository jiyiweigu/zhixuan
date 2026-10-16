"""可替换的证据重排适配器。

默认使用确定性的 FakeReranker，保证开发与测试不联网；启用真实模型时再选择
BGE CrossEncoder。适配器只负责给候选片段打分，来源和安全约束由问答服务负责。
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from collections.abc import Sequence
from typing import Any, Protocol

LOGGER = logging.getLogger("zhixuan.rag")


class Reranker(Protocol):
    name: str

    def rerank(self, query: str, documents: Sequence[str | dict[str, Any]]) -> list[float]: ...


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+", str(text).lower())


def _document_text(document: str | dict[str, Any]) -> str:
    return str(document.get("content", "") if isinstance(document, dict) else document)


class FakeReranker:
    """基于词元覆盖率和稳定微扰的离线重排器。"""

    name = "fake"

    def rerank(self, query: str, documents: Sequence[str | dict[str, Any]]) -> list[float]:
        query_tokens = _tokens(query)
        query_set = set(query_tokens)
        scores: list[float] = []
        for document in documents:
            text = _document_text(document)
            tokens = _tokens(text)
            token_set = set(tokens)
            overlap = len(query_set & token_set) / max(len(query_set), 1)
            phrase_bonus = 0.12 if query.strip() and query.strip().lower() in text.lower() else 0.0
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            stable_noise = int.from_bytes(digest[:2], "big") / 65535 * 0.01
            scores.append(min(1.0, 0.05 + 0.84 * overlap + phrase_bonus + stable_noise))
        return scores


class BgeReranker:
    """可选的 BGE CrossEncoder 重排器，模型只在显式启用时加载。"""

    name = "bge-reranker"

    def __init__(self, model_name: str = "BAAI/bge-reranker-base", model: Any = None) -> None:
        self.model_name = model_name
        if model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:
                raise RuntimeError("BgeReranker requires optional sentence-transformers") from exc
            model = CrossEncoder(model_name)
        self.model = model

    def rerank(self, query: str, documents: Sequence[str | dict[str, Any]]) -> list[float]:
        if not documents:
            return []
        pairs = [[query, _document_text(document)] for document in documents]
        raw = self.model.predict(pairs)
        values = [float(value) for value in raw]
        if not values:
            return values
        # CrossEncoder 分数没有固定范围，映射到 0~1 供统一置信度逻辑使用。
        low, high = min(values), max(values)
        if high == low:
            return [0.5 for _ in values]
        return [(value - low) / (high - low) for value in values]


def create_reranker_from_env() -> Reranker:
    backend = os.getenv("ZHIXUAN_RERANK_BACKEND", "fake").strip().lower()
    model = os.getenv("ZHIXUAN_RERANK_MODEL", "BAAI/bge-reranker-base").strip()
    if backend in {"", "fake", "demo"}:
        LOGGER.info("当前为演示实现：使用 FakeReranker")
        return FakeReranker()
    if backend in {"bge", "local"}:
        return BgeReranker(model)
    raise ValueError(f"unsupported reranker backend: {backend}")


__all__ = ["BgeReranker", "FakeReranker", "Reranker", "create_reranker_from_env"]
