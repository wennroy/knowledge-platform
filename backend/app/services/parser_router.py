"""Parser router: MarkItDown by default, Docling fallback for scanned PDFs."""
from __future__ import annotations

import logging
import traceback
from pathlib import Path

from app.models import ParseResult

log = logging.getLogger(__name__)

# Threshold below which MarkItDown output is considered empty / scanned-image.
SCAN_FALLBACK_CHARS = 200


class ParserError(Exception):
    """Raised when neither MarkItDown nor Docling can produce useful text."""


def _strip_markdown(text: str) -> str:
    """Trim whitespace and drop very short blocks before measuring."""
    if not text:
        return ""
    return text.strip()


def _docling_convert(file_path: Path) -> str:
    """Use Docling's DocumentConverter to OCR + extract text."""
    from docling.document_converter import DocumentConverter  # type: ignore

    converter = DocumentConverter()
    result = converter.convert(str(file_path))
    # Docling returns a DoclingDocument; .export_to_markdown() gives us text.
    try:
        return result.document.export_to_markdown()
    except Exception:  # pragma: no cover - depends on docling internals
        return str(getattr(result.document, "text", ""))


def parse(file_path: Path) -> ParseResult:
    """Parse a file. Returns markdown + parser used.

    Default path: MarkItDown. If output is too short, fallback to Docling.
    Raises ParserError if both paths fail.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise ParserError(f"file not found: {file_path}")

    # 1) MarkItDown default path
    try:
        from markitdown import MarkItDown  # type: ignore

        md = MarkItDown().convert(str(file_path))
        text = _strip_markdown(getattr(md, "text_content", "") or "")
        if len(text) >= SCAN_FALLBACK_CHARS:
            return ParseResult(markdown=text, parser="markitdown", ocr_used=False)
        markitdown_text = text
    except Exception as exc:  # noqa: BLE001 - capture and continue
        log.warning("markitdown failed for %s: %s", file_path, exc)
        markitdown_text = ""

    # 2) Docling fallback (scanned / poor MarkItDown output)
    try:
        text = _docling_convert(file_path)
        text = _strip_markdown(text)
        if not text:
            raise ParserError(
                f"docling produced empty output for {file_path} "
                f"(markitdown was {len(markitdown_text)} chars)"
            )
        return ParseResult(markdown=text, parser="docling", ocr_used=True)
    except Exception as exc:  # noqa: BLE001
        msg = f"both parsers failed for {file_path}: markitdown={markitdown_text!r}; docling={exc}"
        log.error("%s\n%s", msg, traceback.format_exc())
        raise ParserError(msg) from exc
