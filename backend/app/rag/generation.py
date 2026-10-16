"""受限回答生成适配器。

生成器只接收已经筛选的证据片段；来源字段由 QA 服务组装，生成器不能自行创建来源。
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Sequence
from typing import Any, Protocol
from urllib.request import Request, urlopen

LOGGER = logging.getLogger("zhixuan.rag")


class Generator(Protocol):
    name: str

    def generate(
        self,
        question: str,
        snippets: Sequence[dict[str, Any]],
        *,
        province: str | None = None,
        pathway_id: str | None = None,
    ) -> str: ...


class FakeGenerator:
    """离线确定性生成器，用证据原文拼接带引用的摘要。"""

    name = "fake"

    def generate(
        self,
        question: str,
        snippets: Sequence[dict[str, Any]],
        *,
        province: str | None = None,
        pathway_id: str | None = None,
    ) -> str:
        del question, province, pathway_id
        parts: list[str] = []
        for index, snippet in enumerate(snippets, 1):
            content = str(snippet.get("snippet") or snippet.get("content") or "").strip()
            if content:
                parts.append(f"{content[:240]} [{index}]")
        return "基于知识库证据：" + "；".join(parts) if parts else ""


class OpenAICompatibleGenerator:
    """调用 OpenAI-compatible Chat Completions 接口的生成器。"""

    name = "openai-compatible"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = "qwen-plus",
        timeout: float = 30.0,
    ) -> None:
        if not base_url or not api_key:
            raise ValueError("generation API base URL and key are required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def generate(
        self,
        question: str,
        snippets: Sequence[dict[str, Any]],
        *,
        province: str | None = None,
        pathway_id: str | None = None,
    ) -> str:
        context = "\n".join(
            f"[{index}] {snippet.get('snippet') or snippet.get('content', '')}"
            for index, snippet in enumerate(snippets, 1)
        )
        system = (
            "你是智选志愿的可溯源问答助手。只能依据用户提供的知识片段回答，"
            "不得补充片段之外的事实；每条事实结论都要用 [数字] 标注引用。"
            "证据不足时回答‘知识库暂无相关数据，建议查阅官方渠道’。"
        )
        if province:
            system += f" 当前用户省份：{province}。"
        if pathway_id:
            system += f" 当前升学途径：{pathway_id}。"
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": f"问题：{question}\n知识片段：\n{context}"},
            ],
        }
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
        if isinstance(content, list):
            content = "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
        result = str(content).strip()
        if not result:
            raise RuntimeError("generation API returned empty content")
        return result


def create_generator_from_env() -> Generator:
    backend = os.getenv("ZHIXUAN_GENERATION_BACKEND", "fake").strip().lower()
    model = os.getenv("ZHIXUAN_GENERATION_MODEL", "qwen-plus").strip()
    base_url = os.getenv("ZHIXUAN_GENERATION_API_BASE", "").strip()
    api_key = os.getenv("ZHIXUAN_GENERATION_API_KEY", "")
    timeout = float(os.getenv("ZHIXUAN_GENERATION_TIMEOUT", "30"))
    if backend in {"", "fake", "demo"}:
        LOGGER.info("当前为演示实现：使用 FakeGenerator")
        return FakeGenerator()
    if backend in {"openai", "openai-compatible", "qwen"}:
        if not base_url or not api_key:
            LOGGER.warning("生成 API 配置不完整，回退 FakeGenerator")
            return FakeGenerator()
        return OpenAICompatibleGenerator(base_url, api_key, model, timeout)
    raise ValueError(f"unsupported generation backend: {backend}")


__all__ = [
    "FakeGenerator",
    "Generator",
    "OpenAICompatibleGenerator",
    "create_generator_from_env",
]
