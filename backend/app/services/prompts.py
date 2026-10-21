"""Prompt templates for the chat route.

Kept deliberately short and constant-only — easy to tweak, easy to test. The
contract is: ``system`` is the role message sent before the user turn, and
``build_user_message`` assembles the final user content by appending the
retrieval references under the original query.
"""
from __future__ import annotations

from collections.abc import Iterable

SYSTEM_PROMPT = (
    "You are a knowledge assistant backed by a private vault of documents. "
    "Answer the user's question using only the information in the references "
    "provided beneath the user's message.\n\n"
    "Rules:\n"
    "1. Every factual claim you make must cite the supporting reference using "
    "its bracketed index, e.g. [1], [2]. Include the vault file path and the "
    "section heading whenever you cite.\n"
    "2. If the references do not contain enough information, say so explicitly. "
    "Do not invent facts, file names, or section titles.\n"
    "3. Keep the answer focused and concise. Prefer quoting the exact relevant "
    "passage over paraphrasing when precision matters."
)


def build_user_message(original_query: str, references_block: str) -> str:
    """Combine the user query with the formatted retrieval context."""
    query = (original_query or "").strip()
    refs = (references_block or "").strip()
    if not refs:
        refs = "(no references available)"
    return f"{query}\n\n---\nReferences:\n{refs}"


def user_message_from_query_and_context(
    query: str, context_lines: Iterable[str]
) -> str:
    """Helper used by tests: turn a list of context lines into the user message."""
    return build_user_message(query, "\n".join(context_lines))


__all__ = ["SYSTEM_PROMPT", "build_user_message", "user_message_from_query_and_context"]