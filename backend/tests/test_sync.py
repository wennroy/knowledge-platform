"""sync tests using mocked callbacks."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.services import sync


@pytest.fixture
def fake_indexer(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("LANCEDB_PATH", str(tmp_path / "lancedb"))
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    from app.config import get_settings

    get_settings.cache_clear()

    # Stub the embedder so reconcile doesn't hit the network.
    import numpy as np

    async def fake_embed(texts):
        return np.zeros((len(texts), 8), dtype=np.float32)

    from app.services import embedder as embedder_module

    monkeypatch.setattr(embedder_module, "embed_batch", fake_embed)
    from app.services import indexer as indexer_module

    monkeypatch.setattr(indexer_module.embedder_module, "embed_batch", fake_embed)

    yield
    get_settings.cache_clear()


def test_startup_reconcile_indexes_existing_md(fake_indexer, tmp_path: Path):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "team").mkdir()
    (vault_root / "team" / "a.md").write_text(
        "---\nsource_hash: deadbeef\n---\n\n# A\n\nHello",
        encoding="utf-8",
    )
    indexed = []
    deleted = []

    v = sync.VaultIndexer(
        on_index=lambda p: indexed.append(str(p)),
        on_delete=lambda p: deleted.append(str(p)),
    )
    res = v.startup_reconcile(vault_root)
    assert res["scanned"] >= 1
    assert res["indexed"] >= 1


def test_startup_reconcile_removes_orphan_from_index(fake_indexer, tmp_path: Path):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    # Pre-seed the indexer with a status row pointing at a file that doesn't exist.
    from app.models import utcnow_iso
    from app.services.indexer import LanceIndexer

    idx = LanceIndexer()
    idx._status.add(  # type: ignore[attr-defined]
        [
            {
                "file_path": str(vault_root / "team" / "ghost.md"),
                "file_hash": "ghost",
                "chunk_count": 0,
                "status": "ok",
                "updated_at": utcnow_iso(),
                "error": "",
            }
        ]
    )

    v = sync.VaultIndexer()
    res = v.startup_reconcile(vault_root)
    assert res["deleted"] >= 1


def test_watchdog_debounce_coalesces_burst(fake_indexer, tmp_path: Path):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "team").mkdir()
    target = vault_root / "team" / "burst.md"
    target.write_text("# Hello\n\nWorld", encoding="utf-8")

    calls = []

    v = sync.VaultIndexer(
        on_index=lambda p: calls.append(("index", str(p))),
        on_delete=lambda p: calls.append(("delete", str(p))),
    )
    v._enqueue(target)
    v._enqueue(target)
    v._enqueue(target)
    # Wait for debounce timer to fire (timer is 0.5s; allow generous slack)
    deadline = time.time() + 3.0
    while time.time() < deadline and not calls:
        time.sleep(0.05)
    assert any(c[0] == "index" for c in calls)
