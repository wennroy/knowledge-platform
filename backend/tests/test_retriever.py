"""Retriever tests using a fake indexer + monkeypatched hooks.

The retriever depends on LanceDB and the embedder; both are heavy and require a
real gateway for the embedding side. We monkeypatch the retriever's internal
hooks (``_embed_query_sync`` and ``_search_chunks``) so the tests stay fast
and deterministic, while exercising the actual ``Retriever.retrieve`` and
``Retriever.format_context`` code paths.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from app.services.retriever import (
    RetrievalResult,
    Retriever,
    RetrieverError,
    format_context,
)


@dataclass
class FakeIndexer:
    """Minimal stand-in for ``LanceIndexer`` exposing only what Retriever reads."""

    lancedb_path: Path
    closed: bool = False


def _fake_rows() -> list[dict[str, Any]]:
    return [
        {
            "id": "chunk-1",
            "file_path": "/vault/team/alpha.md",
            "chunk_index": 0,
            "text": "alpha body one",
            "heading_path": ["Alpha", "Intro"],
            "_distance": 0.1,
        },
        {
            "id": "chunk-2",
            "file_path": "/vault/team/beta.md",
            "chunk_index": 3,
            "text": "beta body two",
            "heading_path": ["Beta"],
            "_distance": 1.5,
        },
    ]


@pytest.fixture
def fake_retriever(monkeypatch, tmp_path: Path) -> Retriever:
    indexer = FakeIndexer(lancedb_path=tmp_path / "lancedb")
    r = Retriever(indexer)  # type: ignore[arg-type]

    monkeypatch.setattr(r, "_embed_query_sync", lambda q: [0.1, 0.2, 0.3])
    monkeypatch.setattr(r, "_search_chunks", lambda vec, k: _fake_rows())
    return r


# ------------------------------------------------------------------ retrieve
def test_retrieve_returns_typed_results(fake_retriever: Retriever):
    hits = fake_retriever.retrieve("anything", top_k=4)
    assert len(hits) == 2
    assert all(isinstance(h, RetrievalResult) for h in hits)
    assert hits[0].file_path == "/vault/team/alpha.md"
    assert hits[0].chunk_index == 0
    assert hits[0].heading_path == ["Alpha", "Intro"]
    assert hits[0].text == "alpha body one"
    assert hits[0].chunk_id == "chunk-1"
    # distance 0.1 -> 1/(1+0.1) ~= 0.909
    assert hits[0].score == pytest.approx(1.0 / 1.1, rel=1e-3)
    # distance 1.5 -> 1/(1+1.5) ~= 0.4
    assert hits[1].score == pytest.approx(1.0 / 2.5, rel=1e-3)


def test_retrieve_top_k_zero_returns_empty(fake_retriever: Retriever):
    assert fake_retriever.retrieve("x", top_k=0) == []


def test_retrieve_propagates_embed_error(monkeypatch, tmp_path: Path):
    indexer = FakeIndexer(lancedb_path=tmp_path / "lancedb")
    r = Retriever(indexer)  # type: ignore[arg-type]

    def boom(_q):
        raise RetrieverError("embed exploded")

    monkeypatch.setattr(r, "_embed_query_sync", boom)
    with pytest.raises(RetrieverError, match="embed exploded"):
        r.retrieve("anything")


def test_retrieve_propagates_search_error(monkeypatch, tmp_path: Path):
    indexer = FakeIndexer(lancedb_path=tmp_path / "lancedb")
    r = Retriever(indexer)  # type: ignore[arg-type]
    monkeypatch.setattr(r, "_embed_query_sync", lambda q: [0.0])

    def boom(_v, _k):
        raise RetrieverError("search exploded")

    monkeypatch.setattr(r, "_search_chunks", boom)
    with pytest.raises(RetrieverError, match="search exploded"):
        r.retrieve("anything")


def test_retrieve_handles_string_heading_path(monkeypatch, tmp_path: Path):
    indexer = FakeIndexer(lancedb_path=tmp_path / "lancedb")
    r = Retriever(indexer)  # type: ignore[arg-type]
    monkeypatch.setattr(r, "_embed_query_sync", lambda q: [0.0])
    monkeypatch.setattr(
        r,
        "_search_chunks",
        lambda vec, k: [
            {
                "id": "x",
                "file_path": "/v/a.md",
                "chunk_index": 0,
                "text": "t",
                "heading_path": '["A", "B"]',
                "_distance": 0.0,
            }
        ],
    )
    hits = r.retrieve("anything")
    assert hits[0].heading_path == ["A", "B"]


def test_retrieve_handles_invalid_heading_path(monkeypatch, tmp_path: Path):
    indexer = FakeIndexer(lancedb_path=tmp_path / "lancedb")
    r = Retriever(indexer)  # type: ignore[arg-type]
    monkeypatch.setattr(r, "_embed_query_sync", lambda q: [0.0])
    monkeypatch.setattr(
        r,
        "_search_chunks",
        lambda vec, k: [
            {
                "id": "x",
                "file_path": "/v/a.md",
                "chunk_index": 0,
                "text": "t",
                "heading_path": "not-json",
                "_distance": 0.5,
            }
        ],
    )
    hits = r.retrieve("anything")
    assert hits[0].heading_path == []


def test_distance_to_score_handles_none():
    assert Retriever._distance_to_score(None) == 0.0


# ------------------------------------------------------------------ format
def test_format_context_with_results_includes_heading_and_idx():
    r1 = RetrievalResult(
        file_path="/vault/team/a.md",
        chunk_index=0,
        heading_path=["A", "Intro"],
        text="first body",
        score=0.9,
        chunk_id="c1",
    )
    r2 = RetrievalResult(
        file_path="/vault/team/b.md",
        chunk_index=1,
        heading_path=[],
        text="second body",
        score=0.4,
        chunk_id="c2",
    )
    out = format_context([r1, r2])
    assert "[1] /vault/team/a.md#A > Intro" in out
    assert "first body" in out
    assert "[2] /vault/team/b.md" in out  # no heading
    assert "second body" in out
    assert "do not invent facts" in out.lower()


def test_format_context_with_empty_results_emits_anti_hallucination():
    out = format_context([])
    assert "no matching chunks" in out.lower()
    assert "do not" in out.lower() or "fabricat" in out.lower()


# ------------------------------------------------------------------ refs payload
def test_references_payload_round_trip():
    results = [
        RetrievalResult(
            file_path="/vault/a.md",
            chunk_index=0,
            heading_path=["Alpha"],
            text="x",
            score=0.83291,
            chunk_id="c-1",
        )
    ]
    payload = Retriever.references_payload(results)
    assert payload == [
        {
            "file_path": "/vault/a.md",
            "heading": "Alpha",
            "chunk_id": "c-1",
            "score": 0.8329,
        }
    ]