"""Admin endpoints for inspecting and triggering index operations."""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
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
    statuses = indexer.get_status()
    return {"count": len(statuses), "items": [s.model_dump() for s in statuses]}


@router.post("/scan")
async def trigger_scan(vault: VaultIndexer = Depends(_vault_indexer)) -> dict:
    """Trigger a full reconcile pass."""
    result = await asyncio.to_thread(vault.startup_reconcile)
    return result


@router.post("/reindex")
async def reindex_file(
    body: ReindexRequest,
    indexer: LanceIndexer = Depends(_lance_indexer),
) -> dict:
    """Re-index a single markdown file by path (relative to vault)."""
    base = Path(settings.VAULT_PATH).expanduser().resolve()
    target = (base / body.path).resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=400, detail="path escapes vault")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    fm = read_md(body.path)
    status = await asyncio.to_thread(indexer.index_file, target, fm.body)
    return status.model_dump()
