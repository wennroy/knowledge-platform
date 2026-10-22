"""Grep-style full-text search over the vault markdown files.

The unified frontend needs a quick global search in the top bar. This is a
deliberately simple substring scan (case-insensitive) rather than a semantic
search — the RAG pipeline already covers semantic lookup, and the top-bar
search must feel instant.

Contract:

    GET /v1/search?q=xxx
    {
      "query": "xxx",
      "results": [
        {
          "file_path": "team/api-design.md",
          "title": "API 设计原则",
          "matches": [{"line": 12, "text": "使用 Bearer token"}]
        }
      ]
    }

Line numbers are 1-based and relative to the document *body* (the markdown
with the frontmatter block stripped) — that is exactly what the frontend
renders in the reader pane.
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Query

from app.config import get_settings
from app.services.vault import list_vault, read_md

router = APIRouter(prefix="/v1", tags=["search"])

# At most this many files are returned.
MAX_RESULTS = 50
# At most this many matching lines per file.
MAX_MATCHES_PER_FILE = 5
# Matched lines are truncated to this many characters.
MAX_LINE_CHARS = 200

_H1_RE = re.compile(r"^#\s+(.+?)\s*$")


def _first_heading(body: str) -> str:
    """First ATX H1 in the body, or an empty string."""
    for line in body.splitlines():
        match = _H1_RE.match(line)
        if match:
            return match.group(1).strip()
    return ""


def _title_for(meta: dict[str, Any], body: str, fallback: str) -> str:
    """Best-effort document title: frontmatter > first H1 > file stem."""
    raw = meta.get("title")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    heading = _first_heading(body)
    if heading:
        return heading
    return fallback


@router.get("/search")
async def search(q: str = Query("", description="case-insensitive substring")) -> dict:
    """Search every markdown file in the vault for ``q``."""
    query = q.strip()
    if not query:
        return {"query": "", "results": []}

    base = get_settings().vault_path()
    needle = query.lower()
    results: list[dict[str, Any]] = []

    for path in list_vault(base):
        if len(results) >= MAX_RESULTS:
            break
        try:
            rel = path.relative_to(base).as_posix()
        except ValueError:  # pragma: no cover - list_vault always yields under base
            continue

        fm = read_md(rel, vault_path=base)
        body = fm.body or ""

        matches: list[dict[str, Any]] = []
        for lineno, line in enumerate(body.splitlines(), start=1):
            if needle in line.lower():
                matches.append({"line": lineno, "text": line.rstrip()[:MAX_LINE_CHARS]})
                if len(matches) >= MAX_MATCHES_PER_FILE:
                    break
        if not matches:
            continue

        results.append(
            {
                "file_path": rel,
                "title": _title_for(fm.meta or {}, body, path.stem),
                "matches": matches,
            }
        )

    return {"query": query, "results": results}
