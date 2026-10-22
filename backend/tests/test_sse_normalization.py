"""SSE normalisation: the backend owns the end of the stream.

The upstream gateway is an OpenAI-compatible proxy that may terminate its own
stream (``data: [DONE]``) and may emit its own ``references`` events. Both
were forwarded verbatim, which meant the client could see two ``[DONE]``
markers and two reference lists with conflicting numbering.

The backend now forwards the gateway's delta frames untouched, drops the
gateway's ``[DONE]`` and ``references`` frames, and appends exactly one
references event plus one ``[DONE]`` of its own.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

import app.routes.chat as chat_module
from app.main import app
from app.services.retriever import RetrievalResult, Retriever

# ------------------------------------------------------------------ fixtures


@dataclass
class _FakeIndexer:
    lancedb_path: Path


_REFERENCES = [
    RetrievalResult(
        file_path="team/alpha.md",
        chunk_index=0,
        heading_path=["Alpha"],
        text="alpha content",
        score=0.9,
        chunk_id="c-1",
    ),
]


@pytest.fixture
def stub_retriever(monkeypatch):
    fake = Retriever(_FakeIndexer(lancedb_path=Path("/tmp/lance")))  # type: ignore[arg-type]
    fake.retrieve = lambda query, top_k=8: list(_REFERENCES)  # type: ignore[assignment]
    monkeypatch.setattr(chat_module, "_get_retriever", lambda: fake)
    return _REFERENCES


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def gateway(monkeypatch):
    """Return a factory that scripts the gateway's raw SSE body."""
    state: dict[str, Any] = {"body": b"", "status": 200}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["status"] >= 400:
            return httpx.Response(state["status"], json={"error": "boom"})
        return httpx.Response(
            200,
            content=state["body"],
            headers={"Content-Type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return state


def _stream(client: TestClient) -> str:
    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "q"}], "stream": True},
    ) as response:
        assert response.status_code == 200
        return b"".join(response.iter_bytes()).decode("utf-8")


def _data_payloads(raw: str) -> list[Any]:
    out: list[Any] = []
    for line in raw.split("\n"):
        if not line.startswith("data: "):
            continue
        body = line[len("data: ") :]
        if body == "[DONE]":
            out.append("[DONE]")
            continue
        try:
            out.append(json.loads(body))
        except ValueError:
            out.append(body)
    return out


# ------------------------------------------------------------------ unit level


def test_normalize_sse_drops_gateway_done():
    from app.routes.chat import normalize_sse

    raw = b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n'
    out = normalize_sse(raw)
    assert out == b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'


def test_normalize_sse_drops_gateway_references():
    from app.routes.chat import normalize_sse

    raw = (
        b'data: {"type":"references","references":[{"file_path":"gw.md"}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
    )
    out = normalize_sse(raw)
    assert b'"references"' not in out
    assert b"hi" in out


def test_normalize_sse_keeps_unknown_frames():
    from app.routes.chat import normalize_sse

    raw = (
        b": keep-alive\n\n"
        b"event: ping\n\n"
        b"data: not-json-at-all\n\n"
        b"data: {\"type\":\"other\"}\n\n"
    )
    assert normalize_sse(raw) == raw


def test_normalize_sse_keeps_frame_boundaries():
    from app.routes.chat import normalize_sse

    raw = b"data: a\r\n\r\ndata: b\r\n\r\n"
    assert normalize_sse(raw) == raw


# ------------------------------------------------------------------ HTTP level


def test_client_receives_exactly_one_done(
    client: TestClient, gateway, stub_retriever
):
    gateway["body"] = (
        b'data: {"choices":[{"delta":{"content":"A"}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    raw = _stream(client)
    assert raw.count("data: [DONE]") == 1
    assert raw.rstrip().endswith("data: [DONE]")


def test_gateway_references_event_is_filtered_out(
    client: TestClient, gateway, stub_retriever
):
    gateway["body"] = (
        b'data: {"choices":[{"delta":{"content":"A"}}]}\n\n'
        b'data: {"type":"references","references":[{"file_path":"gateway/own.md"}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"B"}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    raw = _stream(client)
    payloads = _data_payloads(raw)
    ref_events = [p for p in payloads if isinstance(p, dict) and p.get("type") == "references"]
    # Exactly one references event — ours.
    assert len(ref_events) == 1
    assert ref_events[0]["references"][0]["file_path"] == "team/alpha.md"
    assert "gateway/own.md" not in raw


def test_gateway_deltas_are_forwarded_verbatim(
    client: TestClient, gateway, stub_retriever
):
    gateway["body"] = (
        b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":" world"}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    raw = _stream(client)
    payloads = _data_payloads(raw)
    forwarded = [
        p
        for p in payloads
        if isinstance(p, dict) and "choices" in p and p.get("type") != "references"
    ]
    assert [c["choices"][0]["delta"]["content"] for c in forwarded] == [
        "Hello",
        " world",
    ]
    # Byte-for-byte: the gateway's frames are not re-serialised.
    assert 'data: {"choices":[{"delta":{"content":"Hello"}}]}' in raw


def test_non_json_data_frame_is_forwarded(client: TestClient, gateway, stub_retriever):
    gateway["body"] = b"data: plain-text-payload\n\ndata: [DONE]\n\n"
    raw = _stream(client)
    assert "data: plain-text-payload" in raw
    assert raw.count("data: [DONE]") == 1


def test_non_data_lines_are_forwarded(client: TestClient, gateway, stub_retriever):
    gateway["body"] = (
        b": heartbeat\n\n"
        b"event: custom-event\n\n"
        b'data: {"choices":[{"delta":{"content":"x"}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    raw = _stream(client)
    assert ": heartbeat" in raw
    assert "event: custom-event" in raw
    assert raw.count("data: [DONE]") == 1


def test_gateway_error_yields_error_event_and_single_done(
    client: TestClient, gateway, stub_retriever
):
    gateway["status"] = 502
    raw = _stream(client)
    payloads = _data_payloads(raw)
    errors = [p for p in payloads if isinstance(p, dict) and "error" in p]
    assert len(errors) == 1
    assert errors[0]["error"]["type"] == "upstream_error"
    assert raw.count("data: [DONE]") == 1
    # No references event when the upstream failed.
    assert not any(
        isinstance(p, dict) and p.get("type") == "references" for p in payloads
    )
