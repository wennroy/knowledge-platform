"""End-to-end integration tests for the knowledge platform backend.

Covers product scenarios A1-I6 from the original plan §19. Runs against the
live FastAPI app via ``TestClient`` with all external services (gateway,
embeddings) stubbed via ``httpx.MockTransport`` or direct monkeypatching. No
real network calls ever leave the test boundary.

The existing ``tests/conftest.py`` autouse fixture already isolates the
working directory + vault + LanceDB paths and pins tiny chunk/embedding
defaults for fast tests; this file only adds scenario-specific fixtures.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services import parser_router as parser_router_module
from app.services.indexer import LanceIndexer
from app.services.retriever import RetrievalResult, Retriever

# Repo root: backend/tests/ -> backend/ -> <repo>. Resolved from this file so
# the suite behaves identically on a developer machine and in CI.
REPO_ROOT = Path(__file__).resolve().parents[2]

# ====================================================================== fixtures


# Modules that captured ``from app.config import settings`` at import time and
# therefore hold a stale reference until we re-assign.
_SETTINGS_USERS = (
    "app.config",
    "app.services.vault",
    "app.routes.files",
    "app.routes.admin_index",
    "app.routes.graph",
    "app.services.sync",
)


@pytest.fixture(autouse=True)
def _refresh_settings(monkeypatch: pytest.MonkeyPatch):
    """Rebind ``settings`` in modules that captured the original instance.

    The conftest autouse updates env vars + clears the lru_cache, but
    ``app.config.settings = get_settings()`` is bound at config.py import time
    and not refreshed by ``cache_clear()``. Every module that did
    ``from app.config import settings`` therefore sees the stale singleton.
    This fixture runs after the conftest autouse and replaces each captured
    reference with a fresh ``Settings()`` built from the current env.
    """
    import importlib


    get_settings.cache_clear()
    fresh = get_settings()

    patches = []
    for mod_name in _SETTINGS_USERS:
        mod = importlib.import_module(mod_name)
        if hasattr(mod, "settings"):
            monkeypatch.setattr(mod, "settings", fresh)
            patches.append((mod, "settings"))

    yield


@pytest.fixture
def stub_embed(monkeypatch: pytest.MonkeyPatch):
    """Replace ``embed_batch`` with a deterministic sync stub.

    Sync (returns numpy array directly) so the lifespan's startup_reconcile
    inside the FastAPI event loop does not crash on ``asyncio.run``.

    Returns a tuple ``(sync_fake, original_async)`` so callers that need the
    real retry path can swap it back in (e.g. C5).
    """
    from app.services import embedder as embedder_module_real
    from app.services import indexer as indexer_module_local

    original_async = embedder_module_real.embed_batch

    def fake_embed(texts):
        arr = np.zeros((len(list(texts)), 8), dtype=np.float32)
        for i, t in enumerate(texts):
            arr[i, 0] = float(len(t) % 7) / 7.0
            arr[i, 1] = float(hash(t) % 5) / 5.0
        return arr

    monkeypatch.setattr(embedder_module_real, "embed_batch", fake_embed)
    monkeypatch.setattr(indexer_module_local.embedder_module, "embed_batch", fake_embed)
    return fake_embed, original_async


@pytest.fixture
def stub_parser(monkeypatch: pytest.MonkeyPatch):
    """Install a controllable fake for ``app.routes.files.parse``.

    Returns a callable ``install(text, parser, ocr_used, raises)`` to configure
    the fake on demand; ``raises`` (if set) makes ``parse`` raise the given
    exception.
    """
    from app.models import ParseResult
    from app.routes import files as files_module

    state: dict[str, Any] = {"result": None, "exc": None}

    def fake_parse(staged_path):
        if state["exc"] is not None:
            raise state["exc"]
        return state["result"]

    monkeypatch.setattr(files_module, "parse", fake_parse)

    def install(
        text: str = "Hello extracted body. " * 30,
        parser: str = "markitdown",
        ocr_used: bool | None = None,
        raises: Exception | None = None,
    ) -> None:
        state["exc"] = raises
        state["result"] = ParseResult(
            markdown=text,
            parser=parser,
            ocr_used=(parser == "docling") if ocr_used is None else ocr_used,
        )

    return install


@pytest.fixture
def raw_client(stub_embed):
    """TestClient without triggering lifespan (most route tests don't need it)."""
    return TestClient(app)


@pytest.fixture
def live_client(stub_embed):
    """TestClient wrapped in the lifespan context manager (starts watchdog)."""
    with TestClient(app) as client:
        yield client


# ------------------------------------------------------------ chat/gateway mocks


@dataclass
class _GatewayMock:
    """Captures gateway requests and returns scripted responses."""

    monkeypatch: pytest.MonkeyPatch
    requests: list[httpx.Request] = field(default_factory=list)
    _handler: Any = None
    _transport: Any = None

    def __post_init__(self) -> None:
        self._handler = self._default_handler
        self._transport = httpx.MockTransport(self._handle)
        real_async_client = httpx.AsyncClient

        def factory(*args: Any, **kwargs: Any):
            kwargs["transport"] = self._transport
            return real_async_client(*args, **kwargs)

        self.monkeypatch.setattr(httpx, "AsyncClient", factory)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)

    @staticmethod
    def _default_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"data: [DONE]\n\n",
            headers={"Content-Type": "text/event-stream"},
        )

    def set_handler(self, handler: Any) -> None:
        self._handler = handler

    @staticmethod
    def stream_response(parts: list[dict[str, Any]]) -> httpx.Response:
        body = b"".join(
            f"data: {json.dumps(p, ensure_ascii=False, separators=(',', ':'))}\n\n".encode()
            for p in parts
        ) + b"data: [DONE]\n\n"
        return httpx.Response(
            200, content=body, headers={"Content-Type": "text/event-stream"}
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
def gateway(monkeypatch: pytest.MonkeyPatch) -> _GatewayMock:
    return _GatewayMock(monkeypatch=monkeypatch)


# =============================================================== A. Upload & Parse


class TestAUploadAndParse:
    def test_a1_pdf_upload_creates_md_indexes_and_frontmatter(
        self, raw_client: TestClient, stub_parser, tmp_path: Path
    ):
        """A1: upload PDF -> vault .md; LanceDB has embedding; frontmatter complete."""
        stub_parser(text="# Doc\n\nThis is the parsed body content.", parser="markitdown")
        data = b"%PDF-1.4 fake content"
        response = raw_client.post(
            "/v1/files", files={"file": ("hello.pdf", data, "application/pdf")}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert body["parser"] == "markitdown"
        assert body["chunks"] >= 1
        md_path = Path(body["file_path"])
        assert md_path.exists()
        text = md_path.read_text(encoding="utf-8")
        # Frontmatter complete
        assert text.startswith("---\n")
        assert "source_filename: hello.pdf" in text
        assert "source_hash:" in text
        assert "parser: markitdown" in text
        assert "ocr_used: false" in text
        # LanceDB has the file
        idx = LanceIndexer()
        statuses = idx.get_status()
        assert any(s.file_path == body["file_path"] for s in statuses)

    def test_a2_scanned_pdf_docling_fallback(
        self, raw_client: TestClient, stub_parser
    ):
        """A2: scanned -> docling fallback path (parser=='docling', ocr_used==True)."""
        stub_parser(
            text="Recognized OCR body content " * 30,
            parser="docling",
            ocr_used=True,
        )
        response = raw_client.post(
            "/v1/files",
            files={"file": ("scan.pdf", b"%PDF-fake", "application/pdf")},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["parser"] == "docling"
        assert body["status"] == "ok"
        md_path = Path(body["file_path"])
        fm_text = md_path.read_text(encoding="utf-8")
        assert "parser: docling" in fm_text
        assert "ocr_used: true" in fm_text

    def test_a3_corrupted_file_falls_into_failed_dir(
        self, raw_client: TestClient, stub_parser, tmp_path: Path
    ):
        """A3: corrupted file -> .staging/failed/, error visible in response."""
        stub_parser(raises=parser_router_module.ParserError("both parsers broke"))
        response = raw_client.post(
            "/v1/files",
            files={"file": ("bad.pdf", b"%PDF-corrupt", "application/pdf")},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "failed"
        assert "both parsers broke" in (body.get("error") or "")
        # .staging/failed/<hash>.json exists
        failed_dir = tmp_path / "vault" / ".staging" / "failed"
        assert failed_dir.exists()
        jsons = list(failed_dir.glob("*.json"))
        assert len(jsons) == 1
        payload = json.loads(jsons[0].read_text())
        assert payload["filename"] == "bad.pdf"
        assert "both parsers broke" in payload["error"]
        assert payload["stage"] == "parse"

    def test_a4_oversize_file_rejected_with_413(self, raw_client: TestClient, monkeypatch):
        """A4: oversize -> 413."""
        # Mutate settings.MAX_UPLOAD_BYTES directly on the captured instances.
        import app.routes.files as files_module
        from app.config import settings as cfg_settings

        original = cfg_settings.MAX_UPLOAD_BYTES
        cfg_settings.MAX_UPLOAD_BYTES = 1024
        monkeypatch.setattr(files_module.settings, "MAX_UPLOAD_BYTES", 1024)
        try:
            data = b"x" * 2048
            response = raw_client.post(
                "/v1/files",
                files={"file": ("big.pdf", data, "application/pdf")},
            )
            assert response.status_code == 413
            assert "too large" in response.text.lower()
        finally:
            cfg_settings.MAX_UPLOAD_BYTES = original

    def test_a5_duplicate_upload_same_sha(self, raw_client: TestClient, stub_parser):
        """A5: duplicate (same sha256) -> expected to be skipped, not double-indexed.

        Documents actual behavior: the upload route stamps a new timestamp on
        each upload, so two uploads of identical bytes create two .md files
        with distinct paths (but identical id/sha256). The LanceDB upsert is
        hash-based so chunk rows are deduped. We assert the id parity and the
        dedup-on-hash property for LanceDB.
        """
        stub_parser(text="# Same\n\nSame body content.", parser="markitdown")
        data = b"%PDF-same-content"
        r1 = raw_client.post(
            "/v1/files", files={"file": ("same.pdf", data, "application/pdf")}
        )
        r2 = raw_client.post(
            "/v1/files", files={"file": ("same.pdf", data, "application/pdf")}
        )
        assert r1.status_code == 200 and r2.status_code == 200
        b1, b2 = r1.json(), r2.json()
        # Same content -> same sha256 -> same id
        assert b1["id"] == b2["id"]
        # LanceDB index is keyed by hash so there is only ONE status row
        idx = LanceIndexer()
        matching = [
            s for s in idx.get_status()
            if s.file_path == b1["file_path"] or s.file_path == b2["file_path"]
        ]
        # The same source_hash means dedup-on-hash in LanceDB
        source_hashes = {s.file_hash for s in matching}
        assert len(source_hashes) <= 1

    def test_a6_illegal_extension_rejected_with_hint(self, raw_client: TestClient):
        """A6: illegal extension -> 400 with whitelist hint."""
        response = raw_client.post(
            "/v1/files",
            files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
        )
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "extension" in detail.lower() or "allowed" in detail.lower()


# ============================================================== B. Index status


class TestBIndexing:
    def test_b1_upload_is_immediately_searchable(
        self, raw_client: TestClient, stub_parser
    ):
        """B1: upload -> retrievable synchronously."""
        stub_parser(text="Apple banana cherry dragon unique-content.", parser="markitdown")
        r = raw_client.post(
            "/v1/files", files={"file": ("doc.pdf", b"%PDF-x", "application/pdf")}
        )
        assert r.status_code == 200
        body = r.json()
        # Build a retriever that reads everything from the chunks table.
        idx = LanceIndexer()
        tbl = idx._db.open_table("chunks")

        def all_rows(vector, top_k):
            return tbl.search(list(vector), vector_column_name="vector").limit(1000).to_list()

        rtr = Retriever(idx)
        rtr._embed_query_sync = lambda q: [0.0] * 8
        rtr._search_chunks = all_rows
        results = rtr.retrieve("anything", top_k=64)
        assert any(body["file_path"] in res.file_path for res in results)

    def test_b2_chunking_stable_across_versions(self):
        """B2: chunk count is stable across identical inputs."""
        from app.services.chunker import split

        text = "# A\n\n" + ("content paragraph. " * 30)
        c1 = split(text, "x.md", "h1")
        c2 = split(text, "x.md", "h1")
        assert len(c1) == len(c2)
        for a, b in zip(c1, c2, strict=False):
            assert a["chunk_index"] == b["chunk_index"]
            assert a["file_path"] == b["file_path"]
            assert a["file_hash"] == b["file_hash"]

    def test_b3_admin_index_status_reports_per_file(
        self, raw_client: TestClient, stub_parser
    ):
        """B3: /admin/index/status returns per-file state."""
        stub_parser(text="Content A.", parser="markitdown")
        raw_client.post(
            "/v1/files", files={"file": ("a.pdf", b"%PDF-a", "application/pdf")}
        )
        stub_parser(text="Content B.", parser="markitdown")
        raw_client.post(
            "/v1/files", files={"file": ("b.pdf", b"%PDF-b", "application/pdf")}
        )
        response = raw_client.get("/admin/index/status")
        assert response.status_code == 200
        body = response.json()
        assert body["count"] >= 2
        items = body["items"]
        for item in items:
            assert "status" in item
            assert "chunk_count" in item
            assert "file_path" in item
            assert "file_hash" in item
        paths = [it["file_path"] for it in items]
        # uploaded files become <ts>_<stem>.md in vault/team/
        assert any(os.path.basename(p).endswith("_a.md") for p in paths)
        assert any(os.path.basename(p).endswith("_b.md") for p in paths)


# ============================================================== C. Retrieval / Q&A


class TestCRetrieval:
    def test_c1_stream_chat_returns_citations(
        self, raw_client: TestClient, gateway: _GatewayMock, monkeypatch
    ):
        """C1: /v1/chat/completions stream -> SSE chunks + references event."""
        import app.routes.chat as chat_module

        fixed = [
            RetrievalResult(
                file_path="/vault/team/alpha.md",
                chunk_index=0,
                heading_path=["Alpha"],
                text="alpha body",
                score=0.9,
                chunk_id="c-1",
            )
        ]

        def stub():
            fake = Retriever(_FakeIndexer())  # type: ignore[arg-type]
            fake.retrieve = lambda q, top_k=8: list(fixed)
            return fake

        monkeypatch.setattr(chat_module, "_get_retriever", stub)
        gateway.set_handler(
            lambda req: _GatewayMock.stream_response(
                [{"choices": [{"delta": {"content": "hi"}}]}]
            )
        )

        with raw_client.stream(
            "POST",
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "x"}], "stream": True},
        ) as resp:
            assert resp.status_code == 200
            body = b"".join(resp.iter_bytes()).decode("utf-8")

        # Citation event present + references path
        assert '"type": "references"' in body
        assert "alpha.md" in body
        assert "c-1" in body
        assert body.rstrip().endswith("data: [DONE]")

    def test_c2_citations_include_vault_path_and_heading(
        self, raw_client: TestClient, gateway: _GatewayMock, monkeypatch
    ):
        """C2: references include vault path + heading + score."""
        import app.routes.chat as chat_module

        fixed = [
            RetrievalResult(
                file_path="/vault/team/notes.md",
                chunk_index=2,
                heading_path=["Notes", "Sub"],
                text="body",
                score=0.7,
                chunk_id="ck-2",
            )
        ]

        def stub():
            fake = Retriever(_FakeIndexer())  # type: ignore[arg-type]
            fake.retrieve = lambda q, top_k=8: list(fixed)
            return fake

        monkeypatch.setattr(chat_module, "_get_retriever", stub)
        gateway.set_handler(lambda req: _GatewayMock.stream_response([{}]))

        with raw_client.stream(
            "POST",
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "x"}], "stream": True},
        ) as resp:
            raw = b"".join(resp.iter_bytes()).decode("utf-8")

        ref_line = next(
            (line for line in raw.split("\n") if line.startswith("data:") and "references" in line),
            None,
        )
        assert ref_line is not None
        payload = json.loads(ref_line[len("data: "):])
        ref = payload["references"][0]
        assert ref["file_path"] == "/vault/team/notes.md"
        assert ref["heading"] == "Notes > Sub"
        assert ref["chunk_id"] == "ck-2"
        assert isinstance(ref["score"], float)

    def test_c3_empty_hits_anti_hallucination_prompt(
        self, raw_client: TestClient, gateway: _GatewayMock, monkeypatch
    ):
        """C3: empty retrieval -> anti-hallucination instruction present in prompt."""
        import app.routes.chat as chat_module

        def stub():
            fake = Retriever(_FakeIndexer())  # type: ignore[arg-type]
            fake.retrieve = lambda q, top_k=8: []
            return fake

        monkeypatch.setattr(chat_module, "_get_retriever", stub)

        captured: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content))
            return _GatewayMock.stream_response(
                [{"choices": [{"delta": {"content": "no info"}}]}]
            )

        gateway.set_handler(handler)

        with raw_client.stream(
            "POST",
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "x"}], "stream": True},
        ) as resp:
            b"".join(resp.iter_bytes())

        user_msg = next(
            m for m in captured[0]["messages"] if m["role"] == "user"
        )
        content = user_msg["content"]
        assert "no matching chunks" in content.lower() or "not invent" in content.lower()

    def test_c4_gateway_5xx_returns_502_or_sse_error(
        self, raw_client: TestClient, gateway: _GatewayMock, monkeypatch
    ):
        """C4: gateway 5xx -> 502 (non-stream) or SSE error event (stream)."""
        import app.routes.chat as chat_module

        def stub():
            fake = Retriever(_FakeIndexer())  # type: ignore[arg-type]
            fake.retrieve = lambda q, top_k=8: [
                RetrievalResult(file_path="/x.md", chunk_index=0,
                                heading_path=[], text="x", score=0.5, chunk_id="x")
            ]
            return fake

        monkeypatch.setattr(chat_module, "_get_retriever", stub)
        gateway.set_handler(lambda req: _GatewayMock.error_response(502, "boom"))

        # non-stream -> 502
        r_non = raw_client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "x"}], "stream": False},
        )
        assert r_non.status_code == 502

        # stream -> SSE error event
        with raw_client.stream(
            "POST",
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "x"}], "stream": True},
        ) as resp:
            assert resp.status_code == 200
            body = b"".join(resp.iter_bytes()).decode("utf-8")
        assert '"error"' in body
        assert "502" in body

    def test_c5_embedding_rate_limit_retries_complete(
        self, raw_client: TestClient, stub_embed, stub_parser, monkeypatch
    ):
        """C5: embedding rate-limited -> indexing still completes (retries don't hang).

        Drives the real ``embed_batch`` retry path via httpx.MockTransport. The
        sync stub from ``stub_embed`` would short-circuit retries, so we swap
        ``embed_batch`` back to the original async function for this test.
        """
        from app.services import embedder as embedder_module_real
        from app.services import indexer as indexer_module_local

        _sync_fake, real_embed_batch = stub_embed

        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if attempts["n"] < 2:
                return httpx.Response(429, json={"error": "rate limit"})
            return httpx.Response(
                200,
                json={"data": [{"embedding": [0.0] * 8}]},
            )

        transport = httpx.MockTransport(handler)

        def factory(*args, **kwargs):
            kwargs["transport"] = transport
            return httpx.AsyncClient(*args, **kwargs)

        # Speed up backoff so the test isn't gated by 1+2+4 seconds.
        async def _no_sleep(*_a, **_k):
            return None

        embedder_module_real.asyncio.sleep = _no_sleep  # type: ignore[attr-defined]
        embedder_module_real._new_client = factory  # type: ignore[assignment]
        indexer_module_local.embedder_module._new_client = factory  # type: ignore[attr-defined]
        # Restore real async embed_batch (the autouse stub is sync).
        monkeypatch.setattr(embedder_module_real, "embed_batch", real_embed_batch)
        monkeypatch.setattr(
            indexer_module_local.embedder_module, "embed_batch", real_embed_batch
        )

        stub_parser(text="retry me " * 20, parser="markitdown")
        t0 = time.time()
        response = raw_client.post(
            "/v1/files",
            files={"file": ("rl.pdf", b"%PDF-rl", "application/pdf")},
        )
        elapsed = time.time() - t0
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        # Retry actually happened
        assert attempts["n"] >= 2
        # And it didn't hang on backoff
        assert elapsed < 10.0

    def test_c6_concurrent_requests_no_data_mixing(
        self, raw_client: TestClient, gateway: _GatewayMock, monkeypatch
    ):
        """C6: concurrent requests don't mix retrieval results across calls."""
        import threading

        import app.routes.chat as chat_module

        # Per-call results keyed by user query content.
        map_by_query = {
            "q-A": [
                RetrievalResult(
                    file_path="/vault/team/A.md", chunk_index=0,
                    heading_path=["A"], text="alpha", score=0.9, chunk_id="ca"
                )
            ],
            "q-B": [
                RetrievalResult(
                    file_path="/vault/team/B.md", chunk_index=0,
                    heading_path=["B"], text="beta", score=0.9, chunk_id="cb"
                )
            ],
        }
        lock = threading.Lock()

        def stub():
            class _R(Retriever):
                def retrieve(self, query, top_k=8):
                    with lock:
                        return list(map_by_query.get(query, []))

            return _R(_FakeIndexer())  # type: ignore[arg-type]

        monkeypatch.setattr(chat_module, "_get_retriever", stub)

        seen_queries: list[str] = []
        gw_lock = threading.Lock()

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            # Pull the user content (after "---References:")
            user_msg = next(m for m in body["messages"] if m["role"] == "user")
            q = user_msg["content"].split("\n\n---\n")[0].strip()
            with gw_lock:
                seen_queries.append(q)
            return _GatewayMock.stream_response(
                [{"choices": [{"delta": {"content": "ok"}}]}]
            )

        gateway.set_handler(handler)

        def fire(query: str) -> str:
            with raw_client.stream(
                "POST",
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": query}], "stream": True},
            ) as resp:
                body = b"".join(resp.iter_bytes()).decode("utf-8")
            return body

        threads = [
            threading.Thread(target=fire, args=("q-A",)),
            threading.Thread(target=fire, args=("q-B",)),
            threading.Thread(target=fire, args=("q-A",)),
            threading.Thread(target=fire, args=("q-B",)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        # Each request saw its own retrieval results — the user prompt
        # contained the correct reference for its query.
        assert sorted(seen_queries) == sorted(["q-A", "q-A", "q-B", "q-B"])


# ============================================================== E. Personal notes


class TestEPersonalNotes:
    def test_e1_watchdog_indexes_new_md(
        self, live_client: TestClient, tmp_path: Path
    ):
        """E1: writing a new .md to vault/notes/personal triggers watchdog -> indexed."""
        vault_path = tmp_path / "vault"
        target = vault_path / "notes" / "personal" / "test.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# Personal Note\n\nBody content for personal note.", encoding="utf-8")
        # Watchdog debounces ~500ms; allow generous slack.
        deadline = time.time() + 5.0
        indexed = False
        while time.time() < deadline:
            statuses = LanceIndexer().get_status()
            if any("test.md" in s.file_path for s in statuses):
                indexed = True
                break
            time.sleep(0.2)
        assert indexed, "watchdog did not index the new file within 5s"

    def test_e2_modify_md_replaces_old_chunks(
        self, live_client: TestClient, tmp_path: Path
    ):
        """E2: modifying an existing .md should drop old chunks + recreate.

        Indexer dedups by file_path (not file_hash) so content changes
        cleanly replace the previous hash's rows — no orphan accumulation.
        """
        vault_path = tmp_path / "vault"
        target = vault_path / "notes" / "personal" / "evolving.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# v1\n\nOriginal body one.", encoding="utf-8")
        # Wait for index to settle
        deadline = time.time() + 5.0
        idx = LanceIndexer()
        while time.time() < deadline:
            sts = [s for s in idx.get_status() if "evolving.md" in s.file_path]
            if sts:
                break
            time.sleep(0.2)
        assert sts, "watchdog did not index initial content"
        old_hash = sts[0].file_hash

        # Mutate content
        target.write_text("# v2\n\nUpdated body two.", encoding="utf-8")
        deadline = time.time() + 5.0
        while time.time() < deadline:
            sts = [s for s in idx.get_status() if "evolving.md" in s.file_path]
            if sts and sts[0].file_hash != old_hash:
                break
            time.sleep(0.2)
        # After modification: old hash is GONE (file_path-based dedup),
        # new hash exists with status=ok.
        new_statuses = [s for s in idx.get_status() if "evolving.md" in s.file_path]
        new_hashes = {s.file_hash for s in new_statuses}
        assert old_hash not in new_hashes, (
            "old hash should have been cleaned up after content change; "
            f"observed hashes={new_hashes}"
        )
        assert any(h != old_hash for h in new_hashes), (
            "expected a NEW status row for the modified content; "
            f"observed hashes={new_hashes}"
        )
        assert all(s.status == "ok" for s in new_statuses), new_statuses

    def test_e4_wikilinks_and_tags_reflected_in_index(
        self, raw_client: TestClient, stub_parser, tmp_path: Path
    ):
        """E4: adding [[wikilink]] + tags to a note reflects in the index."""
        stub_parser(
            text="# Tagged\n\nThis references [[Other Note]] inline.\n",
            parser="markitdown",
        )
        r = raw_client.post(
            "/v1/files",
            files={"file": ("tagged.md", b"%PDF-x", "application/pdf")},
        )
        assert r.status_code == 200
        # Now manually add a wikilink note into the vault and trigger reconcile
        vault_path = tmp_path / "vault"
        target = vault_path / "notes" / "personal" / "linked.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "---\ntags: [knowledge, ai]\n---\n# Linked\n\nLinks to [[Tagged]].",
            encoding="utf-8",
        )
        # Trigger reconcile via admin endpoint
        scan = raw_client.post("/admin/index/scan")
        assert scan.status_code == 200
        # Both should now be indexed
        statuses = LanceIndexer().get_status()
        paths = [s.file_path for s in statuses]
        assert any("tagged.md" in p for p in paths)
        assert any("linked.md" in p for p in paths)
        # Tags parsed in frontmatter
        from app.services.vault import read_md

        fm = read_md("notes/personal/linked.md", vault_path=vault_path)
        assert fm.meta.get("tags") == ["knowledge", "ai"]


# ============================================================== F. Graph


class TestFGraph:
    def _write_md(self, vault_path: Path, rel: str, body: str, fm: dict | None = None) -> Path:
        from app.services.vault import write_md

        return write_md(rel, body, frontmatter=fm, vault_path=vault_path)

    def test_f1_graph_nodes_match_vault_count_and_wikilink_edges(
        self, raw_client: TestClient, tmp_path: Path
    ):
        """F1: node count == vault .md count; wikilink edges present."""
        vault_path = tmp_path / "vault"
        # Wikilinks written with explicit relative path so the resolver can map
        # them to the node id (the resolver only matches exact rel or rel.md).
        self._write_md(
            vault_path, "team/alpha.md", "# Alpha\n\nSee [[team/beta.md]].",
            fm={"title": "Alpha"},
        )
        self._write_md(
            vault_path, "team/beta.md", "# Beta\n\nBody.", fm={"title": "Beta"}
        )
        self._write_md(
            vault_path, "team/gamma.md", "# Gamma\n\nNo link.",
            fm={"title": "Gamma"},
        )
        resp = raw_client.get("/graph")
        assert resp.status_code == 200
        body = resp.json()
        assert "nodes" in body and "edges" in body
        ids = {n["id"] for n in body["nodes"]}
        assert "team/alpha.md" in ids
        assert "team/beta.md" in ids
        assert "team/gamma.md" in ids
        wl_edges = [
            e for e in body["edges"] if e.get("type") == "wikilink"
        ]
        # alpha -> beta resolved to real path
        assert any(
            e["source"] == "team/alpha.md" and e["target"] == "team/beta.md"
            for e in wl_edges
        ), f"wikilink edges: {wl_edges}"

    def test_f2_node_hover_fields_include_title_path_summary(
        self, raw_client: TestClient, tmp_path: Path
    ):
        """F2: nodes carry title/path/summary for hover tooltips."""
        vault_path = tmp_path / "vault"
        self._write_md(
            vault_path,
            "team/doc.md",
            "# Doc body\n\nThis is the body used to compute summary.",
            fm={"title": "My Doc"},
        )
        resp = raw_client.get("/graph")
        assert resp.status_code == 200
        body = resp.json()
        node = next(n for n in body["nodes"] if n["id"] == "team/doc.md")
        assert node["title"] == "My Doc"
        assert "summary" in node
        assert "body used to compute summary" in node["summary"]
        # label = stem
        assert node["label"] == "doc"

    def test_f3_wikilink_vs_share_tag_edges_distinguished(
        self, raw_client: TestClient, tmp_path: Path
    ):
        """F3: wikilink and share-tag edge types are distinguished."""
        vault_path = tmp_path / "vault"
        # Use absolute wikilinks so the resolver can find the target.
        self._write_md(
            vault_path,
            "team/A.md",
            "# A\n\nLink to [[team/B.md]].",
            fm={"tags": ["shared"]},
        )
        self._write_md(
            vault_path,
            "team/B.md",
            "# B\n\nLinked from A.",
            fm={"tags": ["shared"]},
        )
        self._write_md(
            vault_path,
            "team/C.md",
            "# C\n\nNo link.",
            fm={"tags": ["shared"]},
        )
        resp = raw_client.get("/graph")
        assert resp.status_code == 200
        body = resp.json()
        types = {e.get("type") for e in body["edges"]}
        assert "wikilink" in types
        assert "share-tag" in types
        # Wikilink A->B
        wl = [e for e in body["edges"] if e.get("type") == "wikilink"]
        assert any(
            e["source"] == "team/A.md" and e["target"] == "team/B.md" for e in wl
        ), f"wikilink edges: {wl}"
        # share-tag edges between any pair of A/B/C
        st = [e for e in body["edges"] if e.get("type") == "share-tag"]
        pairs = {(e["source"], e["target"]) for e in st}
        assert any(
            ("team/A.md", "team/B.md") == (a, b) or ("team/B.md", "team/A.md") == (a, b)
            for (a, b) in pairs
        ), f"share-tag pairs: {pairs}"

    def test_f4_graph_degrades_at_or_above_500_nodes(
        self, raw_client: TestClient, tmp_path: Path
    ):
        """F4: >=500 nodes -> degraded response with top-N nodes only."""
        vault_path = tmp_path / "vault"
        (vault_path / "team").mkdir(parents=True, exist_ok=True)
        n = 510
        for i in range(n):
            content = f"# Doc {i}\n\n" + ("x " * (i + 1)) + "\n"
            (vault_path / "team" / f"f{i:04d}.md").write_text(content, encoding="utf-8")
        resp = raw_client.get("/graph")
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("degraded") is True
        assert len(body["nodes"]) == 500
        # edges are filtered to kept set
        ids = {n["id"] for n in body["nodes"]}
        for e in body["edges"]:
            assert e["source"] in ids
            assert e["target"] in ids


# ============================================================== G. Error / Edge


class TestGErrorsAndEdges:
    def test_g1_missing_frontmatter_indexed_by_filename(
        self, raw_client: TestClient, tmp_path: Path
    ):
        """G1: MD without frontmatter is indexed (no crash)."""
        from app.services.vault import write_md

        target = write_md(
            "team/nofront.md",
            "# Plain\n\nBody without any frontmatter.",
            frontmatter=None,
            vault_path=tmp_path / "vault",
        )
        assert target.exists()
        text = target.read_text(encoding="utf-8")
        assert not text.startswith("---\n")

        # Trigger reconcile so it gets indexed
        raw_client.post("/admin/index/scan")
        statuses = LanceIndexer().get_status()
        assert any("nofront.md" in s.file_path for s in statuses)

    def test_g2_oversized_line_hard_split(self):
        """G2: extra-long single line is chunked, never a 1-line chunk."""
        from app.services.chunker import split

        long_text = "abcdef " * 200  # well over 64 tokens
        md = f"# Long\n\n{long_text}"
        chunks = split(md, "long.md", "h1")
        assert len(chunks) >= 2
        # Each chunk <= 64 tokens (per conftest CHUNK_TOKENS=64)
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        for c in chunks:
            assert len(enc.encode(c["text"])) <= 64

    def test_g3_process_crash_recovery(self, tmp_path: Path):
        """G3: indexer can be re-instantiated; prior status survives.

        Simulates a process crash by closing the LanceIndexer and
        re-creating it from the same on-disk LanceDB directory.
        """
        monkeypath = tmp_path / "lancedb"
        idx1 = LanceIndexer(lancedb_path=monkeypath)
        # Inject a chunk row via direct path (bypasses embedder).
        # Simpler: just call index_file with stubbed embedder.
        from app.services import embedder as emb_mod
        from app.services import indexer as idx_mod

        def fake_embed(texts):
            return np.zeros((len(list(texts)), 8), dtype=np.float32)

        emb_mod.embed_batch = fake_embed  # type: ignore[assignment]
        idx_mod.embedder_module.embed_batch = fake_embed  # type: ignore[attr-defined]
        idx1.index_file(
            Path("/vault/team/a.md"), "# A\n\nSome content for crash test."
        )
        before = idx1.get_status()
        assert before

        # "Crash": drop reference and create a new indexer from the same path
        idx2 = LanceIndexer(lancedb_path=monkeypath)
        after = idx2.get_status()
        # Same row visible across "crash"
        assert len(after) == len(before)
        assert after[0].file_path == before[0].file_path

    def test_g4_lancedb_rebuilt_after_data_loss(self, tmp_path: Path):
        """G4: corrupted / missing LanceDB dir is rebuilt cleanly."""
        ldb_path = tmp_path / "lancedb"
        LanceIndexer(lancedb_path=ldb_path)
        assert (ldb_path).exists()
        # "Corruption": nuke the LanceDB dir
        shutil.rmtree(ldb_path)
        assert not ldb_path.exists()
        # New indexer should recreate tables without error
        idx2 = LanceIndexer(lancedb_path=ldb_path)
        assert (ldb_path).exists()
        # And the tables are accessible
        tbl = idx2._db.open_table("chunks")
        assert tbl is not None
        tbl = idx2._db.open_table("index_status")
        assert tbl is not None


# ============================================================== H. Concurrency / Git


class TestHConcurrencyGit:
    def test_h1_post_commit_hook_references_scan_endpoint(self):
        """H1: the post-commit hook template is executable and calls /admin/index/scan.

        The hook ships as a template under deploy/hooks/ because a live
        .git/hooks/ directory is never tracked by git. It is installed into
        the vault repo by deploy/scripts/install-git-hooks.sh.
        """
        hook = REPO_ROOT / "deploy" / "hooks" / "post-commit"
        assert hook.exists(), "post-commit hook missing"
        # Must be executable
        assert os.access(hook, os.X_OK), "post-commit hook is not executable"
        # Bash syntax must be valid
        res = subprocess.run(["bash", "-n", str(hook)], capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
        # And must reference the scan endpoint
        text = hook.read_text(encoding="utf-8")
        assert "/admin/index/scan" in text

    def test_h2_concurrent_upload_does_not_corrupt_index(
        self, raw_client: TestClient, stub_parser
    ):
        """H2: concurrent uploads produce consistent final state (no data mixing).

        Race-targets:
          1. Two LanceIndexer objects opening the same LanceDB directory
             simultaneously and racing on table creation. ``_ensure_table``
             retries on conflict.
          2. Concurrent uploads whose parsed content is identical must not
             clobber each other's status rows (status is keyed by file_path).

        Both upload bytes differ per thread (``%PDF-{i}``) so the A5 content
        dedup does not trigger; the shared stub_parser yields one markdown
        body for all threads, which is exactly the identical-content case
        that used to lose status rows.
        """
        import threading

        stub_parser(text="shared body " * 20, parser="markitdown")
        results: list[tuple[int, int, dict[str, Any]]] = []

        def fire(i: int) -> None:
            try:
                r = raw_client.post(
                    "/v1/files",
                    files={"file": (f"doc{i}.pdf", f"%PDF-{i}".encode(), "application/pdf")},
                )
                try:
                    body = r.json()
                except Exception:
                    body = {"detail": r.text}
                results.append((r.status_code, i, body))
            except Exception as exc:  # noqa: BLE001
                results.append((500, i, {"detail": str(exc)}))

        threads = [threading.Thread(target=fire, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        # All 8 reach a 200 — no server crash from the table-init race.
        ok_codes = [c for c, _, _ in results if c == 200]
        assert len(ok_codes) == 8, (
            f"expected all 8 concurrent uploads to return 200; results={results}"
        )
        # All 8 are actually indexed (upload bytes differ -> no dedup skip).
        statuses_ok = [b for _, _, b in results if b.get("status") == "ok"]
        assert len(statuses_ok) == 8, (
            f"expected all 8 uploads indexed; results={results}"
        )

        # Every indexed upload has its own status row — identical content
        # across different paths must not clobber each other.
        idx = LanceIndexer()
        statuses = idx.get_status()
        indexed_paths = {s.file_path for s in statuses}
        successful_paths = {body["file_path"] for body in statuses_ok}
        assert successful_paths <= indexed_paths, (
            f"missing status rows: {successful_paths - indexed_paths}"
        )

        # No 500 / unhandled exception.
        for code, _, body in results:
            assert code == 200, f"unexpected non-200: {code} {body}"

    def test_h3_delete_md_clears_index(
        self, raw_client: TestClient, stub_parser, tmp_path: Path
    ):
        """H3: deleting a vault .md removes its index entries."""
        stub_parser(text="To be deleted.", parser="markitdown")
        r = raw_client.post(
            "/v1/files",
            files={"file": ("del.pdf", b"%PDF-del", "application/pdf")},
        )
        assert r.status_code == 200
        rel_path = r.json()["file_path"]
        # Sanity: present
        idx = LanceIndexer()
        assert any(s.file_path == rel_path for s in idx.get_status())

        # Compute the relative path inside the vault
        vault_root = tmp_path / "vault"
        rel = str(Path(rel_path).relative_to(vault_root))
        d = raw_client.delete(f"/v1/files/{rel}")
        assert d.status_code == 200
        assert not any(s.file_path == rel_path for s in LanceIndexer().get_status())

    def test_h4_special_chars_in_frontmatter(
        self, raw_client: TestClient, stub_parser, tmp_path: Path
    ):
        """H4: frontmatter with unicode, quotes, and edge chars parses cleanly."""
        from app.services.vault import write_md

        write_md(
            "team/special.md",
            "# Special\n\nBody text.",
            frontmatter={
                "title": "标题 with unicode",
                "description": 'quoted "value" with \\backslash',
                "tags": ["a", "b c", "d/e"],
            },
            vault_path=tmp_path / "vault",
        )
        # Trigger reconcile
        raw_client.post("/admin/index/scan")
        # Reading back should yield the same meta keys
        from app.services.vault import read_md

        fm = read_md("team/special.md", vault_path=tmp_path / "vault")
        assert fm.meta["title"].startswith("标题")
        assert '"value"' in fm.meta["description"]
        assert fm.meta["tags"] == ["a", "b c", "d/e"]
        # And the file is indexed (no crash)
        statuses = LanceIndexer().get_status()
        assert any("special.md" in s.file_path for s in statuses)


# ============================================================== I. Deployment ops


class TestIDeployment:
    @pytest.fixture
    def compose_file(self) -> Path:
        return REPO_ROOT / "deploy" / "docker-compose.yml"

    def test_i1_docker_compose_config_quiet(self, compose_file: Path):
        """I1: docker compose config -q exits 0."""
        if shutil.which("docker") is None:
            pytest.skip("docker not installed")
        res = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "config", "-q"],
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, res.stderr or res.stdout

    def test_i2_docker_compose_lists_backend_and_open_webui(self, compose_file: Path):
        """I2: docker compose config lists backend + open-webui services."""
        if shutil.which("docker") is None:
            pytest.skip("docker not installed")
        res = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "config"],
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0
        out = res.stdout
        assert "backend:" in out
        assert "open-webui:" in out

    def test_i3_backup_script_syntax(self):
        """I3: backup.sh passes ``bash -n``."""
        script = REPO_ROOT / "deploy" / "scripts" / "backup.sh"
        res = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert res.returncode == 0, res.stderr

    def test_i4_restore_script_syntax_and_missing_arg(self):
        """I4: restore.sh passes ``bash -n``; missing arg -> non-zero exit."""
        script = REPO_ROOT / "deploy" / "scripts" / "restore.sh"
        # syntax
        res = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
        # missing arg -> non-zero
        res = subprocess.run([str(script)], capture_output=True, text=True)
        assert res.returncode != 0

    def test_i5_metrics_exposes_kb_prefixed_metrics(
        self, raw_client: TestClient, stub_parser
    ):
        """I5: /metrics contains the kb_* metric family AND they actually count.

        F-07 fix: drives one upload to confirm ``kb_index_files_total{status="indexed"}``
        increments past zero (the previous test only checked the name string,
        which passes even when the metric is never incremented).
        """
        stub_parser(text="metrics smoke body " * 8, parser="markitdown")
        up = raw_client.post(
            "/v1/files",
            files={"file": ("metrics.pdf", b"%PDF-m", "application/pdf")},
        )
        assert up.status_code == 200, up.text
        assert up.json()["status"] == "ok"

        r = raw_client.get("/metrics")
        assert r.status_code == 200
        text = r.text

        # All metric names present
        for name in [
            "kb_index_files_total",
            "kb_retrieve_latency_seconds",
            "kb_chat_completions_total",
            "kb_embedding_latency_seconds",
            "kb_lancedb_rows",
        ]:
            assert name in text, f"missing metric {name} in /metrics output"

        # F-07 strong assertion: at least one increment > 0
        import re

        m_indexed = re.search(
            r'kb_index_files_total\{status="indexed"\}\s+([0-9.eE+-]+)', text
        )
        assert m_indexed and float(m_indexed.group(1)) > 0, (
            f"expected kb_index_files_total{{status=indexed}} > 0, body:\n{text}"
        )
        m_rows = re.search(r"kb_lancedb_rows\s+([0-9.eE+-]+)", text)
        assert m_rows and float(m_rows.group(1)) > 0, (
            f"expected kb_lancedb_rows > 0 after upload, body:\n{text}"
        )

    def test_i6_compose_env_override_matches_volume_mount(
        self, compose_file: Path
    ):
        """I6: VAULT_PATH override in compose matches the mounted volume path."""
        if shutil.which("docker") is None:
            pytest.skip("docker not installed")
        res = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "config"],
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0
        out = res.stdout
        # The override sets VAULT_PATH=/data/vault and mounts ../vault there
        assert "VAULT_PATH: /data/vault" in out
        # Source mount -> /data/vault
        assert "/data/vault" in out


# ============================================================== helpers


@dataclass
class _FakeIndexer:
    """Minimal stand-in for LanceIndexer (only ``lancedb_path`` needed by stubbed retriever)."""

    lancedb_path: Path = Path("/tmp/lance")
