"""T3 RAG 问答离线验收（不联网、不下载模型、不使用 GPU）。"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_work = Path(tempfile.mkdtemp(prefix="zhixuan_qa_rag_"))
os.environ["ZHIXUAN_DATABASE_URL"] = f"sqlite:///{(_work / 'qa.db').as_posix()}"
os.environ["ZHIXUAN_SECRET_KEY"] = "test-secret-key-qa-rag-suite-at-least-32-bytes"
os.environ["ZHIXUAN_ENV"] = "test"
os.environ["ZHIXUAN_EMBEDDING_BACKEND"] = "fake"
os.environ["ZHIXUAN_RERANK_BACKEND"] = "fake"
os.environ["ZHIXUAN_GENERATION_BACKEND"] = "fake"

from app.db.session import SessionLocal, create_all  # noqa: E402
from app.models.knowledge import KnowledgeChunk, KnowledgeDoc, QaLog, ReviewTask  # noqa: E402
from app.models.source import Source  # noqa: E402
from app.rag.embedder import FakeEmbedder  # noqa: E402
from app.rag.generation import FakeGenerator  # noqa: E402
from app.rag.reranker import FakeReranker  # noqa: E402
from app.services import qa  # noqa: E402

create_all()
_embedder = FakeEmbedder(512)


def seed_chunk(content: str, *, province: str = "河南", pathway_id: str | None = None) -> int:
    with SessionLocal() as db:
        source = Source(
            source_name="河南省教育考试院",
            source_url="https://www.haeea.cn/official",
            year=2026,
            source_type="official",
        )
        db.add(source)
        db.flush()
        doc = KnowledgeDoc(
            title="河南招生政策",
            source_name=source.source_name,
            source_url=source.source_url,
            year=source.year,
            province=province,
            pathway_id=pathway_id,
            doc_type="政策",
            content=content,
        )
        db.add(doc)
        db.flush()
        chunk = KnowledgeChunk(
            doc_id=doc.id,
            content=content,
            chunk_index=0,
            embedding=_embedder.embed([content])[0],
            province=province,
            pathway_id=pathway_id,
            source_id=source.id,
        )
        db.add(chunk)
        db.commit()
        return int(chunk.id)


def test_full_chain_and_citation() -> None:
    seed_chunk("河南省2026年普通本科一批省控线为465分。")
    qa.register_embedder(_embedder)
    qa.register_reranker(FakeReranker())
    qa.register_generator(FakeGenerator())
    with SessionLocal() as db:
        result = qa.ask(db, "河南一本线是多少", session_id="s-full", province="河南")
    assert "465" in result["answer"]
    assert result["citations"]
    assert {"source_name", "source_url", "year", "snippet", "chunk_id"} <= set(result["citations"][0])
    assert result["confidence_level"] in {"high", "medium", "low"}


def test_no_evidence_never_calls_generator() -> None:
    calls = {"count": 0}

    class CountingGenerator:
        def generate(self, *args, **kwargs) -> str:
            calls["count"] += 1
            return "不应被调用"

    qa.register_generator(CountingGenerator())
    with SessionLocal() as db:
        result = qa.ask(db, "一个完全不存在的冷门问题", session_id="s-empty")
    assert "知识库暂无相关数据" in result["answer"]
    assert result["confidence_level"] == "low"
    assert result["needs_review"] is True
    assert calls["count"] == 0


def test_generation_failure_degrades_and_logs_review() -> None:
    seed_chunk("河南省普通批平行志愿按分数优先、遵循志愿顺序投档。")

    class FailingGenerator:
        def generate(self, *args, **kwargs) -> str:
            raise TimeoutError("fixture timeout")

    qa.register_generator(FailingGenerator())
    with SessionLocal() as db:
        result = qa.ask(db, "河南普通批平行志愿如何投档", session_id="s-degrade")
        log = db.get(QaLog, result["qa_log_id"])
        task = db.query(ReviewTask).filter(ReviewTask.qa_log_id == log.id).one()
        assert log.degraded is True
        assert task.status == "pending"
    assert result["degraded"] is True
    assert "AI 生成暂不可用" in result["answer"]
    assert result["citations"]


def test_low_confidence_review_is_idempotent_and_history_shape() -> None:
    class LowReranker:
        def rerank(self, query, documents):
            return [0.1 for _ in documents]

    seed_chunk("河南招生章程说明报名条件以官方公告为准。")
    qa.register_reranker(LowReranker())
    qa.register_generator(FakeGenerator())
    with SessionLocal() as db:
        result = qa.ask(db, "报名条件是什么", session_id="s-review")
        log_id = result["qa_log_id"]
        assert db.query(ReviewTask).filter(ReviewTask.qa_log_id == log_id).count() == 1
        result2 = qa.ask(db, "报名条件是什么", session_id="s-review")
        assert db.query(ReviewTask).filter(ReviewTask.qa_log_id == result2["qa_log_id"]).count() == 1
        page = qa.history(db, session_id="s-review")
    assert set(page) == {"items", "total", "page", "page_size"}
    assert page["total"] == 2


def main() -> int:
    tests = [
        test_full_chain_and_citation,
        test_no_evidence_never_calls_generator,
        test_generation_failure_degrades_and_logs_review,
        test_low_confidence_review_is_idempotent_and_history_shape,
    ]
    failures: list[str] = []
    for test in tests:
        try:
            test()
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{test.__name__}: {type(exc).__name__}: {exc}")
    for failure in failures:
        print(f"FAIL {failure}")
    print(f"RAG QA tests: {len(tests) - len(failures)}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
