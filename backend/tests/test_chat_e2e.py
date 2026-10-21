"""End-to-end tests for the OpenAI-compatible chat route.

The gateway is mocked via ``httpx.MockTransport`` so no real network call ever
leaves the test boundary. The retriever is stubbed by monkeypatching
``app.routes.chat._get_retriever`` to return a ``Retriever`` whose ``retrieve``
method yields a fixed list of ``RetrievalResult`` objects. This exercises the
full HTTP path (request parsing -> retrieval -> gateway forwarding -> SSE
tail / non-stream JSON) without external dependencies.
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
_FIXED_RESULTS = [
    RetrievalResult(
        file_path="/vault/team/alpha.md",
        chunk_index=0,
        heading_path=["Alpha", "Intro"],
        text="alpha content",
        score=0.9,
        chunk_id="c-1",
    ),
    RetrievalResult(
        file_path="/vault/team/beta.md",
        chunk_index=2,
        heading_path=["Beta"],
        text="beta content",
        score=0.5,
        chunk_id="c-2",
    ),
]


@dataclass
class _FakeIndexer:
    lancedb_path: Path


def _stub_retriever() -> Retriever:
    fake = Retriever(_FakeIndexer(lancedb_path=Path("/tmp/lance")))  # type: ignore[arg-type]
    # Replace the real search path with a fixed list — never touches LanceDB.
    fake.retrieve = lambda query, top_k=8: list(_FIXED_RESULTS)  # type: ignore[assignment]
    return fake


@pytest.fixture
def stub_retriever(monkeypatch):
    monkeypatch.setattr(chat_module, "_get_retriever", _stub_retriever)
    return _FIXED_RESULTS


# ---------------------------------------------- httpx.MockTransport helper
class _GatewayMock:
    """Captures gateway requests and returns scripted responses."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch):
        self.requests: list[httpx.Request] = []
        self._monkeypatch = monkeypatch
        self._handler = self._default_handler
        self._transport = httpx.MockTransport(self._handle)

        real_async_client = httpx.AsyncClient

        def factory(*args: Any, **kwargs: Any):
            kwargs["transport"] = self._transport
            return real_async_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)

    @staticmethod
    def _default_handler(request: httpx.Request) -> httpx.Response:
        # Default: succeed with an empty SSE body so tests that forget to
        # set a handler still see a streaming response.
        return httpx.Response(
            200,
            content=b"data: [DONE]\n\n",
            headers={"Content-Type": "text/event-stream"},
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)

    def set_handler(self, handler):
        self._handler = handler

    # Common scripted responses
    @staticmethod
    def stream_response(parts: list[dict[str, Any]]) -> httpx.Response:
        body = b"".join(
            f"data: {json.dumps(p, ensure_ascii=False, separators=(',', ':'))}\n\n".encode()
            for p in parts
        ) + b"data: [DONE]\n\n"
        return httpx.Response(
            200,
            content=body,
            headers={"Content-Type": "text/event-stream"},
        )

    @staticmethod
    def json_chat_response(content: str) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    @staticmethod
    def error_response(status: int, msg: str = "boom") -> httpx.Response:
        return httpx.Response(status, json={"error": msg})


@pytest.fixture
def gateway(monkeypatch) -> _GatewayMock:
    return _GatewayMock(monkeypatch)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


# ------------------------------------------------------------------ stream
def test_stream_request_to_gateway_has_correct_payload(
    client: TestClient, gateway: _GatewayMock, stub_retriever
):
    captured_payloads: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.content))
        return _GatewayMock.stream_response(
            [{"choices": [{"delta": {"content": "hi"}}]}]
        )

    gateway.set_handler(handler)

    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "ignored-by-backend",
            "messages": [{"role": "user", "content": "what is alpha?"}],
            "stream": True,
            "temperature": 0.3,
        },
    ) as response:
        assert response.status_code == 200
        # Force the streaming generator to run end-to-end.
        chunks = list(response.iter_text())

    assert len(captured_payloads) == 1
    payload = captured_payloads[0]
    assert payload["model"] == "test-chat"  # from conftest.py CHAT_MODEL
    assert payload["stream"] is True
    assert payload["temperature"] == 0.3
    msgs = payload["messages"]
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert "vault" in msgs[0]["content"].lower()
    assert "reference" in msgs[0]["content"].lower() or "cite" in msgs[0]["content"].lower()
    assert msgs[1]["role"] == "user"
    user_content = msgs[1]["content"]
    assert "what is alpha?" in user_content
    assert "[1]" in user_content and "alpha content" in user_content
    assert "[2]" in user_content and "beta content" in user_content
    # Final streaming bytes should end with [DONE].
    assert "data: [DONE]" in "".join(chunks)


def test_stream_response_forwards_gateway_chunks(
    client: TestClient, gateway: _GatewayMock, stub_retriever
):
    gateway.set_handler(
        lambda req: _GatewayMock.stream_response(
            [
                {"choices": [{"delta": {"content": "Hello"}}]},
                {"choices": [{"delta": {"content": " world"}}]},
                {"choices": [{"delta": {"content": "!"}}]},
            ]
        )
    )

    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as response:
        assert response.status_code == 200
        body = b"".join(response.iter_bytes()).decode("utf-8")

    # Parse out data: lines and verify the content stream.
    data_lines = [
        line[len("data: "):]
        for line in body.split("\n")
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    payloads = [json.loads(line) for line in data_lines]

    forwarded = [
        p for p in payloads if "choices" in p and p.get("type") != "references"
    ]
    assert len(forwarded) == 3
    assert [c["choices"][0]["delta"]["content"] for c in forwarded] == [
        "Hello",
        " world",
        "!",
    ]

    # References event
    refs = [p for p in payloads if p.get("type") == "references"]
    assert len(refs) == 1
    assert len(refs[0]["references"]) == 2
    assert refs[0]["references"][0]["file_path"] == "/vault/team/alpha.md"
    assert refs[0]["references"][0]["heading"] == "Alpha > Intro"
    assert refs[0]["references"][0]["chunk_id"] == "c-1"

    # The references event comes BEFORE the final [DONE]
    refs_idx = body.find('"type": "references"')
    done_idx = body.rfind("data: [DONE]")
    assert refs_idx != -1 and done_idx != -1
    assert refs_idx < done_idx


def test_stream_response_references_event_has_full_metadata(
    client: TestClient, gateway: _GatewayMock, stub_retriever
):
    gateway.set_handler(
        lambda req: _GatewayMock.stream_response(
            [{"choices": [{"delta": {"content": "ok"}}]}]
        )
    )

    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "q"}], "stream": True},
    ) as response:
        raw = b"".join(response.iter_bytes()).decode("utf-8")

    # Locate the references event line and parse it.
    ref_line = next(
        (line for line in raw.split("\n") if line.startswith("data:") and "references" in line),
        None,
    )
    assert ref_line is not None
    payload = json.loads(ref_line[len("data: ") :])
    assert payload["type"] == "references"
    refs = payload["references"]
    assert len(refs) == 2
    assert refs[0]["file_path"] == "/vault/team/alpha.md"
    assert refs[0]["heading"] == "Alpha > Intro"
    assert refs[0]["chunk_id"] == "c-1"
    assert isinstance(refs[0]["score"], float)


# ------------------------------------------------------------------ non-stream
def test_non_stream_response_returns_json_with_references_injected(
    client: TestClient, gateway: _GatewayMock, stub_retriever
):
    gateway.set_handler(
        lambda req: _GatewayMock.json_chat_response("Here is what I found.")
    )

    response = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "give me alpha info"}],
            "stream": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["role"] == "assistant"
    content = body["choices"][0]["message"]["content"]
    assert content.startswith("Here is what I found.")
    # Markdown references appended
    assert "References:" in content
    assert "[1] /vault/team/alpha.md#Alpha > Intro" in content
    assert "c-1" not in content  # non-stream body does not embed chunk ids
    # Original non-stream payload's usage field survives
    assert body["usage"]["total_tokens"] == 15


def test_non_stream_request_sends_stream_false_to_gateway(
    client: TestClient, gateway: _GatewayMock, stub_retriever
):
    """The non-stream branch always sends stream=False to the gateway."""
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return _GatewayMock.json_chat_response("OK")

    gateway.set_handler(handler)

    client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "x"}], "stream": False},
    )

    assert captured[0]["stream"] is False


# ------------------------------------------------------------------ errors
def test_empty_messages_returns_400(client: TestClient, gateway: _GatewayMock):
    response = client.post(
        "/v1/chat/completions", json={"messages": [], "stream": False}
    )
    assert response.status_code == 400
    detail = response.json()["detail"]["error"]["message"].lower()
    assert "messages" in detail


def test_no_user_message_returns_400(client: TestClient, gateway: _GatewayMock):
    response = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "system", "content": "no user here"}],
            "stream": False,
        },
    )
    assert response.status_code == 400
    detail = response.json()["detail"]["error"]["message"].lower()
    assert "user" in detail


def test_stream_gateway_5xx_surfaces_as_sse_error_event(
    client: TestClient, gateway: _GatewayMock, stub_retriever
):
    """In stream mode, HTTP status is 200; the error appears as an SSE event."""
    gateway.set_handler(lambda req: _GatewayMock.error_response(502, "bad gateway"))

    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "x"}], "stream": True},
    ) as response:
        assert response.status_code == 200
        body = b"".join(response.iter_bytes()).decode("utf-8")

    # Parse out data: lines and locate the error event.
    data_lines = [
        line[len("data: "):]
        for line in body.split("\n")
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    payloads = [json.loads(line) for line in data_lines]
    errors = [p for p in payloads if "error" in p]
    assert len(errors) == 1
    assert errors[0]["error"]["type"] == "upstream_error"
    assert "502" in errors[0]["error"]["message"]

    # Ends with [DONE].
    assert body.rstrip().endswith("data: [DONE]")
    # No references event is appended when the upstream failed.
    assert not any(p.get("type") == "references" for p in payloads)


def test_non_stream_gateway_5xx_returns_502(
    client: TestClient, gateway: _GatewayMock, stub_retriever
):
    gateway.set_handler(lambda req: _GatewayMock.error_response(500, "internal"))

    response = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "x"}], "stream": False},
    )
    assert response.status_code == 502


def test_retriever_failure_returns_500(client: TestClient, gateway: _GatewayMock, monkeypatch):
    from app.services.retriever import RetrieverError

    def boom():
        r = Retriever(_FakeIndexer(lancedb_path=Path("/tmp/lance")))  # type: ignore[arg-type]

        def _raise(query, top_k=8):
            raise RetrieverError("vault is on fire")

        r.retrieve = _raise  # type: ignore[assignment]
        return r

    monkeypatch.setattr(chat_module, "_get_retriever", boom)

    response = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "x"}], "stream": False},
    )
    assert response.status_code == 500
    detail = response.json()["detail"]["error"]["message"].lower()
    assert "retrieval" in detail


def test_temperature_default_is_applied(client: TestClient, gateway: _GatewayMock, stub_retriever):
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return _GatewayMock.json_chat_response("ok")

    gateway.set_handler(handler)

    client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "x"}]},  # no temperature
    )
    assert captured[0]["temperature"] == 0.3


def test_invalid_temperature_falls_back(client: TestClient, gateway: _GatewayMock, stub_retriever):
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return _GatewayMock.json_chat_response("ok")

    gateway.set_handler(handler)

    client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "x"}],
            "temperature": "hot",
        },
    )
    assert captured[0]["temperature"] == 0.3


def test_user_content_as_list_is_concatenated(
    client: TestClient, gateway: _GatewayMock, stub_retriever
):
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return _GatewayMock.json_chat_response("ok")

    gateway.set_handler(handler)

    client.post(
        "/v1/chat/completions",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "first part"},
                        {"type": "text", "text": "second part"},
                    ],
                }
            ]
        },
    )
    user_msg = next(m for m in captured[0]["messages"] if m["role"] == "user")
    assert "first part" in user_msg["content"]
    assert "second part" in user_msg["content"]


# ------------------------------------------------------------------ http headers
def test_upstream_request_includes_authorization_header(
    client: TestClient, gateway: _GatewayMock, stub_retriever
):
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(dict(request.headers))
        return _GatewayMock.json_chat_response("ok")

    gateway.set_handler(handler)

    client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "x"}], "stream": False},
    )
    # conftest.py sets GATEWAY_API_KEY=test-key
    assert seen_headers.get("authorization") == "Bearer test-key"


def test_url_concatenates_chat_completions(
    client: TestClient, gateway: _GatewayMock, stub_retriever
):
    seen_url: str = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_url
        seen_url = str(request.url)
        return _GatewayMock.json_chat_response("ok")

    gateway.set_handler(handler)

    client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "x"}], "stream": False},
    )
    # conftest.py sets GATEWAY_BASE_URL=http://test-gateway.local/v1
    assert seen_url == "http://test-gateway.local/v1/chat/completions"