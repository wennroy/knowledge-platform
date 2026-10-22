"""FastAPI application entry point."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.config import settings
from app.deps import configure_logging
from app.metrics import REGISTRY as METRICS_REGISTRY
from app.routes import admin_index, chat, files, graph, search
from app.services.sync import VaultIndexer

configure_logging()
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    """Boot watchdog + reconcile, then yield, then stop watchdog."""
    indexer = VaultIndexer()
    # Reconcile is blocking IO (embedding + LanceDB writes). It must run off
    # the event loop: index_file() calls asyncio.run() internally for the
    # embedding call, which raises "asyncio.run() cannot be called from a
    # running event loop" when invoked synchronously from async context.
    try:
        await asyncio.to_thread(indexer.startup_reconcile)
    except Exception as exc:  # noqa: BLE001
        # Record the failure on app.state instead of only logging it: a
        # swallowed startup error makes the whole index silently empty.
        log.exception("startup reconcile failed")
        app.state.startup_reconcile_error = str(exc)
    else:
        app.state.startup_reconcile_error = None
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
app.include_router(files.tree_router)
app.include_router(search.router)
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


# Static mount for the unified frontend SPA (vite build output).
# The directory is resolved from this file, not from the process cwd, so the
# mount works regardless of where uvicorn was started from.
_APP_DIR = Path(__file__).resolve().parent / "static" / "app"
if _APP_DIR.is_dir():
    # History-mode fallback for deep links (``/app/graph``): serve the built
    # asset when it exists, otherwise hand back index.html so the client-side
    # router can take over. This route is registered *before* the mount so it
    # wins over StaticFiles' 404 for unknown paths.
    @app.get("/app/{spa_path:path}", include_in_schema=False)
    async def app_spa(spa_path: str) -> FileResponse:
        candidate = (_APP_DIR / spa_path).resolve()
        if candidate.is_relative_to(_APP_DIR) and candidate.is_file():
            return FileResponse(candidate)
        # A request for a *file* (it has an extension) must not be answered
        # with index.html: a stale cached index.html can reference a bundle
        # that no longer exists, and serving HTML for it makes the browser
        # fail with a MIME error instead of a clear 404.
        if PurePosixPath(spa_path).suffix:
            raise HTTPException(status_code=404, detail="asset not found")
        index = _APP_DIR / "index.html"
        if index.exists():
            return FileResponse(index)
        raise HTTPException(status_code=404, detail="not found")

    app.mount(
        "/app",
        StaticFiles(directory=str(_APP_DIR), html=True),
        name="app-spa",
    )
else:  # pragma: no cover - only when the SPA has not been built yet
    log.warning("frontend SPA not built at %s; /app not mounted", _APP_DIR)


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


# SPA history fallback. Registered *last* so every API route (``/v1/*``,
# ``/graph``, ``/healthz``, ``/metrics``, ``/admin/*``) is matched first —
# FastAPI resolves routes in registration order.
@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str) -> FileResponse:
    index = _APP_DIR / "index.html"
    if _APP_DIR.is_dir() and index.exists():
        return FileResponse(index)
    raise HTTPException(status_code=404, detail="not found")
