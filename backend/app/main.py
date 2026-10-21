"""FastAPI application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.config import settings
from app.deps import configure_logging
from app.metrics import REGISTRY as METRICS_REGISTRY
from app.routes import admin_index, chat, files, graph
from app.services.sync import VaultIndexer

configure_logging()
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    """Boot watchdog + reconcile, then yield, then stop watchdog."""
    indexer = VaultIndexer()
    try:
        indexer.startup_reconcile()
    except Exception:  # noqa: BLE001
        log.exception("startup reconcile failed")
    try:
        indexer.start_watchdog()
    except Exception:  # noqa: BLE001
        log.exception("watchdog failed to start")
    app.state.vault_indexer = indexer
    try:
        yield
    finally:
        indexer.stop_watchdog()


app = FastAPI(
    title="Knowledge Platform",
    version="0.1.0",
    lifespan=lifespan,
)

# Open CORS for PoC; tighten before going to production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(files.router)
app.include_router(admin_index.router)
app.include_router(chat.router)
app.include_router(graph.router)

# Static mount for the graph-viewer SPA (vite build output).
# The directory is resolved from this file, not from the process cwd, so the
# mount works regardless of where uvicorn was started from.
_GRAPH_SPA_DIR = Path(__file__).resolve().parent / "static" / "graph"
if _GRAPH_SPA_DIR.is_dir():
    app.mount(
        "/static/graph",
        StaticFiles(directory=str(_GRAPH_SPA_DIR), html=True),
        name="graph-spa",
    )
else:  # pragma: no cover - only when the SPA has not been built yet
    log.warning("graph SPA not built at %s; /static/graph/ not mounted", _GRAPH_SPA_DIR)


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.get("/metrics")
async def metrics() -> Response:
    """Prometheus scrape endpoint.

    Exposes the default process-local registry. Each scrape returns the
    current snapshot of kb_* metrics.
    """
    return Response(
        content=generate_latest(METRICS_REGISTRY),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get("/")
async def root() -> dict:
    return {
        "service": "knowledge-platform",
        "version": "0.1.0",
        "vault": settings.VAULT_PATH,
        "lancedb": settings.LANCEDB_PATH,
    }
