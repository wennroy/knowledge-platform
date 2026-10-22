"""Regression tests for calling the sync indexer from async context.

The bug these guard against: ``LanceIndexer.index_file`` awaits the embedding
call via ``asyncio.run()`` internally. When it was invoked synchronously from
a FastAPI lifespan hook (an async context with a running event loop), that
raised ``RuntimeError: asyncio.run() cannot be called from a running event
loop`` — and the lifespan hook swallowed it in a bare ``except``, leaving the
whole index silently empty while every test still passed.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from app.main import app
from app.services.indexer import LanceIndexer, _maybe_await


class TestAsyncContextIndexing:
    def test_maybe_await_works_with_running_loop(self):
        """_maybe_await must not raise when a loop is already running."""

        async def coro() -> str:
            await asyncio.sleep(0)
            return "ok"

        async def driver() -> str:
            return _maybe_await(coro())

        # If this raises RuntimeError, the bug is back.
        assert asyncio.run(driver()) == "ok"

    def test_maybe_await_without_loop_still_works(self):
        """The plain (no running loop) path must keep working."""

        async def coro() -> str:
            return "plain"

        assert _maybe_await(coro()) == "plain"

    def test_maybe_await_passes_through_non_coroutine(self):
        assert _maybe_await(42) == 42

    def test_index_file_works_from_running_loop(self, monkeypatch, tmp_path: Path):
        """index_file called from async context must succeed, not raise."""
        from app.services import indexer as indexer_module

        async def fake_embed(texts):
            import numpy as np

            return np.zeros((len(texts), 8), dtype=np.float32)

        monkeypatch.setattr(indexer_module.embedder_module, "embed_batch", fake_embed)
        monkeypatch.setenv("LANCEDB_PATH", str(tmp_path / "lancedb"))

        from app.config import get_settings

        get_settings.cache_clear()
        try:
            idx = LanceIndexer()
            target = tmp_path / "note.md"
            target.write_text("# Note\n\nSome body text for the chunker.\n", encoding="utf-8")

            async def driver():
                # Sync call from async context — the exact shape that used
                # to blow up inside the lifespan hook.
                return idx.index_file(target, target.read_text(encoding="utf-8"))

            status = asyncio.run(driver())
            assert status.status == "ok", status.error
            assert status.chunk_count >= 1
        finally:
            get_settings.cache_clear()


class TestStartupReconcileNotSilentlySwallowed:
    def test_lifespan_records_reconcile_error(self, monkeypatch, tmp_path: Path):
        """A failing startup reconcile must be visible on app.state.

        The original bug was invisible because lifespan caught the exception
        and only logged it. Now the error is surfaced so it can be asserted.
        """
        from app.services import sync as sync_module

        monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
        monkeypatch.setenv("LANCEDB_PATH", str(tmp_path / "lancedb"))

        from app.config import get_settings

        get_settings.cache_clear()

        def boom(*_args, **_kwargs):
            raise RuntimeError("reconcile exploded")

        monkeypatch.setattr(sync_module.VaultIndexer, "startup_reconcile", boom)

        try:
            from fastapi.testclient import TestClient

            with TestClient(app) as client:
                err = getattr(client.app.state, "startup_reconcile_error", "missing")
                assert err != "missing", "lifespan did not record the reconcile outcome"
                assert err is not None, "reconcile error was swallowed"
                assert "reconcile exploded" in err
        finally:
            get_settings.cache_clear()
