"""End-to-end tests for the upload path: dedup, short files, staging.

These cover bugs that the earlier mock-heavy suite did not catch:

* The upload dedup compared the sha256 of the *parsed markdown* against the
  sha256 of the *uploaded bytes* — two different values, so the check never
  fired and every duplicate upload created a second document.
* ``save_staging`` wrote a bare ``<digest>`` file without the extension, so
  MarkItDown could not sniff the type and short documents failed to parse.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(monkeypatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setenv("LANCEDB_PATH", str(tmp_path / "lancedb"))

    from app.config import get_settings

    get_settings.cache_clear()
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def _upload(client: TestClient, name: str, body: bytes, mime: str = "text/markdown"):
    return client.post("/v1/files", files={"file": (name, body, mime)})


def test_upload_dedup_skips_identical_bytes(client: TestClient, monkeypatch):
    """The same bytes uploaded twice must not create two documents."""
    from app.services import indexer as indexer_module

    async def fake_embed(texts):
        import numpy as np

        return np.zeros((len(texts), 8), dtype=np.float32)

    monkeypatch.setattr(indexer_module.embedder_module, "embed_batch", fake_embed)

    payload = b"# Same file\n\nidentical content\n"
    first = _upload(client, "same.md", payload)
    assert first.status_code == 200, first.text
    assert first.json()["status"] in ("ok", "indexed"), first.json()

    second = _upload(client, "same.md", payload)
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["status"] == "skipped", f"duplicate was not detected: {body}"
    assert "duplicate of" in (body.get("error") or "")

    # Only one document exists.
    listed = client.get("/v1/files").json()
    assert listed["count"] == 1, listed


def test_dedup_key_is_the_upload_digest_not_the_markdown_hash(
    client: TestClient, monkeypatch
):
    """The dedup key must be the sha256 of the uploaded bytes.

    Two *different* files that happen to parse to the same markdown must not
    be treated as duplicates, and the same bytes must be — regardless of the
    filename they were uploaded under.
    """
    from app.services import indexer as indexer_module

    async def fake_embed(texts):
        import numpy as np

        return np.zeros((len(texts), 8), dtype=np.float32)

    monkeypatch.setattr(indexer_module.embedder_module, "embed_batch", fake_embed)

    payload = b"# Same file\n\nidentical content\n"
    first = _upload(client, "one.md", payload)
    assert first.json()["status"] in ("ok", "indexed")

    # Same bytes, different filename -> still a duplicate.
    second = _upload(client, "renamed.md", payload)
    assert second.json()["status"] == "skipped", second.json()

    # The recorded source_hash must be the digest of the uploaded bytes.
    status = client.get("/admin/index/status").json()
    items = status.get("items", [])
    expected = hashlib.sha256(payload).hexdigest()
    assert any(i.get("source_hash") == expected for i in items), items


def test_short_markdown_file_parses(client: TestClient, monkeypatch):
    """A short .md must survive the parse stage.

    Regression: the staged file had no extension, MarkItDown produced
    almost no output, the Docling fallback rejected it, and the upload
    came back as ``failed``.
    """
    from app.services import indexer as indexer_module

    async def fake_embed(texts):
        import numpy as np

        return np.zeros((len(texts), 8), dtype=np.float32)

    monkeypatch.setattr(indexer_module.embedder_module, "embed_batch", fake_embed)

    # 60 bytes — well under the 200-char fallback threshold.
    short = b"# Hi\n\nshort note\n"
    response = _upload(client, "short.md", short)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] != "failed", f"short file failed to parse: {body}"
    assert body["parser"] == "markitdown", body


def test_staging_is_cleaned_after_successful_index(client: TestClient, monkeypatch):
    """The staging area must not accumulate a copy of every upload.

    Regression risk: the staged file is a full copy of the uploaded bytes.
    Leaving it behind duplicates the whole vault on disk.
    """
    from app.services import indexer as indexer_module

    async def fake_embed(texts):
        import numpy as np

        return np.zeros((len(texts), 8), dtype=np.float32)

    monkeypatch.setattr(indexer_module.embedder_module, "embed_batch", fake_embed)

    payload = b"# Ext check\n\nbody\n"
    response = _upload(client, "ext.md", payload)
    assert response.json()["status"] in ("ok", "indexed"), response.json()

    vault = Path(os.environ["VAULT_PATH"])
    staged = [p for p in (vault / ".staging").glob("*") if p.suffix != ".json"]
    assert not staged, f"staging was not cleaned: {[p.name for p in staged]}"


def test_staging_is_kept_when_parsing_fails(client: TestClient, monkeypatch):
    """A failed parse keeps the staged file so it can be diagnosed."""
    from app.services import indexer as indexer_module

    async def fake_embed(texts):
        import numpy as np

        return np.zeros((len(texts), 8), dtype=np.float32)

    monkeypatch.setattr(indexer_module.embedder_module, "embed_batch", fake_embed)

    # Force the parser to fail.
    from app.routes import files as files_module

    def boom(_path):
        from app.services.parser_router import ParserError

        raise ParserError("nope")

    monkeypatch.setattr(files_module, "parse", boom)

    response = _upload(client, "broken.md", b"# broken\n")
    assert response.json()["status"] == "failed", response.json()

    vault = Path(os.environ["VAULT_PATH"])
    staged = [p for p in (vault / ".staging").glob("*") if p.suffix != ".json"]
    assert staged, "the staged file should be kept for diagnosis"
