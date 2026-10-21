"""indexer tests using a temporary LANCEDB_PATH and stubbed embedder."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.services import indexer
from app.services.indexer import LanceIndexer


@pytest.fixture
def stub_embedder(monkeypatch):
    """Replace embed_batch with a deterministic fake."""
    def fake_embed(texts):
        arr = np.zeros((len(texts), 8), dtype=np.float32)
        for i, t in enumerate(texts):
            arr[i, 0] = float(len(t) % 7) / 7.0
            arr[i, 1] = float(hash(t) % 5) / 5.0
        return arr

    async def fake_async(texts):
        return fake_embed(list(texts))

    monkeypatch.setattr(indexer.embedder_module, "embed_batch", fake_async)


@pytest.fixture
def fresh_indexer(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("LANCEDB_PATH", str(tmp_path / "lancedb"))
    from app.config import get_settings

    get_settings.cache_clear()
    idx = LanceIndexer()
    yield idx
    idx._db = None  # type: ignore[attr-defined]


def test_index_file_creates_status_row(fresh_indexer, stub_embedder):
    md = "# Hello\n\nThis is a small test document for indexing."
    target = Path("/vault/team/test.md")
    status = fresh_indexer.index_file(target, md)
    assert status.status == "ok"
    assert status.chunk_count >= 1
    statuses = fresh_indexer.get_status()
    assert any(s.file_path == str(target) for s in statuses)


def test_index_file_upserts_on_repeat(fresh_indexer, stub_embedder):
    md = "# Same\n\nContent for re-indexing test."
    target = Path("/vault/team/dup.md")
    s1 = fresh_indexer.index_file(target, md)
    s2 = fresh_indexer.index_file(target, md)
    assert s1.file_hash == s2.file_hash
    statuses = fresh_indexer.get_status()
    matches = [s for s in statuses if s.file_path == str(target)]
    # After dedup-by-hash we expect exactly one status row.
    assert len(matches) == 1


def test_delete_file_removes_status_and_chunks(fresh_indexer, stub_embedder):
    md = "# Bye\n\nSome content."
    target = Path("/vault/team/del.md")
    fresh_indexer.index_file(target, md)
    assert any(s.file_path == str(target) for s in fresh_indexer.get_status())
    fresh_indexer.delete_file(target)
    assert not any(s.file_path == str(target) for s in fresh_indexer.get_status())


def test_get_status_returns_list(fresh_indexer, stub_embedder):
    assert isinstance(fresh_indexer.get_status(), list)
