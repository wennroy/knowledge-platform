"""Async embedding client targeting the gateway /embeddings endpoint."""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from typing import Any

import httpx
import numpy as np

from app.config import get_settings
from app.metrics import kb_embedding_latency_seconds

log = logging.getLogger(__name__)

# Conservative batch size to avoid request size limits.
MAX_BATCH = 64


class EmbedderError(Exception):
    """Raised when the embedding service fails after retries."""


def _split_batches(texts: Sequence[str], size: int) -> list[list[str]]:
    return [list(texts[i : i + size]) for i in range(0, len(texts), size)]


def _new_client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    """Build the AsyncClient. Tests may override by monkeypatching this symbol."""
    kwargs: dict[str, Any] = {"timeout": 60.0}
    if transport is not None:
        kwargs["transport"] = transport
    return httpx.AsyncClient(**kwargs)


async def _post_embeddings(
    client: httpx.AsyncClient,
    payload: dict,
    base_url: str,
    api_key: str,
) -> list[list[float]]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url = f"{base_url.rstrip('/')}/embeddings"
    response = await client.post(url, json=payload, headers=headers)
    response.raise_for_status()
    body = response.json()

    # Accept either OpenAI-style {data:[{embedding:[]}]} or {"embeddings":[[]]}
    if isinstance(body, dict) and "data" in body and isinstance(body["data"], list):
        vectors = [item.get("embedding") for item in body["data"]]
    elif isinstance(body, dict) and "embeddings" in body:
        vectors = body["embeddings"]
    else:  # pragma: no cover - depends on gateway schema
        raise EmbedderError(f"unexpected embeddings response: {body!r}")

    for v in vectors:
        if v is None:
            raise EmbedderError("embedding missing in response")
    return vectors  # type: ignore[return-value]


async def embed_batch(texts: Sequence[str]) -> np.ndarray:
    """Embed ``texts`` via the gateway with batching and exponential backoff."""
    s = get_settings()
    if not texts:
        return np.zeros((0, s.EMBEDDING_DIM), dtype=np.float32)

    start = time.perf_counter()
    batches = _split_batches(list(texts), MAX_BATCH)
    all_vectors: list[list[float]] = []

    async with _new_client() as client:
        for batch in batches:
            payload = {"input": batch, "model": s.EMBEDDING_MODEL}
            attempt = 0
            last_exc: Exception | None = None
            while attempt < 3:
                try:
                    vectors = await _post_embeddings(client, payload, s.GATEWAY_BASE_URL, s.GATEWAY_API_KEY)
                    if len(vectors) != len(batch):
                        raise EmbedderError(
                            f"embedding count mismatch: got {len(vectors)} for {len(batch)} inputs"
                        )
                    all_vectors.extend(vectors)
                    last_exc = None
                    break
                except (httpx.HTTPError, EmbedderError) as exc:
                    last_exc = exc
                    delay = 2**attempt
                    log.warning(
                        "embed attempt %s failed: %s; retrying in %ss",
                        attempt + 1,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    attempt += 1
            if last_exc is not None:
                kb_embedding_latency_seconds.observe(time.perf_counter() - start)
                raise EmbedderError(f"embedding failed after 3 attempts: {last_exc}") from last_exc

    arr = np.asarray(all_vectors, dtype=np.float32)
    if arr.ndim != 2:
        raise EmbedderError(f"unexpected embedding shape: {arr.shape}")
    kb_embedding_latency_seconds.observe(time.perf_counter() - start)
    return arr


def embed_batch_sync(texts: Sequence[str]) -> np.ndarray:
    """Synchronous wrapper for tests / non-async contexts."""
    return asyncio.run(embed_batch(texts))
