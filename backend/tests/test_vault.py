"""vault I/O tests."""
from __future__ import annotations

from pathlib import Path

from app.services import vault


def test_save_staging_writes_file_with_sha_name(tmp_path: Path):
    import hashlib

    vault_path = tmp_path / "vault"
    data = b"hello world"
    target = vault.save_staging(data, "greeting.txt", vault_path=vault_path)
    assert target.exists()
    assert target.name == hashlib.sha256(data).hexdigest()
    assert target.read_bytes() == data
    # Sidecar metadata exists
    sidecar = vault_path / vault.STAGING_DIRNAME / f"{target.name}.meta.json"
    assert sidecar.exists()


def test_write_md_injects_frontmatter(tmp_path: Path):
    vault_path = tmp_path / "vault"
    target = vault.write_md(
        "team/foo.md",
        "# Title\n\nBody text.",
        frontmatter={"source_filename": "foo.pdf", "source_hash": "abc"},
        vault_path=vault_path,
    )
    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "source_filename: foo.pdf" in text
    assert "source_hash: abc" in text
    assert "# Title" in text


def test_write_md_rejects_path_traversal(tmp_path: Path):
    import pytest

    vault_path = tmp_path / "vault"
    with pytest.raises(ValueError):
        vault.write_md("../escape.md", "x", vault_path=vault_path)


def test_parse_frontmatter_roundtrip(tmp_path: Path):
    text = (
        "---\n"
        "source_filename: doc.pdf\n"
        "tags: [a, b]\n"
        "---\n\n"
        "Body line.\n"
    )
    fm = vault.parse_frontmatter(text)
    assert fm.meta["source_filename"] == "doc.pdf"
    assert fm.meta["tags"] == ["a", "b"]
    assert "Body line." in fm.body


def test_read_md_returns_parsed(tmp_path: Path):
    vault_path = tmp_path / "vault"
    vault.write_md(
        "notes/personal/x.md",
        "Hello\n",
        frontmatter={"k": "v"},
        vault_path=vault_path,
    )
    fm = vault.read_md("notes/personal/x.md", vault_path=vault_path)
    assert fm.meta["k"] == "v"
    assert "Hello" in fm.body


def test_list_vault_skips_staging(tmp_path: Path):
    vault_path = tmp_path / "vault"
    vault.write_md("team/a.md", "a", vault_path=vault_path)
    vault.write_md("notes/personal/b.md", "b", vault_path=vault_path)
    vault.save_staging(b"junk", "junk.pdf", vault_path=vault_path)
    files = vault.list_vault(vault_path)
    paths = [p.name for p in files]
    assert "a.md" in paths
    assert "b.md" in paths
    assert all(".staging" not in p.parts for p in files)
