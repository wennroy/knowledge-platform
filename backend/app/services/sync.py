"""Vault ↔ index reconciliation and live filesystem watcher."""
from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from app.config import get_settings
from app.services.indexer import LanceIndexer
from app.services.vault import FAILED_DIRNAME, STAGING_DIRNAME, list_vault, read_md

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
        self.on_index = on_index or (
            lambda p: self.indexer.index_file(p, _read(p), _read_source_hash(p))
        )
        self.on_delete = on_delete or (lambda p: self.indexer.delete_file(p))

    # ------------------------------------------------------------------ reconcile
    def startup_reconcile(self, vault_path: Path | None = None) -> dict:
        """Walk the vault and compare with index. Re-index any diff."""
        base = Path(vault_path or get_settings().vault_path())
        results = {"scanned": 0, "indexed": 0, "deleted": 0, "errors": []}

        # Rows written before the relative-path contract hold absolute paths.
        # They can never be matched by a relative-path lookup, so drop them
        # first; the files are re-indexed below with the relative path.
        results["deleted"] += self.indexer.purge_legacy_paths()

        indexed = {s.file_path: s for s in self.indexer.get_status()}
        on_disk: set[str] = set()

        # Files on disk
        for md_path in list_vault(base):
            results["scanned"] += 1
            # Same normalisation the indexer applies, so both sides of the
            # comparison use the identical key.
            rel = self.indexer.rel_path(md_path)
            on_disk.add(rel)
            try:
                try:
                    rel_for_read = md_path.relative_to(base).as_posix()
                except ValueError:
                    rel_for_read = md_path.name
                fm = read_md(rel_for_read, base)
                content_hash = fm.meta.get("source_hash")
                # Always re-read full content for safety in PoC
                body = fm.body
                # Carry the upload digest (frontmatter `source_hash`) so the
                # upload-dedup key survives a reconcile pass.
                source_hash = str(content_hash or "")
                status = self.indexer.index_file(md_path, body, source_hash)
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
                results["errors"].append({"path": rel, "error": str(exc)})

        # Files in index but missing from disk
        for path in list(indexed.keys()):
            if path not in on_disk:
                self.indexer.delete_file(path)
                results["deleted"] += 1

        # F-01 fix: refresh the LanceDB row-count gauge so /metrics reflects
        # the post-reconcile state for monitoring.
        self.indexer.refresh_row_count()

        return results

    def rebuild_index(self, vault_path: Path | None = None) -> dict:
        """Wipe the index and rebuild it from the vault.

        Used by ``POST /admin/index/rebuild``. Clearing first is required:
        rows written before the relative-path contract cannot be matched (and
        therefore cannot be deleted) by a relative-path lookup, so they would
        survive a plain re-index and show up as duplicates.
        """
        self.indexer.clear_all()
        return self.startup_reconcile(vault_path)

    # ------------------------------------------------------------------ watchdog
    def start_watchdog(self, vault_path: Path | None = None) -> Observer:
        """Start the watchdog observer with 500ms debouncing."""
        base = Path(vault_path or get_settings().vault_path())
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

    @staticmethod
    def _is_vault_doc(path: str) -> bool:
        """Only real vault documents — never the staging area.

        The staging directory holds a full copy of every upload under its
        original name, and since ``save_staging`` keeps the extension those
        copies end with ``.md``. Without this filter the watchdog indexes
        them: the content is embedded twice and the index gains rows whose
        ``file_path`` points at a scratch file that is deleted moments later.
        """
        if not path.endswith(".md"):
            return False
        parts = Path(path).parts
        return STAGING_DIRNAME not in parts and FAILED_DIRNAME not in parts

    def on_modified(self, event):  # type: ignore[override]
        if event.is_directory:
            return
        if not self._is_vault_doc(event.src_path):
            return
        self.parent._enqueue(Path(event.src_path))

    def on_created(self, event):  # type: ignore[override]
        if event.is_directory:
            return
        if not self._is_vault_doc(event.src_path):
            return
        self.parent._enqueue(Path(event.src_path))

    def on_deleted(self, event):  # type: ignore[override]
        if event.is_directory:
            return
        if not self._is_vault_doc(event.src_path):
            return
        self.parent._enqueue(Path(event.src_path))

    def on_moved(self, event):  # type: ignore[override]
        if event.is_directory:
            return
        if not self._is_vault_doc(event.dest_path):
            return
        self.parent._enqueue(Path(event.dest_path))


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _read_source_hash(path: Path) -> str:
    """The sha256 of the original upload, taken from the frontmatter.

    Watchdog-triggered indexing must keep the upload-dedup key intact,
    otherwise a file that was indexed by the watcher could not be detected
    as a duplicate on a later upload.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return ""
    match = re.search(r"^source_hash:\s*(\S+)\s*$", text, re.MULTILINE)
    return match.group(1) if match else ""
