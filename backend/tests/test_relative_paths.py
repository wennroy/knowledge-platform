"""Contract tests: every ``file_path`` is relative to the vault root.

Before this contract the index stored the *absolute* path of every indexed
document. That leaked the server layout and broke every existing index entry
as soon as the vault moved (different host, different container mount point).

The rules exercised here:

* ``index_file`` stores a vault-relative POSIX path;
* ``get_status`` (and therefore ``/admin/index/status``) returns it;
* ``delete_file`` accepts either the absolute or the relative path;
* ``/v1/files`` (upload + list) and the chat ``references`` event use it too;
* SQL string building in the indexer escapes single quotes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.routes.files as files_module
from app.config import get_settings
from app.main import app
from app.models import ParseResult
from app.services import indexer as indexer_module
from app.services.indexer import LanceIndexer
from app.services.retriever import Retriever
from app.services.sync import VaultIndexer

# ------------------------------------------------------------------ fixtures


@pytest.fixture
def stub_embedder(monkeypatch):
    """Replace embed_batch with a deterministic fake (no network)."""

    def fake_embed(texts):
        arr = np.zeros((len(list(texts)), 8), dtype=np.float32)
        for i, t in enumerate(texts):
            arr[i, 0] = float(len(t) % 7) / 7.0
        return arr

    async def fake_async(texts):
        return fake_embed(list(texts))

    monkeypatch.setattr(indexer_module.embedder_module, "embed_batch", fake_async)


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """The vault ``VAULT_PATH`` points at (see conftest.py)."""
    base = get_settings().vault_path()
    (base / "team").mkdir(parents=True, exist_ok=True)
    (base / "team" / "api-design.md").write_text(
        "# API 设计原则\n\n## 鉴权\n\n使用 Bearer token\n",
        encoding="utf-8",
    )
    return base


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def stub_parser(monkeypatch):
    """Install a fake parser for the upload endpoint."""

    def fake_parse(staged_path):
        return ParseResult(
            markdown="# Uploaded\n\nSome parsed body content.",
            parser="markitdown",
            ocr_used=False,
        )

    monkeypatch.setattr(files_module, "parse", fake_parse)


@pytest.fixture
def gateway(monkeypatch):
    """Mock the upstream gateway with a plain SSE delta stream."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            content=b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
            b"data: [DONE]\n\n",
            headers={"Content-Type": "text/event-stream"},
        )
    )
    real_async_client = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def _all_chunks(self: Retriever, vector, top_k):  # type: ignore[no-untyped-def]
    """Return every chunk row — no real vector search needed."""
    table = self._open_chunks_table()
    return (
        table.search(list(vector), vector_column_name="vector").limit(100).to_list()
    )


# ------------------------------------------------------------------ indexer


def test_index_file_stores_relative_path(stub_embedder, vault: Path):
    idx = LanceIndexer()
    target = vault / "team" / "api-design.md"
    status = idx.index_file(target, "# API\n\nbody")
    assert status.file_path == "team/api-design.md"

    rows = idx._chunks.search().to_list()  # type: ignore[attr-defined]
    assert rows
    assert all(r["file_path"] == "team/api-design.md" for r in rows)


def test_get_status_returns_relative_path(stub_embedder, vault: Path):
    idx = LanceIndexer()
    idx.index_file(vault / "team" / "api-design.md", "# API\n\nbody")
    statuses = idx.get_status()
    assert [s.file_path for s in statuses] == ["team/api-design.md"]
    assert not Path(statuses[0].file_path).is_absolute()


def test_delete_file_accepts_absolute_path(stub_embedder, vault: Path):
    """An absolute path must still remove the row stored under the relative one."""
    idx = LanceIndexer()
    target = vault / "team" / "api-design.md"
    idx.index_file(target, "# API\n\nbody")
    assert any(s.file_path == "team/api-design.md" for s in idx.get_status())

    idx.delete_file(target)  # absolute
    assert not any(s.file_path == "team/api-design.md" for s in idx.get_status())
    assert idx._chunks.search().to_list() == []  # type: ignore[attr-defined]


def test_delete_file_accepts_relative_path(stub_embedder, vault: Path):
    idx = LanceIndexer()
    idx.index_file(vault / "team" / "api-design.md", "# API\n\nbody")
    idx.delete_file("team/api-design.md")  # relative
    assert idx.get_status() == []


def test_startup_reconcile_yields_relative_paths(stub_embedder, vault: Path):
    v = VaultIndexer()
    v.startup_reconcile(vault)
    statuses = LanceIndexer().get_status()
    assert statuses
    for s in statuses:
        assert not Path(s.file_path).is_absolute()
        assert s.file_path.startswith("team/")


def test_reconcile_purges_legacy_absolute_rows(stub_embedder, vault: Path):
    """Rows written before the contract (absolute paths) are removed."""
    from app.models import utcnow_iso

    idx = LanceIndexer()
    legacy = str(vault / "team" / "api-design.md")
    idx._status.add(  # type: ignore[attr-defined]
        [
            {
                "file_path": legacy,
                "file_hash": "deadbeef",
                "chunk_count": 0,
                "status": "ok",
                "updated_at": utcnow_iso(),
                "error": "",
            }
        ]
    )
    idx._chunks.add(  # type: ignore[attr-defined]
        [
            {
                "id": "legacy-1",
                "file_path": legacy,
                "file_hash": "deadbeef",
                "chunk_index": 0,
                "text": "legacy row",
                "heading_path": "[]",
                "start_offset": 0,
                "end_offset": 0,
                "ingested_at": utcnow_iso(),
                "vector": [0.0] * 8,
            }
        ]
    )

    VaultIndexer().startup_reconcile(vault)

    fresh = LanceIndexer()
    paths = [s.file_path for s in fresh.get_status()]
    assert paths == ["team/api-design.md"]
    chunk_paths = [r["file_path"] for r in fresh._chunks.search().to_list()]  # type: ignore[attr-defined]
    assert legacy not in chunk_paths


def test_rebuild_index_clears_legacy_rows(stub_embedder, vault: Path):
    """``rebuild_index`` wipes the tables first, so nothing survives."""
    from app.models import utcnow_iso

    idx = LanceIndexer()
    idx._status.add(  # type: ignore[attr-defined]
        [
            {
                "file_path": str(vault / "team" / "ghost.md"),
                "file_hash": "deadbeef",
                "chunk_count": 0,
                "status": "ok",
                "updated_at": utcnow_iso(),
                "error": "",
            }
        ]
    )

    result = VaultIndexer().rebuild_index(vault)
    assert result["indexed"] >= 1
    paths = [s.file_path for s in LanceIndexer().get_status()]
    assert paths == ["team/api-design.md"]


# ------------------------------------------------------------------ SQL escaping


def test_delete_by_hash_escapes_single_quotes(stub_embedder):
    """A quote in a hash must not break the generated WHERE clause."""
    idx = LanceIndexer()
    table = idx._chunks
    row = {
        "id": "q1",
        "file_path": "team/quote.md",
        "file_hash": "it's-a-hash",
        "chunk_index": 0,
        "text": "body",
        "heading_path": "[]",
        "start_offset": 0,
        "end_offset": 0,
        "ingested_at": "2026-01-01T00:00:00+00:00",
        "vector": [0.0] * 8,
    }
    table.add([row])
    assert len(table.search().to_list()) == 1

    deleted = idx._delete_by_hash(table, "it's-a-hash")
    assert deleted == 1
    assert table.search().to_list() == []


def test_delete_by_file_path_escapes_single_quotes(stub_embedder):
    idx = LanceIndexer()
    table = idx._chunks
    row = {
        "id": "q2",
        "file_path": "team/it's.md",
        "file_hash": "h",
        "chunk_index": 0,
        "text": "body",
        "heading_path": "[]",
        "start_offset": 0,
        "end_offset": 0,
        "ingested_at": "2026-01-01T00:00:00+00:00",
        "vector": [0.0] * 8,
    }
    table.add([row])
    deleted = idx._delete_by_file_path(table, "team/it's.md")
    assert deleted == 1
    assert table.search().to_list() == []


def test_index_and_delete_file_with_quote_in_name(stub_embedder, vault: Path):
    """A document whose name contains a quote round-trips through the index."""
    target = vault / "team" / "it's.md"
    target.write_text("# Quote\n\nbody\n", encoding="utf-8")

    idx = LanceIndexer()
    status = idx.index_file(target, "# Quote\n\nbody\n")
    assert status.file_path == "team/it's.md"

    idx.delete_file(target)
    assert not any(s.file_path == "team/it's.md" for s in idx.get_status())


# ------------------------------------------------------------------ HTTP API


def test_upload_returns_relative_path(client: TestClient, stub_embedder, stub_parser):
    response = client.post(
        "/v1/files", files={"file": ("hello.pdf", b"%PDF-x", "application/pdf")}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert not Path(body["file_path"]).is_absolute()
    assert body["file_path"].startswith("team/")
    assert body["file_path"].endswith("_hello.md")


def test_list_files_returns_relative_paths(client: TestClient, vault: Path):
    response = client.get("/v1/files")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] >= 1
    for item in body["files"]:
        assert not Path(item["file_path"]).is_absolute()
    assert any(item["file_path"] == "team/api-design.md" for item in body["files"])


def test_admin_index_status_returns_relative_paths(
    client: TestClient, stub_embedder, vault: Path
):
    VaultIndexer().startup_reconcile(vault)
    response = client.get("/admin/index/status")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] >= 1
    for item in body["items"]:
        assert not Path(item["file_path"]).is_absolute()
    assert any(item["file_path"] == "team/api-design.md" for item in body["items"])


def test_admin_rebuild_endpoint(client: TestClient, stub_embedder, vault: Path):
    response = client.post("/admin/index/rebuild")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["indexed"] >= 1
    items = client.get("/admin/index/status").json()["items"]
    assert all(not Path(i["file_path"]).is_absolute() for i in items)


def test_chat_references_use_relative_paths(
    client: TestClient, stub_embedder, gateway, vault: Path, monkeypatch
):
    VaultIndexer().startup_reconcile(vault)
    monkeypatch.setattr(Retriever, "_search_chunks", _all_chunks)

    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "q"}], "stream": True},
    ) as response:
        assert response.status_code == 200
        raw = b"".join(response.iter_bytes()).decode("utf-8")

    ref_lines = [
        line[len("data: ") :]
        for line in raw.split("\n")
        if line.startswith("data: ") and "references" in line
    ]
    assert ref_lines
    payload = json.loads(ref_lines[0])
    assert payload["type"] == "references"
    assert payload["references"]
    for ref in payload["references"]:
        assert not Path(ref["file_path"]).is_absolute()
        assert ref["file_path"].startswith("team/")
