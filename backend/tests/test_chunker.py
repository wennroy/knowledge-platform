"""chunker tests covering Chinese text, long lines, and code blocks."""
from __future__ import annotations

from app.services.chunker import split


def _count(chunks):
    return len(chunks)


def test_split_empty_returns_empty_list():
    assert split("", "x.md", "h") == []


def test_split_chinese_text_yields_chunks():
    md = "## 第一节\n" + ("这是中文段落。" * 80) + "\n\n## 第二节\n" + ("更多内容。" * 40)
    chunks = split(md, "x.md", "abc")
    assert _count(chunks) > 0
    # First chunk should reference the first heading path.
    assert "第一节" in chunks[0]["heading_path"]


def test_split_oversized_line_is_hard_split():
    # Single huge paragraph well over 64 tokens.
    long_text = "abcdef " * 200  # ~200*1 token each -> >>64 tokens
    md = f"# Long\n\n{long_text}"
    chunks = split(md, "long.md", "h1")
    assert _count(chunks) >= 2
    # Each chunk must be <= 64 tokens (hard cap enforced).
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")
    for c in chunks:
        assert len(enc.encode(c["text"])) <= 64


def test_split_code_block_kept_intact_when_possible():
    md = (
        "# Title\n\n"
        "```python\n"
        "def hello():\n    print('hi')\n"
        "```\n\n"
        "Some prose after the code."
    )
    chunks = split(md, "code.md", "h2")
    texts = [c["text"] for c in chunks]
    assert any("def hello" in t for t in texts)


def test_split_propagates_file_path_and_hash():
    md = "Hello world. " * 30
    chunks = split(md, "/vault/team/foo.md", "deadbeef")
    assert all(c["file_path"] == "/vault/team/foo.md" for c in chunks)
    assert all(c["file_hash"] == "deadbeef" for c in chunks)
    assert all("id" in c and c["chunk_index"] >= 0 for c in chunks)
