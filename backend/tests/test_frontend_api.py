"""Tests for the endpoints the unified frontend depends on.

Covers:

* ``GET /v1/files/{path}``  — read one markdown document (body + frontmatter)
* ``GET /v1/tree``          — nested document tree with tags / size / mtime
* ``GET /v1/search?q=``     — grep-style full-text search
* the ``references`` SSE event now carrying ``start_offset`` / ``end_offset`` /
  the quoted ``text``
* the SPA history fallback serving ``index.html`` for unknown paths without
  swallowing the API routes

No external services are used: the gateway is mocked with
``httpx.MockTransport`` and the vault is a tmp directory.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main_module
import app.routes.chat as chat_module
from app.config import get_settings
from app.main import app
from app.services.retriever import RetrievalResult, Retriever

# ------------------------------------------------------------------ fixtures


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """Populate the vault that ``VAULT_PATH`` points at (see conftest.py)."""
    base = tmp_path / "vault"
    (base / "team").mkdir(parents=True)
    (base / "notes").mkdir(parents=True)
    (base / "team" / "api-design.md").write_text(
        "---\n"
        "tags: [api, design]\n"
        "parser: markitdown\n"
        "---\n"
        "\n"
        "# API 设计原则\n"
        "\n"
        "## 鉴权\n"
        "使用 Bearer token\n"
        "\n"
        "## 限流\n"
        "令牌桶算法\n",
        encoding="utf-8",
    )
    (base / "team" / "auth.md").write_text(
        "# Auth\n\nNo tags here.\n",
        encoding="utf-8",
    )
    (base / "notes" / "todo.md").write_text(
        "---\ntags: [misc]\n---\n\n# Todo\n\n- [ ] 写测试\n",
        encoding="utf-8",
    )
    return base


@pytest.fixture
def spa(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the SPA fallback at a throwaway build directory."""
    root = tmp_path / "spa-build"
    root.mkdir()
    (root / "index.html").write_text(
        "<!doctype html><html><body>SPA INDEX</body></html>",
        encoding="utf-8",
    )
    monkeypatch.setattr(main_module, "_APP_DIR", root)
    return root


# ------------------------------------------------------------------ files: read
def test_get_file_returns_body_and_frontmatter(client: TestClient, vault: Path):
    response = client.get("/v1/files/team/api-design.md")
    assert response.status_code == 200
    body = response.json()
    assert body["file_path"] == "team/api-design.md"
    # Frontmatter is stripped from the content.
    assert body["content"].startswith("# API 设计原则")
    assert "tags:" not in body["content"]
    assert "---" not in body["content"]
    # ... but is returned separately.
    assert body["frontmatter"]["tags"] == ["api", "design"]
    assert body["frontmatter"]["parser"] == "markitdown"
    assert body["size_bytes"] > 0
    assert body["updated_at"]


def test_get_file_missing_returns_404(client: TestClient, vault: Path):
    response = client.get("/v1/files/team/does-not-exist.md")
    assert response.status_code == 404


def test_get_file_rejects_path_traversal(client: TestClient, vault: Path):
    """``..`` segments must not escape the vault root."""
    response = client.get("/v1/files/%2e%2e%2f%2e%2e%2fetc%2fpasswd")
    assert response.status_code == 400
    assert "escapes vault" in response.json()["detail"]


def test_get_file_rejects_absolute_path_escape(client: TestClient, vault: Path):
    response = client.get("/v1/files/%2Fetc%2Fpasswd")
    assert response.status_code in (400, 404)


# ------------------------------------------------------------------ tree
def test_tree_returns_nested_structure(client: TestClient, vault: Path):
    response = client.get("/v1/tree")
    assert response.status_code == 200
    tree = response.json()["tree"]

    # Directories first, sorted by name.
    assert [node["name"] for node in tree] == ["notes", "team"]

    team = next(node for node in tree if node["name"] == "team")
    assert team["type"] == "dir"
    assert team["path"] == "team"
    assert [child["name"] for child in team["children"]] == [
        "api-design.md",
        "auth.md",
    ]

    api = next(child for child in team["children"] if child["name"] == "api-design.md")
    assert api["type"] == "file"
    assert api["path"] == "team/api-design.md"
    assert api["tags"] == ["api", "design"]
    assert api["size_bytes"] > 0
    assert api["updated_at"]

    auth = next(child for child in team["children"] if child["name"] == "auth.md")
    assert auth["tags"] == []


def test_tree_places_directories_before_files(client: TestClient, vault: Path):
    (vault / "zzz-dir").mkdir()
    (vault / "zzz-dir" / "inner.md").write_text("# inner\n", encoding="utf-8")
    (vault / "aaa-file.md").write_text("# aaa\n", encoding="utf-8")

    tree = client.get("/v1/tree").json()["tree"]
    dirs = [i for i, node in enumerate(tree) if node["type"] == "dir"]
    files = [i for i, node in enumerate(tree) if node["type"] == "file"]
    assert dirs and files
    assert max(dirs) < min(files)
    # Each group is sorted by name.
    dir_names = [tree[i]["name"] for i in dirs]
    file_names = [tree[i]["name"] for i in files]
    assert dir_names == sorted(dir_names)
    assert file_names == sorted(file_names)


def test_tree_empty_vault_returns_empty_list(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    empty = tmp_path / "empty-vault"
    empty.mkdir()
    monkeypatch.setenv("VAULT_PATH", str(empty))
    get_settings.cache_clear()

    response = client.get("/v1/tree")
    assert response.status_code == 200
    assert response.json() == {"tree": []}


def test_tree_skips_staging_directory(client: TestClient, vault: Path):
    staging = vault / ".staging"
    staging.mkdir()
    (staging / "half-written.md").write_text("# nope\n", encoding="utf-8")

    tree = client.get("/v1/tree").json()["tree"]
    assert all(node["name"] != ".staging" for node in tree)


# ------------------------------------------------------------------ search
def test_search_returns_matches_with_line_numbers(client: TestClient, vault: Path):
    response = client.get("/v1/search", params={"q": "bearer"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "bearer"
    assert len(payload["results"]) == 1

    hit = payload["results"][0]
    assert hit["file_path"] == "team/api-design.md"
    assert hit["title"] == "API 设计原则"
    assert len(hit["matches"]) == 1
    match = hit["matches"][0]
    # Line numbers are 1-based and relative to the body (frontmatter stripped).
    # body = "# API 设计原则", "", "## 鉴权", "使用 Bearer token", ...
    assert match["line"] == 4
    assert match["text"] == "使用 Bearer token"


def test_search_is_case_insensitive(client: TestClient, vault: Path):
    lower = client.get("/v1/search", params={"q": "bearer"}).json()
    upper = client.get("/v1/search", params={"q": "BEARER"}).json()
    assert len(lower["results"]) == len(upper["results"]) == 1


def test_search_without_match_returns_empty_results(client: TestClient, vault: Path):
    response = client.get("/v1/search", params={"q": "zzz-not-in-vault"})
    assert response.status_code == 200
    assert response.json() == {"query": "zzz-not-in-vault", "results": []}


def test_search_with_empty_query_returns_empty_results(client: TestClient, vault: Path):
    response = client.get("/v1/search", params={"q": ""})
    assert response.status_code == 200
    assert response.json() == {"query": "", "results": []}


def test_search_caps_matches_per_file(client: TestClient, vault: Path):
    (vault / "team" / "many.md").write_text(
        "\n".join(f"line {i} needle" for i in range(1, 11)) + "\n",
        encoding="utf-8",
    )
    payload = client.get("/v1/search", params={"q": "needle"}).json()
    hit = next(r for r in payload["results"] if r["file_path"] == "team/many.md")
    assert len(hit["matches"]) == 5
    assert [m["line"] for m in hit["matches"]] == [1, 2, 3, 4, 5]


def test_search_truncates_long_lines(client: TestClient, vault: Path):
    (vault / "team" / "long.md").write_text(
        "# long\n\n" + ("x" * 500) + " needle\n",
        encoding="utf-8",
    )
    payload = client.get("/v1/search", params={"q": "needle"}).json()
    hit = next(r for r in payload["results"] if r["file_path"] == "team/long.md")
    assert len(hit["matches"][0]["text"]) == 200


# ------------------------------------------------------------------ references
@dataclass
class _FakeIndexer:
    lancedb_path: Path


_REFERENCES = [
    RetrievalResult(
        file_path="team/api-design.md",
        chunk_index=0,
        heading_path=["API 设计原则", "鉴权"],
        text="使用 Bearer token 进行鉴权",
        score=0.9,
        chunk_id="chunk-1",
        start_offset=120,
        end_offset=180,
    ),
]


class _GatewayMock:
    """Captures gateway requests and returns a scripted SSE response."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch):
        self.requests: list[httpx.Request] = []
        self._transport = httpx.MockTransport(self._handle)
        real_async_client = httpx.AsyncClient

        def factory(*args: Any, **kwargs: Any):
            kwargs["transport"] = self._transport
            return real_async_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = (
            b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n' b"data: [DONE]\n\n"
        )
        return httpx.Response(
            200, content=body, headers={"Content-Type": "text/event-stream"}
        )


@pytest.fixture
def gateway(monkeypatch: pytest.MonkeyPatch) -> _GatewayMock:
    return _GatewayMock(monkeypatch)


@pytest.fixture
def stub_retriever(monkeypatch: pytest.MonkeyPatch):
    fake = Retriever(_FakeIndexer(lancedb_path=Path("/tmp/lance")))  # type: ignore[arg-type]
    fake.retrieve = lambda query, top_k=8: list(_REFERENCES)  # type: ignore[assignment]
    monkeypatch.setattr(chat_module, "_get_retriever", lambda: fake)
    return _REFERENCES


def test_references_payload_includes_offsets_and_text():
    payload = Retriever.references_payload(_REFERENCES)
    assert len(payload) == 1
    ref = payload[0]
    assert ref["file_path"] == "team/api-design.md"
    assert ref["heading"] == "API 设计原则 > 鉴权"
    assert ref["chunk_id"] == "chunk-1"
    assert ref["start_offset"] == 120
    assert ref["end_offset"] == 180
    assert ref["text"] == "使用 Bearer token 进行鉴权"


def test_coerce_row_reads_offsets_from_index_row():
    row = {
        "id": "chunk-9",
        "file_path": "team/x.md",
        "chunk_index": 2,
        "text": "body",
        "heading_path": ["X"],
        "start_offset": 42,
        "end_offset": 99,
        "_distance": 0.5,
    }
    result = Retriever._coerce_row(row)
    assert result.start_offset == 42
    assert result.end_offset == 99


def test_stream_references_event_carries_offsets_and_text(
    client: TestClient, gateway: _GatewayMock, stub_retriever
):
    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "q"}], "stream": True},
    ) as response:
        raw = b"".join(response.iter_bytes()).decode("utf-8")

    ref_line = next(
        (
            line
            for line in raw.split("\n")
            if line.startswith("data:") and "references" in line
        ),
        None,
    )
    assert ref_line is not None
    payload = json.loads(ref_line[len("data: ") :])
    assert payload["type"] == "references"
    ref = payload["references"][0]
    assert ref["start_offset"] == 120
    assert ref["end_offset"] == 180
    assert ref["text"] == "使用 Bearer token 进行鉴权"


# ------------------------------------------------------------------ SPA fallback
def test_spa_fallback_serves_index_for_unknown_path(
    client: TestClient, spa: Path
):
    response = client.get("/some/deep/unknown/path")
    assert response.status_code == 200
    assert "SPA INDEX" in response.text


def test_spa_fallback_does_not_swallow_api_routes(
    client: TestClient, vault: Path, spa: Path
):
    files = client.get("/v1/files")
    assert files.status_code == 200
    assert "files" in files.json()

    tree = client.get("/v1/tree")
    assert tree.status_code == 200
    assert "tree" in tree.json()

    search = client.get("/v1/search", params={"q": "bearer"})
    assert search.status_code == 200
    assert "results" in search.json()

    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json() == {"ok": True}


def test_spa_fallback_returns_404_when_not_built(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(main_module, "_APP_DIR", tmp_path / "missing-build")
    response = client.get("/another/unknown/path")
    assert response.status_code == 404


def test_built_frontend_is_served_under_app(client: TestClient):
    """The real vite build (backend/app/static/app) is mounted at /app."""
    index = main_module._APP_DIR / "index.html"
    if not index.exists():
        pytest.skip("frontend not built (npm run build)")

    root = client.get("/app/")
    assert root.status_code == 200
    assert '<div id="root">' in root.text

    # History-mode deep link falls back to index.html.
    deep = client.get("/app/graph")
    assert deep.status_code == 200
    assert '<div id="root">' in deep.text
