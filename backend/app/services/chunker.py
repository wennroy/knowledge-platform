"""Markdown chunker: paragraph-first with tiktoken-based hard split."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

import tiktoken
from markdown_it import MarkdownIt

from app.config import get_settings

_ENCODING = tiktoken.get_encoding("cl100k_base")
_MD = MarkdownIt("commonmark", {"html": False}).enable("heading")


@dataclass
class _Segment:
    heading_path: list[str]
    text: str
    start_offset: int
    end_offset: int


def _token_len(text: str) -> int:
    return len(_ENCODING.encode(text))


def _iter_paragraphs(markdown: str) -> list[_Segment]:
    """Yield paragraphs tagged with their heading context.

    Walks the markdown-it token stream in order, tracking the active heading
    path so each emitted segment knows its outline context.
    """
    tokens = _MD.parse(markdown)
    segments: list[_Segment] = []
    heading_path: list[str] = []

    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok.type == "heading_open":
            level = int(tok.tag.lstrip("h") or "1")
            # next non-close token is the inline containing the heading text
            title = ""
            j = i + 1
            while j < n and tokens[j].type == "heading_open":
                j += 1
            if j < n and tokens[j].type == "inline":
                title = tokens[j].content
            heading_path = heading_path[: max(level - 1, 0)]
            heading_path.append(title)
            # skip past heading_close
            while i < n and tokens[i].type != "heading_close":
                i += 1
            i += 1
            continue

        if tok.type in ("paragraph_open", "fence", "code_block"):
            inline_idx = i + 1
            text = ""
            if tok.type == "paragraph_open" and inline_idx < n and tokens[inline_idx].type == "inline":
                text = tokens[inline_idx].content
            else:
                text = tok.content
            if tok.map is not None and text.strip():
                start, end = tok.map
                segments.append(
                    _Segment(
                        heading_path=list(heading_path),
                        text=text,
                        start_offset=start,
                        end_offset=end,
                    )
                )
            # advance past paragraph_close / matching close
            depth = 1
            i += 1
            close_type = {
                "paragraph_open": "paragraph_close",
                "fence": "fence",
                "code_block": "code_block",
            }[tok.type]
            while i < n and depth > 0:
                if tokens[i].type == tok.type:
                    depth += 1
                elif tokens[i].type == close_type:
                    depth -= 1
                i += 1
            continue

        i += 1

    return segments


def _hard_split(text: str, max_tokens: int, overlap: int) -> list[tuple[str, int, int]]:
    """Token-level hard split with overlap. Returns (text, start_char, end_char)."""
    if not text:
        return []
    ids = _ENCODING.encode(text)
    if len(ids) <= max_tokens:
        return [(text, 0, len(text))]

    chunks: list[tuple[str, int, int]] = []
    step = max(1, max_tokens - overlap)
    i = 0
    n = len(ids)
    while i < n:
        window = ids[i : i + max_tokens]
        chunk_text = _ENCODING.decode(window)
        # Approximate character offset by searching for the chunk in the
        # remaining text. Good enough for indexing purposes.
        remaining = text[i * 4 :] if i > 0 else text  # rough heuristic
        idx = remaining.find(chunk_text[:32])
        if idx == -1 and len(chunk_text) >= 32:
            idx = 0
        start_char = (i * 4) + idx if i > 0 else idx
        end_char = start_char + len(chunk_text)
        chunks.append((chunk_text, start_char, end_char))
        if i + max_tokens >= n:
            break
        i += step
    return chunks


def split(markdown: str, source_path: str, file_hash: str) -> list[dict]:
    """Split a markdown document into chunks ready for embedding."""
    s = get_settings()
    max_tokens = max(1, s.CHUNK_TOKENS)
    overlap = max(0, min(s.CHUNK_OVERLAP, max_tokens - 1))

    segments = _iter_paragraphs(markdown)
    if not segments:
        return []

    out: list[dict] = []
    chunk_index = 0
    buf_text: list[str] = []
    buf_heading: list[str] = []
    buf_start: int | None = None
    buf_token_count = 0

    def flush() -> None:
        nonlocal chunk_index, buf_text, buf_heading, buf_start, buf_token_count
        if not buf_text or buf_start is None:
            return
        joined = "\n\n".join(buf_text)
        heading = list(buf_heading)
        for sub_text, sub_start, sub_end in _hard_split(joined, max_tokens, overlap):
            out.append(
                {
                    "id": str(uuid.uuid4()),
                    "file_path": source_path,
                    "file_hash": file_hash,
                    "chunk_index": chunk_index,
                    "text": sub_text,
                    "heading_path": heading,
                    "start_offset": buf_start + sub_start,
                    "end_offset": buf_start + sub_end,
                }
            )
            chunk_index += 1
        buf_text = []
        buf_heading = []
        buf_start = None
        buf_token_count = 0

    for seg in segments:
        seg_tokens = _token_len(seg.text)
        if seg_tokens > max_tokens:
            flush()
            for sub_text, sub_start, sub_end in _hard_split(seg.text, max_tokens, overlap):
                out.append(
                    {
                        "id": str(uuid.uuid4()),
                        "file_path": source_path,
                        "file_hash": file_hash,
                        "chunk_index": chunk_index,
                        "text": sub_text,
                        "heading_path": list(seg.heading_path),
                        "start_offset": seg.start_offset + sub_start,
                        "end_offset": seg.start_offset + sub_end,
                    }
                )
                chunk_index += 1
            continue
        if buf_token_count + seg_tokens > max_tokens and buf_text:
            flush()
        if buf_start is None:
            buf_start = seg.start_offset
        buf_text.append(seg.text)
        if seg.heading_path:
            buf_heading = list(seg.heading_path)
        buf_token_count += seg_tokens

    flush()
    return out
