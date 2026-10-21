"""parser_router tests.

We don't have real PDF fixtures in the PoC; instead we monkeypatch the
MarkItDown + Docling backends so the routing logic is exercised end-to-end.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.services import parser_router


class _FakeResult:
    def __init__(self, text: str) -> None:
        self.text_content = text


class _FakeMarkItDown:
    def __init__(self, text: str) -> None:
        self._text = text

    def convert(self, path: str):  # noqa: ARG002
        return _FakeResult(self._text)


class _FakeDoclingDoc:
    def __init__(self, text: str) -> None:
        self._text = text

    def export_to_markdown(self) -> str:
        return self._text


class _FakeDoclingConv:
    def __init__(self, text: str) -> None:
        self._text = text

    def convert(self, path: str):  # noqa: ARG002
        return MagicMock(document=_FakeDoclingDoc(self._text))


@pytest.fixture
def fake_markitdown(monkeypatch):
    def _install(text: str):
        monkeypatch.setattr(parser_router, "_docling_convert", lambda p: text)
        monkeypatch.setattr(
            "markitdown.MarkItDown", lambda *a, **k: _FakeMarkItDown(text)
        )

    return _install


def test_parse_uses_markitdown_when_output_is_substantial(
    tmp_path: Path, monkeypatch
):
    big = "Hello world. " * 50  # > 200 chars
    monkeypatch.setattr(parser_router, "_docling_convert", lambda p: "should not run")
    monkeypatch.setattr(
        "markitdown.MarkItDown", lambda *a, **k: _FakeMarkItDown(big)
    )

    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-fake")
    result = parser_router.parse(f)
    assert result.parser == "markitdown"
    assert not result.ocr_used
    assert "Hello world" in result.markdown


def test_parse_falls_back_to_docling_for_scanned_pdf(tmp_path: Path, monkeypatch):
    empty = ""  # MarkItDown produces nothing → scanned
    docling_text = "Recognized OCR text " * 30
    monkeypatch.setattr(parser_router, "_docling_convert", lambda p: docling_text)
    monkeypatch.setattr(
        "markitdown.MarkItDown", lambda *a, **k: _FakeMarkItDown(empty)
    )

    f = tmp_path / "scanned.pdf"
    f.write_bytes(b"%PDF-scanned")
    result = parser_router.parse(f)
    assert result.parser == "docling"
    assert result.ocr_used is True
    assert "Recognized OCR" in result.markdown


def test_parse_raises_when_both_fail(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(parser_router, "_docling_convert", lambda p: "")
    monkeypatch.setattr(
        "markitdown.MarkItDown", lambda *a, **k: _FakeMarkItDown("")
    )

    f = tmp_path / "broken.pdf"
    f.write_bytes(b"%PDF-broken")
    with pytest.raises(parser_router.ParserError):
        parser_router.parse(f)


def test_parse_missing_file(tmp_path: Path):
    with pytest.raises(parser_router.ParserError):
        parser_router.parse(tmp_path / "nope.pdf")
