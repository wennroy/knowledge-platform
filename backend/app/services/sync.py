"""Vault ↔ index reconciliation and live filesystem watcher."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from app.config import settings
from app.services.indexer import LanceIndexer
from app.services.vault import list_vault, read_md

log = logging.getLogger(__name__)

DEBOUNCE_MS = 500


class VaultIndexer:
    """Reconcile vault files with the LanceDB index and run a watchdog."""

    def __init__(
        self,
        indexer: LanceIndexer | None = None,
        on_index: Callable[[Path], None] | None = None,
        on_delete: Callable[[Path], None] | None = None,
    ) -> None:
        self.indexer = indexer or LanceIndexer()
        self._observer: Observer | None = None
        self._pending: dict[str, float] = {}
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self.on_index = on_index or (lambda p: self.indexer.index_file(p, _read(p)))
        self.on_delete = on_delete or (lambda p: self.indexer.delete_file(p))

    # ------------------------------------------------------------------ reconcile
    def startup_reconcile(self, vault_path: Path | None = None) -> dict:
        """Walk the vault and compare with index. Re-index any diff."""
        base = Path(vault_path or settings.vault_path())
        indexed = {s.file_path: s for s in self.indexer.get_status()}
        results = {"scanned": 0, "indexed": 0, "deleted": 0, "errors": []}

        # Files on disk
        on_disk: set[str] = set()
        for md_path in list_vault(base):
            results["scanned"] += 1
            rel = str(md_path)
            on_disk.add(rel)
            try:
                fm = read_md(str(md_path.relative_to(base)), base)
                content_hash = fm.meta.get("source_hash")
                # Always re-read full content for safety in PoC
                body = fm.body
                status = self.indexer.index_file(md_path, body)
                if status.status != "ok":
                    results["errors"].append(
                        {"path": rel, "error": status.error or "unknown"}
                    )
                else:
                    results["indexed"] += 1
                    if content_hash and content_hash != status.file_hash:
                        log.info("hash drift on %s; re-indexed", rel)
            except Exception as exc:  # noqa: BLE001
                log.exception("reconcile failed for %s", md_path)
                results["errors"].append({"path": str(md_path), "error": str(exc)})

        # Files in index but missing from disk
        for path in list(indexed.keys()):
            if path not in on_disk:
                self.indexer.delete_file(path)
                results["deleted"] += 1

        # F-01 fix: refresh the LanceDB row-count gauge so /metrics reflects
        # the post-reconcile state for monitoring.
        self.indexer.refresh_row_count()

        return results

    # ------------------------------------------------------------------ watchdog
    def start_watchdog(self, vault_path: Path | None = None) -> Observer:
        """Start the watchdog observer with 500ms debouncing."""
        base = Path(vault_path or settings.vault_path())
        base.mkdir(parents=True, exist_ok=True)
        handler = _Handler(self)
        self._observer = Observer()
        self._observer.schedule(handler, str(base), recursive=True)
        self._observer.start()
        log.info("watchdog started on %s", base)
        return self._observer

    def stop_watchdog(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None

    # ------------------------------------------------------------------ debounce
    def _enqueue(self, path: Path) -> None:
        key = str(path)
        with self._lock:
            self._pending[key] = time.time()
            if self._timer is None:
                self._timer = threading.Timer(DEBOUNCE_MS / 1000.0, self._flush)
                self._timer.daemon = True
                self._timer.start()

    def _flush(self) -> None:
        with self._lock:
            pending = list(self._pending.items())
            self._pending.clear()
            self._timer = None
        for key, _ts in pending:
            path = Path(key)
            try:
                if not path.exists():
                    self.on_delete(path)
                else:
                    self.on_index(path)
            except Exception:  # noqa: BLE001
                log.exception("watchdog handler failed for %s", path)


class _Handler(FileSystemEventHandler):
    def __init__(self, parent: VaultIndexer) -> None:
        self.parent = parent

    def on_modified(self, event):  # type: ignore[override]
        if event.is_directory:
            return
        if not event.src_path.endswith(".md"):
            return
        self.parent._enqueue(Path(event.src_path))

    def on_created(self, event):  # type: ignore[override]
        if event.is_directory:
            return
        if not event.src_path.endswith(".md"):
            return
        self.parent._enqueue(Path(event.src_path))

    def on_deleted(self, event):  # type: ignore[override]
        if event.is_directory:
            return
        if not event.src_path.endswith(".md"):
            return
        self.parent._enqueue(Path(event.src_path))

    def on_moved(self, event):  # type: ignore[override]
        if event.is_directory:
            return
        if not event.src_path.endswith(".md"):
            return
        self.parent._enqueue(Path(event.dest_path))


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
