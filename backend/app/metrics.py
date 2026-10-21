"""Prometheus metrics for the knowledge platform backend.

Single-process registry (no multiprocess). Other modules can import
``kb_index_files_total``, ``kb_retrieve_latency_seconds``, etc., to record
events. The default ``REGISTRY`` is exposed via ``/metrics`` on the FastAPI app.
"""
from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# Counter: number of vault files processed by the indexer, broken down by
# terminal status. Other modules increment this with the appropriate label.
kb_index_files_total = Counter(
    "kb_index_files_total",
    "Number of vault files processed by the indexer, by terminal status.",
    labelnames=("status",),  # one of: indexed, failed, skipped
)

# Histogram: end-to-end latency of the /v1/chat/completions retrieve-then-ask
# path (vector search + prompt assembly). Buckets aimed at sub-second to ~5s.
kb_retrieve_latency_seconds = Histogram(
    "kb_retrieve_latency_seconds",
    "Latency of retrieve-then-ask path (vector search + prompt assembly).",
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 5.0),
)

# Counter: chat completion outcomes from the gateway adapter.
kb_chat_completions_total = Counter(
    "kb_chat_completions_total",
    "Number of chat completion attempts, by outcome.",
    labelnames=("outcome",),  # one of: success, error, timeout
)

# Histogram: embedding-side latency (model call + batch overhead).
kb_embedding_latency_seconds = Histogram(
    "kb_embedding_latency_seconds",
    "Latency of embedding calls (per batch / per call).",
)

# Gauge: current row count of the LanceDB vector table.
# Updated at startup (after reconcile) and on every reconcile pass.
kb_lancedb_rows = Gauge(
    "kb_lancedb_rows",
    "Current row count of the LanceDB vector table.",
)


__all__ = [
    "CONTENT_TYPE_LATEST",
    "REGISTRY",
    "generate_latest",
    "kb_index_files_total",
    "kb_retrieve_latency_seconds",
    "kb_chat_completions_total",
    "kb_embedding_latency_seconds",
    "kb_lancedb_rows",
]
