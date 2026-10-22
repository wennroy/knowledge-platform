"""Vault I/O: staging, frontmatter roundtrip, .md write/read."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.config import settings
from app.models import utcnow_iso

log = logging.getLogger(__name__)

STAGING_DIRNAME = ".staging"
FAILED_DIRNAME = ".staging/failed"

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


@dataclass
class Frontmatter:
    meta: dict[str, Any]
    body: str


def parse_frontmatter(text: str) -> Frontmatter:
    """Split a markdown string into (frontmatter_dict, body)."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return Frontmatter(meta={}, body=text)
    try:
        meta = yaml.safe_load(match.group(1)) or {}
        if not isinstance(meta, dict):
            meta = {"_meta": meta}
    except yaml.YAMLError:
        meta = {}
    body = text[match.end() :]
    return Frontmatter(meta=meta, body=body)


def serialize_frontmatter(meta: dict[str, Any]) -> str:
    """Render a YAML frontmatter block with trailing newline + body separator."""
    if not meta:
        return ""
    yaml_text = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).rstrip()
    return f"---\n{yaml_text}\n---\n"


# ---------------------------------------------------------------------- staging
def staging_dir(vault_path: Path | None = None) -> Path:
    base = Path(vault_path or settings.vault_path())
    target = base / STAGING_DIRNAME
    target.mkdir(parents=True, exist_ok=True)
    return target


def failed_dir(vault_path: Path | None = None) -> Path:
    base = Path(vault_path or settings.vault_path())
    target = base / FAILED_DIRNAME
    target.mkdir(parents=True, exist_ok=True)
    return target


def save_staging(
    data: bytes,
    filename: str,
    vault_path: Path | None = None,
) -> Path:
    """Drop ``data`` into the staging dir using a sha256-derived name.

    Returns the path on disk. Writes a sidecar ``<hash>.meta.json`` with the
    original filename so we can recover it later.

    The staged file keeps the original extension: converters such as
    MarkItDown sniff the type from it, and a bare ``<digest>`` file is
    rejected with "File format not allowed". Callers that need the digest
    should read ``path.stem`` (the digest is pure hex, so it never contains
    a dot).
    """
    digest = hashlib.sha256(data).hexdigest()
    target_dir = staging_dir(vault_path)
    suffix = Path(filename).suffix.lower()
    target = target_dir / f"{digest}{suffix}"
    target.write_bytes(data)
    sidecar = {
        "filename": filename,
        "size": len(data),
        "sha256": digest,
        "saved_at": utcnow_iso(),
    }
    (target_dir / f"{digest}.meta.json").write_text(
        json.dumps(sidecar, ensure_ascii=False), encoding="utf-8"
    )
    return target


def write_failed(
    payload: dict[str, Any],
    file_hash: str,
    vault_path: Path | None = None,
) -> Path:
    """Record a failed ingest attempt under .staging/failed/<hash>.json."""
    target = failed_dir(vault_path) / f"{file_hash}.json"
    target.write_text(
        json.dumps(payload, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return target


# ---------------------------------------------------------------------- vault md
def write_md(
    relative_path: str,
    markdown: str,
    frontmatter: dict[str, Any] | None = None,
    vault_path: Path | None = None,
) -> Path:
    """Write a markdown file under the vault with frontmatter."""
    base = Path(vault_path or settings.vault_path())
    base.mkdir(parents=True, exist_ok=True)
    target = (base / relative_path).resolve()
    if not str(target).startswith(str(base.resolve())):
        raise ValueError(f"path escapes vault: {relative_path}")
    target.parent.mkdir(parents=True, exist_ok=True)

    meta = dict(frontmatter or {})
    fm_block = serialize_frontmatter(meta)
    body = markdown.lstrip("\n")
    content = fm_block + body if fm_block else body
    if not content.endswith("\n"):
        content += "\n"
    target.write_text(content, encoding="utf-8")
    return target


def read_md(relative_path: str, vault_path: Path | None = None) -> Frontmatter:
    """Read a markdown file and return parsed frontmatter + body."""
    base = Path(vault_path or settings.vault_path())
    target = (base / relative_path).resolve()
    if not target.exists():
        return Frontmatter(meta={}, body="")
    text = target.read_text(encoding="utf-8")
    return parse_frontmatter(text)


def list_vault(vault_path: Path | None = None) -> list[Path]:
    """List all .md files under the vault (skipping .staging)."""
    base = Path(vault_path or settings.vault_path())
    if not base.exists():
        return []
    out: list[Path] = []
    for p in base.rglob("*.md"):
        if STAGING_DIRNAME in p.parts:
            continue
        out.append(p)
    return sorted(out)
