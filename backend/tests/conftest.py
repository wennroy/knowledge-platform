"""Shared test fixtures.

Tests must NOT require an external gateway, GPU, or working internet.
We monkeypatch ``httpx`` for embedder tests and use tmp_path for all I/O.
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Every test gets a clean working directory + isolated .env-derived paths."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GATEWAY_BASE_URL", "http://test-gateway.local/v1")
    monkeypatch.setenv("GATEWAY_API_KEY", "test-key")
    monkeypatch.setenv("EMBEDDING_MODEL", "test-embed")
    monkeypatch.setenv("CHAT_MODEL", "test-chat")
    monkeypatch.setenv("EMBEDDING_DIM", "8")
    monkeypatch.setenv("LANCEDB_PATH", str(tmp_path / "lancedb"))
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setenv("CHUNK_TOKENS", "64")
    monkeypatch.setenv("CHUNK_OVERLAP", "8")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    # Reset cached settings
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
