"""Retrieval: query embedding + LanceDB vector search + LLM context formatting.

Wiring notes
------------
The B1 contract assumed ``Indexer.search`` and ``Indexer.embed_query`` exist on
the indexer; the actual ``LanceIndexer`` exposes only ``index_file``,
``delete_file``, and ``get_status``. To avoid touching B1 code, this module:

* embeds the query via the public ``app.services.embedder.embed_batch`` helper
  (one-element batch — the B1 contract allows this fallback);
* opens the ``chunks`` table via the public ``lancedb_path`` on the indexer and
  runs a vector search there. Both the connection and the table handle are
  obtained through small helpers (``_open_db`` / ``_open_chunks_table``) so
  tests can swap them out without mocking ``lancedb`` directly.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import lancedb

from app.metrics import kb_retrieve_latency_seconds
from app.services import embedder as embedder_module
from app.services.indexer import LanceIndexer

log = logging.getLogger(__name__)

CHUNKS_TABLE = "chunks"
SCORE_THRESHOLD = 0.5
VECTOR_COLUMN = "vector"


@dataclass
class RetrievalResult:
    """A single hit from the index."""

    file_path: str
    chunk_index: int
    heading_path: list[str] = field(default_factory=list)
    text: str = ""
    score: float = 0.0
    chunk_id: str = ""
    # Character offsets of the chunk inside the source markdown. Used by the
    # frontend to highlight the cited passage inside the rendered document.
    start_offset: int = 0
    end_offset: int = 0

    def heading_str(self) -> str:
        return " > ".join(self.heading_path) if self.heading_path else ""


class RetrieverError(Exception):
    """Raised when retrieval fails irrecoverably."""


class Retriever:
    """Embed a query and run vector search over the chunks table."""

    def __init__(self, indexer: LanceIndexer) -> None:
        self.indexer = indexer

    # ------------------------------------------------------------------ hooks
    def _open_db(self) -> Any:
        return lancedb.connect(str(self.indexer.lancedb_path))

    def _open_chunks_table(self, db: Any | None = None):
        db = db if db is not None else self._open_db()
        try:
            return db.open_table(CHUNKS_TABLE)
        except (KeyError, FileNotFoundError, ValueError, OSError) as exc:
            raise RetrieverError(f"chunks table unavailable: {exc}") from exc

    # ------------------------------------------------------------------ embed
    def _embed_query_sync(self, query: str) -> list[float]:
        """Embed a single query string. Returns a plain list[float]."""
        if not query or not query.strip():
            raise RetrieverError("empty query")

        async def _run() -> Any:
            return await embedder_module.embed_batch([query])

        try:
            try:
                arr = asyncio.run(_run())
            except RuntimeError:
                # Already inside an event loop (FastAPI route). Run in a worker
                # thread so the retry sleeps don't block the loop.
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    fut = ex.submit(lambda: asyncio.run(_run()))
                    arr = fut.result()
        except Exception as exc:
            raise RetrieverError(f"query embedding failed: {exc}") from exc

        if arr is None or len(arr) == 0:
            raise RetrieverError("embedding returned empty result")
        return [float(x) for x in arr[0].tolist()]

    # ------------------------------------------------------------------ search
    @staticmethod
    def _distance_to_score(distance: float | None) -> float:
        """Convert LanceDB L2 distance to a [0, 1] similarity score."""
        if distance is None:
            return 0.0
        try:
            return float(1.0 / (1.0 + float(distance)))
        except (TypeError, ZeroDivisionError):
            return 0.0

    def _search_chunks(self, vector: Sequence[float], top_k: int) -> list[dict[str, Any]]:
        table = self._open_chunks_table()
        try:
            return (
                table.search(list(vector), vector_column_name=VECTOR_COLUMN)
                .limit(top_k)
                .to_list()
            )
        except Exception as exc:
            raise RetrieverError(f"vector search failed: {exc}") from exc

    @staticmethod
    def _coerce_row(row: dict[str, Any]) -> RetrievalResult:
        distance = row.pop("_distance", None)
        heading = row.get("heading_path", [])
        if isinstance(heading, str):
            try:
                heading = json.loads(heading)
            except (ValueError, TypeError):
                heading = []
        if not isinstance(heading, list):
            heading = []
        return RetrievalResult(
            file_path=str(row.get("file_path", "")),
            chunk_index=int(row.get("chunk_index", 0) or 0),
            heading_path=[str(h) for h in heading],
            text=str(row.get("text", "")),
            score=Retriever._distance_to_score(distance),
            chunk_id=str(row.get("id", "")),
            start_offset=int(row.get("start_offset", 0) or 0),
            end_offset=int(row.get("end_offset", 0) or 0),
        )

    def retrieve(self, query: str, top_k: int = 8) -> list[RetrievalResult]:
        """Embed the query and return the top-k hits as ``RetrievalResult``."""
        if top_k <= 0:
            return []
        start = time.perf_counter()
        try:
            vector = self._embed_query_sync(query)
            raw = self._search_chunks(vector, top_k)
        finally:
            kb_retrieve_latency_seconds.observe(time.perf_counter() - start)
        results = [self._coerce_row(r) for r in raw]
        # TODO: optional SCORE_THRESHOLD filter — disabled until we have
        # representative scores from a real gateway.
        return results

    # ------------------------------------------------------------------ format
    @staticmethod
    def format_context(results: Sequence[RetrievalResult]) -> str:
        """Render retrieval hits as text to inject under the user message.

        Format:
            [1] path/to/file.md#heading
            <chunk text>

            [2] ...

        The trailing instruction makes the LLM acknowledge empty / irrelevant
        results instead of inventing content.
        """
        if not results:
            return (
                "(no matching chunks were found in the vault for this query; "
                "if the answer is not in your general knowledge, tell the user "
                "you could not find relevant material rather than fabricating "
                "a response.)\n"
            )

        blocks: list[str] = []
        for idx, r in enumerate(results, start=1):
            heading = r.heading_str()
            ref = f"{r.file_path}#{heading}" if heading else r.file_path
            blocks.append(f"[{idx}] {ref}\n{r.text}")
        body = "\n\n".join(blocks)
        tail = (
            "\n\n---\n"
            "If the references above do not contain the information needed to "
            "answer the question, say so explicitly and do not invent facts."
        )
        return body + tail

    @staticmethod
    def references_payload(results: Sequence[RetrievalResult]) -> list[dict[str, Any]]:
        """Project hits into the structure Open WebUI's references event expects.

        The frontend additionally needs ``start_offset`` / ``end_offset`` (to
        locate the cited passage in the rendered document) and ``text`` (to
        show the quoted snippet without re-reading the file).
        """
        return [
            {
                "file_path": r.file_path,
                "heading": r.heading_str(),
                "chunk_id": r.chunk_id,
                "score": round(float(r.score), 4),
                "start_offset": r.start_offset,
                "end_offset": r.end_offset,
                "text": r.text,
            }
            for r in results
        ]


def format_context(results: Sequence[RetrievalResult]) -> str:
    """Module-level convenience so callers can ``from app.services.retriever import format_context``."""
    return Retriever.format_context(results)


__all__ = ["RetrievalResult", "Retriever", "RetrieverError", "format_context"]