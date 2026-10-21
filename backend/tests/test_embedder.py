"""embedder tests with httpx mocked via MockTransport (no real gateway calls)."""
from __future__ import annotations

import json

import httpx
import numpy as np
import pytest

from app.services import embedder
from app.services.embedder import embed_batch


def _make_client_factory(handler):
    """Build an _new_client replacement that injects a MockTransport."""
    transport = httpx.MockTransport(handler)

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return httpx.AsyncClient(*args, **kwargs)

    return factory


@pytest.mark.asyncio
async def test_embed_batch_returns_float32_array(monkeypatch):
    dim = 8  # matches EMBEDDING_DIM=8 from conftest
    vectors = [[0.1] * dim, [0.2] * dim, [0.3] * dim]

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        n = len(body.get("input", []))
        return httpx.Response(
            200,
            json={"data": [{"embedding": list(v)} for v in vectors[:n]]},
        )

    monkeypatch.setattr(embedder, "_new_client", _make_client_factory(handler))

    out = await embed_batch(["a", "b", "c"])
    assert isinstance(out, np.ndarray)
    assert out.dtype == np.float32
    assert out.shape == (3, dim)


@pytest.mark.asyncio
async def test_embed_batch_batches_large_input(monkeypatch):
    dim = 8
    [[0.01 * i] * dim for i in range(130)]
    seen_payloads: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payloads.append(request.content.decode("utf-8"))
        body = json.loads(seen_payloads[-1])
        n = len(body.get("input", []))
        return httpx.Response(
            200,
            json={"data": [{"embedding": [0.0] * dim} for _ in range(n)]},
        )

    monkeypatch.setattr(embedder, "_new_client", _make_client_factory(handler))

    texts = [f"text-{i}" for i in range(130)]
    out = await embed_batch(texts)
    assert out.shape == (130, dim)
    # 130 inputs / 64 batch -> 3 batches
    assert len(seen_payloads) == 3
    # First two batches should be full 64; last should be 2.
    sizes = [len(json.loads(p)["input"]) for p in seen_payloads]
    assert sizes == [64, 64, 2]


@pytest.mark.asyncio
async def test_embed_batch_retries_on_http_error(monkeypatch):
    dim = 8
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 2:
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(
            200,
            json={"data": [{"embedding": [0.5] * dim}]},
        )

    monkeypatch.setattr(embedder, "_new_client", _make_client_factory(handler))
    # Speed up backoff for the test
    async def _no_sleep(*_a, **_k):
        return None
    monkeypatch.setattr(embedder.asyncio, "sleep", _no_sleep)

    out = await embed_batch(["only"])
    assert out.shape == (1, dim)
    assert attempts["n"] == 2


@pytest.mark.asyncio
async def test_embed_batch_raises_after_three_failures(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"error": "bad gateway"})

    monkeypatch.setattr(embedder, "_new_client", _make_client_factory(handler))
    async def _no_sleep(*_a, **_k):
        return None
    monkeypatch.setattr(embedder.asyncio, "sleep", _no_sleep)

    with pytest.raises(embedder.EmbedderError):
        await embed_batch(["x"])


@pytest.mark.asyncio
async def test_embed_batch_empty_input():
    out = await embed_batch([])
    assert out.shape == (0, 8)
