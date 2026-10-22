import { fetchEventSource } from '@microsoft/fetch-event-source'

import type { Citation } from './types'

/**
 * Streaming chat against `POST /v1/chat/completions`.
 *
 * The wire format is a plain SSE stream:
 *
 *   data: {"choices":[{"delta":{"content":"增量文本"}}]}      ← any number of times
 *   data: {"type":"references","references":[…]}              ← once, at the very end
 *   data: [DONE]                                             ← end marker
 *
 * The `references` event arrives *after* every delta, so the UI can only
 * show the citation markers once the body has finished streaming.
 */
export interface StreamHandlers {
  /** Called for every content delta of the assistant answer. */
  onDelta: (text: string) => void
  /** Called once with the references of the answer. */
  onReferences: (refs: Citation[]) => void
  /** Called when the stream ended (normally or through an abort). */
  onDone: () => void
  /** Called when the stream failed. */
  onError: (err: Error) => void
}

/** The API lives at the origin root, not under the SPA's `/app` base path. */
const CHAT_URL = '/v1/chat/completions'

/** The gateway ignores the model name — it is only there for compatibility. */
const CHAT_MODEL = 'kb'

/** Turn a non-2xx response into a readable message. */
async function describeHttpError(response: Response): Promise<string> {
  const status = `${response.status} ${response.statusText}`.trim()
  let detail = ''
  try {
    const raw = await response.text()
    if (raw) {
      try {
        const body = JSON.parse(raw) as Record<string, unknown>
        const inner = body?.detail
        if (typeof inner === 'string') {
          detail = inner
        } else if (inner && typeof inner === 'object') {
          const message = (inner as { error?: { message?: unknown } })?.error?.message
          detail = typeof message === 'string' ? message : JSON.stringify(inner)
        }
      } catch {
        detail = raw.slice(0, 200)
      }
    }
  } catch {
    // Body already consumed or unreadable — keep the status line.
  }
  return detail ? `${status}：${detail}` : status
}

/** Extract the text of a chat-completion delta, or `null` when there is none. */
function readDelta(payload: Record<string, unknown>): string | null {
  const choices = payload['choices']
  if (!Array.isArray(choices) || choices.length === 0) {
    return null
  }
  const first = choices[0] as { delta?: { content?: unknown } } | undefined
  const content = first?.delta?.content
  if (typeof content !== 'string' || content.length === 0) {
    return null
  }
  return content
}

/**
 * How long we wait for late events after a `[DONE]` marker before we call the
 * stream finished.
 *
 * The backend forwards the gateway's stream verbatim — including the
 * gateway's own `data: [DONE]` — and only *afterwards* appends the
 * `references` event and a second `[DONE]`. Finishing on the first `[DONE]`
 * would therefore drop every citation. The real end of the response is the
 * close of the connection; this timer is only a safety net for a server that
 * keeps the connection open after its end marker.
 */
const DONE_GRACE_MS = 3000

/**
 * Stream one chat completion.
 *
 * Reconnection is deliberately disabled: `fetchEventSource` retries by
 * default when `onerror` returns, which would replay the already delivered
 * deltas and duplicate the answer. Throwing from `onerror` turns a failure
 * into a rejected promise instead of a retry.
 */
export async function streamChat(
  messages: { role: string; content: string }[],
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let finished = false
  let timer: ReturnType<typeof setTimeout> | null = null

  const finish = () => {
    if (finished) {
      return
    }
    finished = true
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
    handlers.onDone()
  }

  try {
    await fetchEventSource(CHAT_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      body: JSON.stringify({ model: CHAT_MODEL, messages, stream: true }),
      signal,
      // Without this the library aborts and *reconnects* when the tab is
      // hidden, which would replay the whole answer.
      openWhenHidden: true,
      onopen: async (response) => {
        if (!response.ok) {
          throw new Error(await describeHttpError(response))
        }
        const contentType = response.headers.get('content-type') ?? ''
        if (!contentType.includes('text/event-stream')) {
          throw new Error(`响应不是 SSE 流：${contentType || '缺少 content-type'}`)
        }
      },
      onmessage: (event) => {
        const data = event.data
        if (data === '[DONE]') {
          // End marker of the *current producer* — keep reading: the backend
          // appends its `references` event after the gateway's `[DONE]`.
          if (timer === null) {
            timer = setTimeout(finish, DONE_GRACE_MS)
          }
          return
        }
        let payload: unknown
        try {
          payload = JSON.parse(data)
        } catch {
          // A single malformed frame must not kill the whole stream.
          return
        }
        if (!payload || typeof payload !== 'object') {
          return
        }
        const json = payload as Record<string, unknown>
        if (json['type'] === 'references') {
          const refs = json['references']
          if (Array.isArray(refs)) {
            handlers.onReferences(refs as Citation[])
          }
          return
        }
        const delta = readDelta(json)
        if (delta !== null) {
          handlers.onDelta(delta)
        }
        // Any other shape is silently ignored — the gateway may send keep-alives.
      },
      onclose: () => {
        // The connection closed — the response is complete.
        finish()
      },
      onerror: (error) => {
        // Throwing disables the automatic retry: the answer must not be
        // delivered twice.
        throw error
      },
    })
    finish()
  } catch (error) {
    if (signal?.aborted) {
      // The user stopped the generation — not an error.
      finish()
      return
    }
    handlers.onError(
      error instanceof Error ? error : new Error(String(error)),
    )
  }
}
