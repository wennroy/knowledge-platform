"""Shared data models."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


class Chunk(BaseModel):
    id: str
    file_path: str
    file_hash: str
    chunk_index: int
    text: str
    heading_path: list[str] = Field(default_factory=list)
    start_offset: int
    end_offset: int


class ParseResult(BaseModel):
    markdown: str
    parser: str  # "markitdown" | "docling"
    ocr_used: bool = False


class IndexStatus(BaseModel):
    file_path: str
    file_hash: str
    #: sha256 of the original uploaded bytes. Distinct from ``file_hash``,
    #: which is the sha256 of the *parsed markdown*. The upload endpoint
    #: compares this to detect duplicate uploads.
    source_hash: str = ""
    chunk_count: int
    status: str  # "ok" | "failed" | "pending"
    updated_at: str
    error: str | None = None


class UploadResponse(BaseModel):
    id: str
    status: str
    parser: str
    chunks: int
    file_path: str | None = None
    error: str | None = None


class ReindexRequest(BaseModel):
    path: str


class ReconcileResponse(BaseModel):
    scanned: int
    indexed: int
    deleted: int
    errors: list[dict[str, Any]] = Field(default_factory=list)
