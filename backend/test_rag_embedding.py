from __future__ import annotations
import sys
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.rag.embedder import FakeEmbedder, create_embedder_from_env, normalize_vector, validate_vectors
from app.rag.retrieval import bm25_search, vector_search

def test_fake_deterministic():
    embedder=FakeEmbedder(8)
    assert embedder.embed(["河南普通批"])[0] == embedder.embed(["河南普通批"])[0]
    assert len(embedder.embed(["x"])[0]) == 8

def test_empty_and_validation():
    assert FakeEmbedder(8).embed([]) == []
    try: validate_vectors([[1.0]],1,2)
    except ValueError: pass
    else: raise AssertionError("dimension mismatch must fail")

def test_default_is_offline_fake_and_normalized():
    with patch.dict("os.environ", {"ZHIXUAN_EMBEDDING_BACKEND": "fake"}):
        embedder = create_embedder_from_env()
    assert embedder.name == "fake"
    vector = embedder.embed(["offline"])[0]
    assert abs(sum(value * value for value in vector) - 1.0) < 1e-6
    assert normalize_vector([0.0, 0.0]) == [0.0, 0.0]

def test_vector_and_bm25_search():
    chunks=[{"chunk_id":1,"content":"普通批 计算机", "embedding":[1.0,0.0]}, {"chunk_id":2,"content":"艺术类", "embedding":[0.0,1.0]}]
    assert vector_search([.9,.1],chunks,1)[0].chunk_id == 1
    assert bm25_search("计算机",chunks,1)[0].chunk_id == 1

if __name__ == "__main__":
    for test in (test_fake_deterministic,test_empty_and_validation,test_vector_and_bm25_search): test()
    print("rag embedding tests passed")
