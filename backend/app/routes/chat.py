"""OpenAI-compatible chat completions endpoint with RAG + SSE streaming.

The endpoint:

* accepts the standard OpenAI ``/v1/chat/completions`` request body
  (``model``, ``messages``, ``stream``, ``temperature``);
* pulls the most recent user message, retrieves supporting chunks from the
  vault via :class:`app.services.retriever.Retriever`, and re-injects them
  under the user's turn;
* forwards the response from the gateway verbatim, then appends a single
  ``{"type":"references", ...}`` event followed by ``data: [DONE]`` so
  Open WebUI can render the citations.

Non-stream responses are returned as a single JSON object that mirrors the
OpenAI shape and includes the references as markdown links appended to the
assistant message.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import get_settings
from app.deps import get_logger
from app.metrics import kb_chat_completions_total
from app.services.indexer import LanceIndexer
from app.services.prompts import SYSTEM_PROMPT, build_user_message
from app.services.retriever import RetrievalResult, Retriever, RetrieverError

log = get_logger("routes.chat")

router = APIRouter(prefix="/v1", tags=["chat"])

CHAT_PATH = "/chat/completions"
DEFAULT_TEMPERATURE = 0.3
GATEWAY_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=60.0, pool=5.0)


# ---------------------------------------------------------------- deps
def _get_indexer() -> LanceIndexer:
    """Return a LanceIndexer for the request.

    Kept local to this module so the B1 ``app.deps`` surface stays untouched.
    """
    return LanceIndexer()


def _get_retriever(indexer: LanceIndexer | None = None) -> Retriever:
    return Retriever(indexer or _get_indexer())


# ---------------------------------------------------------------- helpers
def _last_user_message(messages: list[dict[str, Any]]) -> str | None:
    """Walk the messages tail to last and return the user content, if any."""
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, list):
            # OpenAI allows content as a list of typed parts; concatenate text.
            parts: list[str] = []
            for p in content:
                if isinstance(p, dict) and isinstance(p.get("text"), str):
                    parts.append(p["text"])
                elif isinstance(p, str):
                    parts.append(p)
            content = "\n".join(parts)
        if isinstance(content, str) and content.strip():
            return content
    return None


def _references_event(results: list[RetrievalResult]) -> str:
    payload = {"type": "references", "references": Retriever.references_payload(results)}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _references_markdown(results: list[RetrievalResult]) -> str:
    """Append references as a markdown block to the assistant content."""
    if not results:
        return ""
    lines = ["", "", "---", "References:"]
    for idx, r in enumerate(results, start=1):
        heading = r.heading_str()
        ref = f"{r.file_path}#{heading}" if heading else r.file_path
        lines.append(f"[{idx}] {ref} (score={r.score:.2f})")
    return "\n".join(lines)


def _error_payload(message: str, err_type: str = "server_error") -> dict[str, Any]:
    return {
        "error": {"message": message, "type": err_type, "param": None, "code": None}
    }


# ---------------------------------------------------------------- streaming
async def _stream_gateway(
    client: httpx.AsyncClient,
    payload: dict[str, Any],
    results: list[RetrievalResult],
) -> AsyncIterator[bytes]:
    """Forward SSE bytes from the gateway, then append the references tail.

    On upstream errors we yield an OpenAI-style error event followed by
    ``[DONE]`` rather than raising — streaming responses have already
    committed the 200 / text-event-stream headers by the time the generator
    runs, so a non-200 status would never reach the client.
    """
    s = get_settings()
    url = f"{s.GATEWAY_BASE_URL.rstrip('/')}{CHAT_PATH}"
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if s.GATEWAY_API_KEY:
        headers["Authorization"] = f"Bearer {s.GATEWAY_API_KEY}"

    request = client.build_request(
        "POST", url, json=payload, headers=headers, timeout=GATEWAY_TIMEOUT
    )
    try:
        response = await client.send(request, stream=True)
    except httpx.TimeoutException as exc:
        log.warning("gateway chat completions timeout: %s", exc)
        yield _sse_error_event(f"gateway timeout: {exc}", err_type="upstream_timeout")
        yield b"data: [DONE]\n\n"
        return
    except httpx.HTTPError as exc:
        log.warning("gateway chat completions http error: %s", exc)
        yield _sse_error_event(f"gateway error: {exc}", err_type="upstream_error")
        yield b"data: [DONE]\n\n"
        return

    try:
        if response.status_code >= 400:
            body = await response.aread()
            log.warning(
                "gateway chat completions failed: %s %s",
                response.status_code,
                body[:200].decode("utf-8", errors="replace"),
            )
            yield _sse_error_event(
                f"gateway returned {response.status_code}",
                err_type="upstream_error",
            )
            yield b"data: [DONE]\n\n"
            return
        async for chunk in response.aiter_bytes():
            if chunk:
                yield chunk
    finally:
        await response.aclose()

    # Append our custom references event + [DONE] marker.
    yield _references_event(results).encode("utf-8")
    yield b"data: [DONE]\n\n"


def _sse_error_event(message: str, err_type: str) -> bytes:
    payload = {"error": {"message": message, "type": err_type, "param": None, "code": None}}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


async def _stream_response(
    payload: dict[str, Any], results: list[RetrievalResult]
) -> StreamingResponse:
    async def gen() -> AsyncIterator[bytes]:
        try:
            async with httpx.AsyncClient(timeout=GATEWAY_TIMEOUT) as client:
                async for chunk in _stream_gateway(client, payload, results):
                    yield chunk
        except httpx.HTTPError as exc:
            log.exception("stream generator hit unexpected http error")
            yield _sse_error_event(f"upstream error: {exc}", err_type="upstream_error")
            yield b"data: [DONE]\n\n"
        except Exception as exc:
            log.exception("stream generator crashed")
            yield _sse_error_event(f"internal error: {exc}", err_type="internal_error")
            yield b"data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# ---------------------------------------------------------------- non-stream
async def _non_stream_response(
    payload: dict[str, Any], results: list[RetrievalResult]
) -> JSONResponse:
    s = get_settings()
    url = f"{s.GATEWAY_BASE_URL.rstrip('/')}{CHAT_PATH}"
    headers = {"Content-Type": "application/json"}
    if s.GATEWAY_API_KEY:
        headers["Authorization"] = f"Bearer {s.GATEWAY_API_KEY}"

    payload_non_stream = dict(payload)
    payload_non_stream["stream"] = False

    async with httpx.AsyncClient(timeout=GATEWAY_TIMEOUT) as client:
        try:
            response = await client.post(url, json=payload_non_stream, headers=headers)
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=504,
                detail=_error_payload("gateway timeout", err_type="upstream_timeout"),
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=_error_payload(
                    f"gateway error: {exc}", err_type="upstream_error"
                ),
            ) from exc

    if response.status_code >= 400:
        log.warning(
            "gateway non-stream chat failed: %s %s",
            response.status_code,
            response.text[:200],
        )
        raise HTTPException(
            status_code=502,
            detail=_error_payload(
                f"gateway returned {response.status_code}",
                err_type="upstream_error",
            ),
        )

    try:
        body = response.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502,
            detail=_error_payload(
                "gateway returned non-JSON response", err_type="upstream_error"
            ),
        ) from exc

    # Inject references into the first assistant message as a markdown footer.
    refs_md = _references_markdown(results)
    try:
        choices = body.get("choices") or []
        if choices and refs_md:
            msg = choices[0].get("message") or {}
            content = msg.get("content", "")
            if isinstance(content, str):
                msg["content"] = content + refs_md
                choices[0]["message"] = msg
                body["choices"] = choices
    except Exception:
        log.exception("failed to inject references into non-stream body")

    return JSONResponse(body)


# ---------------------------------------------------------------- endpoint
@router.post("/chat/completions", response_model=None)
async def chat_completions(request: Request) -> StreamingResponse | JSONResponse:
    """OpenAI-compatible chat completions with vault-grounded references."""
    try:
        body_raw = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail=_error_payload("invalid JSON body", err_type="invalid_request"),
        ) from exc

    if not isinstance(body_raw, dict):
        raise HTTPException(
            status_code=400,
            detail=_error_payload("body must be a JSON object", err_type="invalid_request"),
        )

    messages = body_raw.get("messages") or []
    if not isinstance(messages, list) or not messages:
        raise HTTPException(
            status_code=400,
            detail=_error_payload("messages must be a non-empty list", err_type="invalid_request"),
        )

    stream = bool(body_raw.get("stream", False))
    try:
        temperature = float(body_raw.get("temperature", DEFAULT_TEMPERATURE))
    except (TypeError, ValueError):
        temperature = DEFAULT_TEMPERATURE

    user_query = _last_user_message(messages)
    if not user_query:
        raise HTTPException(
            status_code=400,
            detail=_error_payload(
                "no user message found in messages", err_type="invalid_request"
            ),
        )

    # Retrieval happens before the gateway call so failure surfaces as 500.
    s = get_settings()
    try:
        results = _get_retriever().retrieve(user_query, top_k=s.RETRIEVE_TOPK)
    except RetrieverError as exc:
        log.exception("retrieval failed")
        raise HTTPException(
            status_code=500,
            detail=_error_payload(f"retrieval failed: {exc}", err_type="retrieval_error"),
        ) from exc

    context_block = Retriever.format_context(results)
    augmented_user = build_user_message(user_query, context_block)

    upstream_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": augmented_user},
    ]

    upstream_payload: dict[str, Any] = {
        "model": s.CHAT_MODEL,
        "messages": upstream_messages,
        "stream": stream,
        "temperature": temperature,
    }

    log.info(
        "chat request: query_chars=%d hits=%d stream=%s",
        len(user_query),
        len(results),
        stream,
    )

    if stream:
        response = await _stream_response(upstream_payload, results)
        kb_chat_completions_total.labels(outcome="success").inc()
        return response
    response = await _non_stream_response(upstream_payload, results)
    kb_chat_completions_total.labels(outcome="success").inc()
    return response