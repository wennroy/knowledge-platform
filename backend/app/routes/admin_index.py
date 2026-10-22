"""Admin endpoints for inspecting and triggering index operations."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from app.config import get_settings
from app.deps import get_logger
from app.models import ReindexRequest
from app.services.indexer import LanceIndexer
from app.services.sync import VaultIndexer
from app.services.vault import read_md

log = get_logger("routes.admin_index")

router = APIRouter(prefix="/admin/index", tags=["admin"])


def _vault_indexer() -> VaultIndexer:
    return VaultIndexer()


def _lance_indexer() -> LanceIndexer:
    return LanceIndexer()


@router.get("/status")
async def get_status(indexer: LanceIndexer = Depends(_lance_indexer)) -> dict:
    """Per-file index state.

    ``file_path`` is always relative to the vault root (``team/api.md``).
    """
    statuses = indexer.get_status()
    return {"count": len(statuses), "items": [s.model_dump() for s in statuses]}


@router.post("/scan")
async def trigger_scan(vault: VaultIndexer = Depends(_vault_indexer)) -> dict:
    """Trigger a full reconcile pass."""
    result = await asyncio.to_thread(vault.startup_reconcile)
    return result


@router.post("/rebuild")
async def rebuild_index(vault: VaultIndexer = Depends(_vault_indexer)) -> dict:
    """Wipe the index and rebuild it from the vault (idempotent).

    Needed once after upgrading from a version that stored absolute paths:
    those rows cannot be matched by a relative-path lookup, so they are
    removed instead of being re-indexed next to the new relative rows.
    """
    result = await asyncio.to_thread(vault.rebuild_index)
    return result


@router.post("/reindex")
async def reindex_file(
    body: ReindexRequest,
    indexer: LanceIndexer = Depends(_lance_indexer),
) -> dict:
    """Re-index a single markdown file by path (relative to vault)."""
    base = get_settings().vault_path()
    target = (base / body.path).resolve()
    # `is_relative_to` rather than a string prefix — see the note in
    # `routes/files.py`.
    if not target.is_relative_to(base):
        raise HTTPException(status_code=400, detail="path escapes vault")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    fm = read_md(body.path, vault_path=base)
    # The frontmatter carries the sha256 of the original uploaded bytes, so
    # a re-index keeps the upload-dedup key intact.
    source_hash = str(fm.meta.get("source_hash") or "")
    status = await asyncio.to_thread(indexer.index_file, target, fm.body, source_hash)
    return status.model_dump()
