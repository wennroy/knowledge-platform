"""File ingestion + vault listing endpoints."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from app.config import settings
from app.deps import get_logger
from app.models import UploadResponse
from app.services.indexer import LanceIndexer
from app.services.parser_router import ParserError, parse
from app.services.vault import save_staging, write_failed, write_md

log = get_logger("routes.files")

router = APIRouter(prefix="/v1/files", tags=["files"])


def _indexer() -> LanceIndexer:
    """FastAPI dependency: a single LanceIndexer per process is fine for PoC."""
    return LanceIndexer()


def _ext_ok(filename: str) -> bool:
    suffix = Path(filename).suffix.lower()
    return suffix in settings.ALLOWED_EXTENSIONS


def _route_for(suffix: str) -> str:
    """Map an extension to a vault subdir."""
    s = suffix.lower()
    if s == ".md":
        return "notes/personal"
    return "team"


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
    if len(data) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large (>50MB)")
    if not data:
        raise HTTPException(status_code=400, detail="empty file")

    suffix = Path(file.filename).suffix.lower()
    staged = save_staging(data, file.filename)
    file_hash = staged.name

    # A5 fix — dedup by content sha256 before parsing/embedding.
    # F-03 fix: reuse the injected indexer instead of constructing a second.
    for status_row in indexer.get_status():
        if status_row.file_hash == file_hash and status_row.status == "ok":
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
        write_failed(payload, file_hash)
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

    target = write_md(rel, result.markdown, fm)
    indexed = await asyncio.to_thread(indexer.index_file, target, result.markdown)

    return UploadResponse(
        id=file_hash,
        status=indexed.status,
        parser=result.parser,
        chunks=indexed.chunk_count,
        file_path=str(target),
        error=indexed.error,
    )


@router.get("")
async def list_files() -> dict:
    from app.services.vault import list_vault

    base = Path(settings.VAULT_PATH).expanduser().resolve()
    files: list[dict] = []
    for p in list_vault(base):
        stat = p.stat()
        files.append(
            {
                "file_path": str(p),
                "size_bytes": stat.st_size,
                "ingested_at": stat.st_mtime,
            }
        )
    return {"files": files, "count": len(files)}


@router.delete("/{file_path:path}")
async def delete_file(file_path: str, indexer: LanceIndexer = Depends(_indexer)) -> dict:
    base = Path(settings.VAULT_PATH).expanduser().resolve()
    target = (base / file_path).resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=400, detail="path escapes vault")
    if not target.exists():
        raise HTTPException(status_code=404, detail="not found")
    target.unlink()
    indexer.delete_file(target)
    return {"deleted": file_path}
