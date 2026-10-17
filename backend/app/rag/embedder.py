"""Embedding adapters for local, remote, and offline development modes."""
from __future__ import annotations

import hashlib
import logging
import math
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol
from urllib.request import Request, urlopen
import json

from app.core import env as _env  # noqa: F401  导入即加载 backend/.env

LOGGER = logging.getLogger("zhixuan.rag")
DEFAULT_DIM = 512

class Embedder(Protocol):
    name: str
    dim: int
    def embed(self, texts: list[str]) -> list[list[float]]: ...

def normalize_vector(vector: Iterable[float]) -> list[float]:
    values = [float(x) for x in vector]
    norm = math.sqrt(sum(x * x for x in values))
    return values if norm == 0 else [x / norm for x in values]

def validate_vectors(vectors: list[list[float]], expected_count: int, dim: int) -> list[list[float]]:
    if len(vectors) != expected_count:
        raise ValueError(f"embedding count mismatch: expected {expected_count}, got {len(vectors)}")
    checked = []
    for vector in vectors:
        if len(vector) != dim:
            raise ValueError(f"embedding dimension mismatch: expected {dim}, got {len(vector)}")
        checked.append(normalize_vector(vector))
    return checked

class FakeEmbedder:
    name = "fake"
    def __init__(self, dim: int = DEFAULT_DIM): self.dim = dim
    def embed(self, texts: list[str]) -> list[list[float]]:
        result=[]
        for text in texts:
            raw=hashlib.sha256(text.encode("utf-8")).digest()
            values=[]
            for i in range(self.dim):
                block=hashlib.sha256(raw + i.to_bytes(4,"big")).digest()
                values.append((int.from_bytes(block[:4],"big") / 2**31) - 1)
            result.append(normalize_vector(values))
        return result

class BgeEmbedder:
    name = "bge-small-zh"
    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5", dim: int = DEFAULT_DIM, model=None):
        self.dim = dim
        self.model_name = model_name
        if model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError("BgeEmbedder requires optional sentence-transformers") from exc
            model = SentenceTransformer(model_name)
        self.model = model
    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts: return []
        raw = self.model.encode(texts, normalize_embeddings=False)
        return validate_vectors([list(vector) for vector in raw], len(texts), self.dim)

class OpenAICompatibleEmbedder:
    name = "openai-compatible"
    def __init__(self, base_url: str, api_key: str, model: str, dim: int = DEFAULT_DIM, timeout: float = 30.0):
        if not base_url or not api_key: raise ValueError("embedding API base URL and key are required")
        self.base_url, self.api_key, self.model, self.dim, self.timeout = base_url.rstrip("/"), api_key, model, dim, timeout
    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts: return []
        payload=json.dumps({"model":self.model,"input":texts}).encode("utf-8")
        request=Request(f"{self.base_url}/embeddings",data=payload,headers={"Authorization":f"Bearer {self.api_key}","Content-Type":"application/json"},method="POST")
        with urlopen(request, timeout=self.timeout) as response:
            body=json.loads(response.read().decode("utf-8"))
        vectors=[item["embedding"] for item in sorted(body["data"],key=lambda item:item.get("index",0))]
        return validate_vectors(vectors,len(texts),self.dim)

class CallableEmbedder:
    """Adapt a batch Embedder to indexing's legacy single-text callable."""
    def __init__(self, embedder: Embedder): self.embedder=embedder
    def __call__(self, text: str) -> list[float]: return self.embedder.embed([text])[0]

def register_default_embedder() -> Embedder:
    """Build configured adapter; absent configuration resolves to offline FakeEmbedder."""
    return create_embedder_from_env()

def create_embedder_from_env() -> Embedder:
    backend=os.getenv("ZHIXUAN_EMBEDDING_BACKEND","fake").strip().lower()
    dim=int(os.getenv("ZHIXUAN_EMBEDDING_DIM",str(DEFAULT_DIM)))
    if backend in {"", "fake", "demo"}:
        LOGGER.info("当前为演示实现：使用 FakeEmbedder")
        return FakeEmbedder(dim)
    if backend in {"bge", "local"}:
        return BgeEmbedder(os.getenv("ZHIXUAN_EMBEDDING_MODEL","BAAI/bge-small-zh-v1.5"),dim)
    if backend in {"openai", "openai-compatible", "qwen"}:
        return OpenAICompatibleEmbedder(os.getenv("ZHIXUAN_EMBEDDING_API_BASE",""),os.getenv("ZHIXUAN_EMBEDDING_API_KEY",""),os.getenv("ZHIXUAN_EMBEDDING_MODEL","text-embedding-v3"),dim)
    raise ValueError(f"unsupported embedding backend: {backend}")
