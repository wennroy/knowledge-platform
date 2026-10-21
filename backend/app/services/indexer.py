"""LanceDB-backed chunk index + per-file status tracking."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa

from app.config import get_settings
from app.metrics import kb_index_files_total, kb_lancedb_rows
from app.models import IndexStatus, utcnow_iso
from app.services import embedder as embedder_module
from app.services.chunker import split

log = logging.getLogger(__name__)

CHUNKS_TABLE = "chunks"
STATUS_TABLE = "index_status"

# LanceDB's delete()+add() is a read-modify-write transaction. Two concurrent
# writers on the same table collide with "Overwrite transaction was preempted"
# / "Append transaction is incompatible with concurrent Overwrite". The backend
# runs as a single process, so a process-wide re-entrant lock around every
# write serialises the critical section. RLock because _upsert_status is also
# called from within index_file's locked region.
_WRITE_LOCK = threading.RLock()


class LanceIndexer:
    """Wraps a LanceDB connection with two tables.

    The class is safe to instantiate from sync or async contexts: all heavy
    work (embedding calls) is dispatched via ``asyncio.run`` if needed.
    """

    def __init__(self, lancedb_path: Path | None = None) -> None:
        s = get_settings()
        self.lancedb_path = Path(lancedb_path or s.lancedb_path())
        self.lancedb_path.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(self.lancedb_path))
        # Table creation is itself a write transaction, so it must not overlap
        # with another thread's add/delete.
        with _WRITE_LOCK:
            self._chunks = self._ensure_chunks_table()
            self._status = self._ensure_status_table()

    def _refresh_tables(self) -> None:
        """Re-open both tables to pick up the latest committed version.

        A LanceDB table handle is bound to the version it was opened at. If
        another writer committed since, writing through the stale handle
        raises a commit conflict. Re-opening inside the write lock gives us
        the current version.
        """
        try:
            self._chunks = self._db.open_table(CHUNKS_TABLE)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._status = self._db.open_table(STATUS_TABLE)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ tables
    def _ensure_chunks_table(self):
        s = get_settings()
        schema = pa.schema(
            [
                pa.field("id", pa.string()),
                pa.field("file_path", pa.string()),
                pa.field("file_hash", pa.string()),
                pa.field("chunk_index", pa.int64()),
                pa.field("text", pa.string()),
                pa.field("heading_path", pa.string()),  # JSON-encoded list
                pa.field("start_offset", pa.int64()),
                pa.field("end_offset", pa.int64()),
                pa.field("ingested_at", pa.string()),
                pa.field(
                    "vector",
                    pa.list_(pa.float32(), s.EMBEDDING_DIM),
                ),
            ]
        )
        return self._ensure_table(CHUNKS_TABLE, schema)

    def _ensure_status_table(self):
        schema = pa.schema(
            [
                pa.field("file_path", pa.string()),
                pa.field("file_hash", pa.string()),
                pa.field("chunk_count", pa.int64()),
                pa.field("status", pa.string()),
                pa.field("updated_at", pa.string()),
                pa.field("error", pa.string()),
            ]
        )
        return self._ensure_table(STATUS_TABLE, schema)

    def _ensure_table(self, name: str, schema: pa.Schema):
        # Retry to absorb the open/create race when two LanceIndexer objects
        # initialize the same LanceDB directory concurrently (H2 fix).
        for _attempt in range(3):
            try:
                return self._db.open_table(name)
            except (KeyError, FileNotFoundError, ValueError, OSError):
                pass
            try:
                return self._db.create_table(name, schema=schema, mode="create")
            except (ValueError, OSError):
                # Another worker just created it; loop and open.
                continue
        # Final fallback: open must succeed now.
        return self._db.open_table(name)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def hash_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def hash_file(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for block in iter(lambda: f.read(65536), b""):
                h.update(block)
        return h.hexdigest()

    @staticmethod
    def _coerce_row(row: dict[str, Any]) -> dict[str, Any]:
        """Cast chunk rows to types matching the pyarrow schema."""
        return {
            "id": str(row["id"]),
            "file_path": str(row["file_path"]),
            "file_hash": str(row["file_hash"]),
            "chunk_index": int(row["chunk_index"]),
            "text": str(row["text"]),
            "heading_path": _json_dumps(row.get("heading_path", [])),
            "start_offset": int(row.get("start_offset", 0)),
            "end_offset": int(row.get("end_offset", 0)),
            "ingested_at": str(row.get("ingested_at") or utcnow_iso()),
        }

    def _delete_by_hash(self, table, file_hash: str) -> int:
        try:
            table.delete(f"file_hash = '{file_hash}'")
            return 1
        except Exception:  # noqa: BLE001
            return 0

    def _delete_by_file_path(self, table, file_path: str) -> int:
        """Delete all rows for a given file_path (regardless of hash).

        Used so content changes to the same file clean up old chunks (E2 fix).
        """
        try:
            # Quote-escape: file_path may contain single quotes from filenames.
            escaped = file_path.replace("'", "''")
            table.delete(f"file_path = '{escaped}'")
            return 1
        except Exception:  # noqa: BLE001
            return 0

    def _refresh_row_count(self) -> None:
        """Push the current chunk row count into the kb_lancedb_rows gauge."""
        try:
            count = self._chunks.count_rows()
            kb_lancedb_rows.set(count)
        except Exception:  # noqa: BLE001
            pass

    def refresh_row_count(self) -> None:
        """Public hook for sync.startup_reconcile to update the gauge."""
        self._refresh_row_count()

    # ------------------------------------------------------------------ public
    def index_file(self, file_path: Path, markdown: str) -> IndexStatus:
        """Chunk + embed + upsert for a single markdown file."""
        file_path = Path(file_path)
        file_hash = self.hash_text(markdown)
        source_path = str(file_path)
        try:
            chunk_dicts = split(markdown, source_path, file_hash)
            if not chunk_dicts:
                self._upsert_status(source_path, file_hash, 0, "ok")
                return IndexStatus(
                    file_path=source_path,
                    file_hash=file_hash,
                    chunk_count=0,
                    status="ok",
                    updated_at=utcnow_iso(),
                )

            vectors = _maybe_await(embedder_module.embed_batch([c["text"] for c in chunk_dicts]))
            now = utcnow_iso()
            rows = []
            for c, vec in zip(chunk_dicts, vectors, strict=False):
                row = self._coerce_row(c)
                row["ingested_at"] = now
                row["vector"] = [float(x) for x in vec.tolist()]
                rows.append(row)

            # Upsert: drop existing chunks + status for this file_path then append.
            # Using file_path (not file_hash) ensures content changes don't leave
            # orphan chunks from the previous hash (E2 fix).
            # The whole delete+add sequence runs under the process-wide write
            # lock: LanceDB transactions conflict if two writers interleave.
            with _WRITE_LOCK:
                self._refresh_tables()
                self._delete_by_file_path(self._chunks, source_path)
                self._delete_by_file_path(self._status, source_path)
                self._chunks.add(rows)

                self._upsert_status(source_path, file_hash, len(rows), "ok")
            kb_index_files_total.labels(status="indexed").inc()
            self._refresh_row_count()
            return IndexStatus(
                file_path=source_path,
                file_hash=file_hash,
                chunk_count=len(rows),
                status="ok",
                updated_at=now,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("index_file failed for %s", file_path)
            err = str(exc)
            try:
                self._upsert_status(source_path, file_hash, 0, "failed", error=err)
            except Exception:  # pragma: no cover
                pass
            kb_index_files_total.labels(status="failed").inc()
            return IndexStatus(
                file_path=source_path,
                file_hash=file_hash,
                chunk_count=0,
                status="failed",
                updated_at=utcnow_iso(),
                error=err,
            )

    def delete_file(self, file_path: Path | str) -> None:
        target = str(file_path)
        # F-04 fix: clear all rows for this file_path directly, instead of
        # picking a single hash. This avoids orphan status rows when multiple
        # hashes ever accumulated for the same path.
        with _WRITE_LOCK:
            self._refresh_tables()
            self._delete_by_file_path(self._chunks, target)
            self._delete_by_file_path(self._status, target)

    def get_status(self) -> list[IndexStatus]:
        rows = self._safe_status_rows()
        out: list[IndexStatus] = []
        for r in rows:
            try:
                out.append(
                    IndexStatus(
                        file_path=str(r.get("file_path", "")),
                        file_hash=str(r.get("file_hash", "")),
                        chunk_count=int(r.get("chunk_count", 0) or 0),
                        status=str(r.get("status", "unknown")),
                        updated_at=str(r.get("updated_at", "")),
                        error=r.get("error"),
                    )
                )
            except Exception:  # noqa: BLE001
                continue
        return out

    # ------------------------------------------------------------------ internal
    def _safe_status_rows(self) -> list[dict[str, Any]]:
        try:
            tbl = self._db.open_table(STATUS_TABLE)
        except (KeyError, FileNotFoundError, ValueError, OSError):
            return []
        try:
            return tbl.search().to_list()
        except Exception:  # noqa: BLE001
            return []

    def _upsert_status(
        self,
        file_path: str,
        file_hash: str,
        chunk_count: int,
        status: str,
        error: str | None = None,
    ) -> None:
        # Drop any existing rows for this file_path, then add the new one.
        # Keyed by file_path (not file_hash): two different documents can share
        # identical content, and deleting by hash would drop the other
        # document's status row.
        # Locked because this is also reached from index_file's error path,
        # outside the locked region.
        with _WRITE_LOCK:
            self._refresh_tables()
            self._delete_by_file_path(self._status, file_path)
            self._status.add(
                [
                    {
                        "file_path": file_path,
                        "file_hash": file_hash,
                        "chunk_count": int(chunk_count),
                        "status": status,
                        "updated_at": utcnow_iso(),
                        "error": error or "",
                    }
                ]
            )


def _maybe_await(value):
    """Await if value is awaitable; otherwise return as-is."""
    if asyncio.iscoroutine(value):
        return asyncio.run(value)
    return value


def _json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)
