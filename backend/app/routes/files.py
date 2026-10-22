"""File ingestion + vault listing endpoints."""
from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from app.config import get_settings
from app.deps import get_logger
from app.models import UploadResponse
from app.services.indexer import LanceIndexer
from app.services.parser_router import ParserError, parse
from app.services.vault import read_md, save_staging, write_failed, write_md

log = get_logger("routes.files")

router = APIRouter(prefix="/v1/files", tags=["files"])

# The document tree lives at ``/v1/tree`` (not under ``/v1/files``), so it gets
# its own router with a different prefix.
tree_router = APIRouter(prefix="/v1", tags=["files"])


def _indexer() -> LanceIndexer:
    """FastAPI dependency: a single LanceIndexer per process is fine for PoC."""
    return LanceIndexer()


def _ext_ok(filename: str) -> bool:
    suffix = Path(filename).suffix.lower()
    return suffix in get_settings().ALLOWED_EXTENSIONS


def _route_for(suffix: str) -> str:
    """Map an extension to a vault subdir."""
    s = suffix.lower()
    if s == ".md":
        return "notes/personal"
    return "team"


def _discard_staged(staged: Path, vault_path: Path | None = None) -> None:
    """Remove the staged copy of an upload once it has been indexed.

    The staging directory is a scratch area, not an archive: keeping every
    uploaded file there would duplicate the whole vault on disk.
    """
    sidecar = staged.with_name(f"{staged.stem}.meta.json")
    for path in (staged, sidecar):
        try:
            path.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - best effort cleanup
            log.warning("could not remove staged file %s", path)


# ------------------------------------------------------------------ vault helpers
def _vault_base() -> Path:
    """Resolved vault root.

    Uses ``get_settings()`` rather than the module-level ``settings``
    singleton so the vault location always reflects the current
    environment (the singleton is bound at import time).
    """
    return get_settings().vault_path()


def _safe_target(base: Path, relative_path: str) -> Path:
    """Resolve ``relative_path`` inside the vault, rejecting traversal.

    Same guard as the delete endpoint: resolve first, then check the result is
    still inside the vault root.
    """
    target = (base / relative_path).resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=400, detail="path escapes vault")
    return target


def _coerce_tags(value: Any) -> list[str]:
    """Best-effort coercion of a frontmatter ``tags`` field to list[str]."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(t) for t in value if isinstance(t, (str, int, float))]
    if isinstance(value, str):
        return [t.strip() for t in value.split(",") if t.strip()]
    return []


def _iso_mtime(path: Path) -> str:
    """ISO-8601 timestamp of the file's mtime."""
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()


@router.post("", response_model=UploadResponse)
async def upload_file(
    file: Annotated[UploadFile, File(...)],
    request: Request,
    indexer: LanceIndexer = Depends(_indexer),
) -> UploadResponse:
    """Accept a single upload, parse it, write into the vault, and index.

    F-05 fix: read the optional ``X-Uploader`` header (set by the reverse
    proxy) so every ingested markdown records who uploaded it.
    """
    uploader = request.headers.get("X-Uploader") or "unknown"

    if not file.filename:
        raise HTTPException(status_code=400, detail="missing filename")
    if not _ext_ok(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"extension not allowed: {Path(file.filename).suffix}",
        )

    data = await file.read()
    if len(data) > get_settings().MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large (>50MB)")
    if not data:
        raise HTTPException(status_code=400, detail="empty file")

    suffix = Path(file.filename).suffix.lower()
    staged = save_staging(data, file.filename, vault_path=_vault_base())
    # The staged file is named "<sha256><ext>"; the digest is its stem.
    file_hash = staged.stem

    # Dedup by the sha256 of the *uploaded bytes*. The index stores the
    # parsed markdown's hash separately (``file_hash``), so comparing that
    # against the upload digest would never match.
    # Only a successfully indexed document counts as a duplicate: a failed
    # ingest (e.g. a transient embedding outage) must not block the user
    # from uploading the same file again.
    for status_row in indexer.get_status():
        if (
            status_row.source_hash
            and status_row.source_hash == file_hash
            and status_row.status == "ok"
        ):
            from app.metrics import kb_index_files_total

            kb_index_files_total.labels(status="skipped").inc()
            return UploadResponse(
                id=file_hash,
                status="skipped",
                parser="unknown",
                chunks=status_row.chunk_count,
                file_path=status_row.file_path,
                error=f"duplicate of {status_row.file_path}",
            )

    try:
        # Run the sync parser in a thread so we don't block the loop.
        result = await asyncio.to_thread(parse, staged)
    except ParserError as exc:
        payload = {
            "filename": file.filename,
            "sha256": file_hash,
            "error": str(exc),
            "stage": "parse",
        }
        write_failed(payload, file_hash, vault_path=_vault_base())
        log.warning("parse failed for %s: %s", file.filename, exc)
        return UploadResponse(
            id=file_hash,
            status="failed",
            parser="unknown",
            chunks=0,
            error=str(exc),
        )

    ts = int(time.time())
    safe_name = Path(file.filename).stem.replace(" ", "_") or "untitled"
    rel = f"{_route_for(suffix)}/{ts}_{safe_name}.md"
    fm = {
        "source_filename": file.filename,
        "source_hash": file_hash,
        "ingested_at": result.model_dump(mode="json").get("ingested_at", ""),
        "parser": result.parser,
        "ocr_used": result.ocr_used,
        "uploader": uploader,  # F-05: write who uploaded for audit
    }
    import datetime as _dt

    fm["ingested_at"] = _dt.datetime.now(_dt.UTC).isoformat()

    target = write_md(rel, result.markdown, fm, vault_path=_vault_base())
    indexed = await asyncio.to_thread(
        indexer.index_file, target, result.markdown, file_hash
    )

    # The staged copy is only needed until the document is written and
    # indexed. Without this the staging directory grows by one full copy of
    # every uploaded file, forever. Failed parses keep their staged file for
    # diagnosis (and `write_failed` already recorded the error).
    if indexed.status == "ok":
        _discard_staged(staged, vault_path=_vault_base())

    return UploadResponse(
        id=file_hash,
        status=indexed.status,
        parser=result.parser,
        chunks=indexed.chunk_count,
        # Vault-relative POSIX path — never the absolute location on disk.
        file_path=indexer.rel_path(target),
        error=indexed.error,
    )


@router.get("")
async def list_files() -> dict:
    from app.services.vault import list_vault

    base = _vault_base()
    files: list[dict] = []
    for p in list_vault(base):
        stat = p.stat()
        try:
            rel = p.relative_to(base).as_posix()
        except ValueError:  # pragma: no cover - list_vault yields under base
            rel = p.name
        files.append(
            {
                "file_path": rel,
                "size_bytes": stat.st_size,
                "ingested_at": stat.st_mtime,
            }
        )
    return {"files": files, "count": len(files)}


@router.delete("/{file_path:path}")
async def delete_file(file_path: str, indexer: LanceIndexer = Depends(_indexer)) -> dict:
    """Delete a vault document.

    ``file_path`` is relative to the vault root (``team/api-design.md``).
    """
    base = _vault_base()
    target = (base / file_path).resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=400, detail="path escapes vault")
    if not target.exists():
        raise HTTPException(status_code=404, detail="not found")
    target.unlink()
    # The indexer normalises the path, so the relative rows are removed.
    indexer.delete_file(target)
    return {"deleted": file_path}


@router.get("/{file_path:path}")
async def read_file(file_path: str) -> dict:
    """Read one markdown document (body + frontmatter + stat info).

    ``file_path`` is relative to the vault root. Path traversal is rejected
    with the same resolve-and-compare guard the delete endpoint uses.
    """
    base = _vault_base()
    target = _safe_target(base, file_path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="not found")
    fm = read_md(file_path, vault_path=base)
    stat = target.stat()
    return {
        "file_path": file_path,
        "content": fm.body,
        "frontmatter": fm.meta or {},
        "size_bytes": stat.st_size,
        "updated_at": _iso_mtime(target),
    }


# ------------------------------------------------------------------ doc tree
def _build_tree(base: Path) -> list[dict[str, Any]]:
    """Build the nested document tree for the vault.

    Directories come before files; each group is sorted by name. Only
    markdown files are listed, and only directories that contain at least one
    markdown file are kept.
    """
    if not base.exists():
        return []

    def walk(directory: Path, prefix: str) -> list[dict[str, Any]]:
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name)
        except (OSError, PermissionError):
            return []

        dirs: list[dict[str, Any]] = []
        files: list[dict[str, Any]] = []

        for entry in entries:
            if entry.name.startswith("."):
                # skip .staging, .git, .obsidian, ...
                continue
            rel = f"{prefix}{entry.name}"
            if entry.is_dir():
                children = walk(entry, f"{rel}/")
                if children:
                    dirs.append(
                        {
                            "name": entry.name,
                            "type": "dir",
                            "path": rel,
                            "children": children,
                        }
                    )
            elif entry.is_file() and entry.suffix.lower() == ".md":
                fm = read_md(rel, vault_path=base)
                stat = entry.stat()
                files.append(
                    {
                        "name": entry.name,
                        "type": "file",
                        "path": rel,
                        "tags": _coerce_tags((fm.meta or {}).get("tags")),
                        "size_bytes": stat.st_size,
                        "updated_at": _iso_mtime(entry),
                    }
                )

        # Directories first, then files; each group already name-sorted.
        return dirs + files

    return walk(base, "")


@tree_router.get("/tree")
async def get_tree() -> dict:
    """Return the vault as a nested document tree.

    Each file node carries ``tags`` (from its frontmatter), ``size_bytes`` and
    ``updated_at``; directories carry their children.
    """
    base = _vault_base()
    return {"tree": _build_tree(base)}
