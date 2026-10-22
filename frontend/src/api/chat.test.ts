import { afterEach, describe, expect, it, vi } from 'vitest'

import { streamChat } from './chat'
import type { Citation } from './types'

/**
 * The tests drive the *real* `@microsoft/fetch-event-source` against a stubbed
 * `fetch`, so the retry/abort behaviour of the library is exercised for real
 * (and not faked away by a module mock).
 */

interface FetchInit {
  method?: string
  headers?: Record<string, string>
  body?: string
  signal?: AbortSignal
}

const originalWindowFetch = window.fetch

/** Wait for the given number of milliseconds. */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms)
  })
}

/** Install the stub as the global `fetch` — the library reads `window.fetch`. */
function installFetch(mock: (url: string, init: FetchInit) => Promise<Response>) {
  vi.stubGlobal('fetch', mock)
  ;(window as unknown as { fetch: unknown }).fetch = mock
}

afterEach(() => {
  vi.unstubAllGlobals()
  window.fetch = originalWindowFetch
})

/** A `Response` stand-in that carries an SSE body. */
function sseResponse(
  frames: string[],
  options: {
    status?: number
    statusText?: string
    contentType?: string
    bodyText?: string
  } = {},
): Response {
  const status = options.status ?? 200
  const text = options.bodyText ?? frames.map((f) => `data: ${f}\n\n`).join('')
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(text))
      controller.close()
    },
  })
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: options.statusText ?? 'OK',
    headers: {
      get: (name: string) =>
        name.toLowerCase() === 'content-type'
          ? (options.contentType ?? 'text/event-stream')
          : null,
    },
    body,
    text: async () => text,
  } as unknown as Response
}

/**
 * A response whose stream delivers one frame and then breaks.
 *
 * The `retry: 10` preamble shortens the retry interval of the SSE library to
 * 10ms — a retry (which must not happen) would therefore show up quickly.
 */
function brokenResponse(frame: string): Response {
  const encoder = new TextEncoder()
  let pulls = 0
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      pulls += 1
      if (pulls === 1) {
        controller.enqueue(
          encoder.encode(`retry: 10\n\ndata: ${frame}\n\n`),
        )
      } else {
        controller.error(new Error('connection reset'))
      }
    },
  })
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    headers: {
      get: (name: string) =>
        name.toLowerCase() === 'content-type' ? 'text/event-stream' : null,
    },
    body,
    text: async () => '',
  } as unknown as Response
}

/** Collect the calls of the stream handlers. */
function recorder() {
  const deltas: string[] = []
  const references: Citation[][] = []
  const errors: Error[] = []
  let done = 0
  return {
    deltas,
    references,
    errors,
    get done() {
      return done
    },
    handlers: {
      onDelta: (text: string) => {
        deltas.push(text)
      },
      onReferences: (refs: Citation[]) => {
        references.push(refs)
      },
      onDone: () => {
        done += 1
      },
      onError: (err: Error) => {
        errors.push(err)
      },
    },
  }
}

const deltaFrame = (content: string) =>
  JSON.stringify({ choices: [{ delta: { content } }] })

const referencesFrame = (refs: unknown[]) =>
  JSON.stringify({ type: 'references', references: refs })

const citation: Citation = {
  file_path: 'notes/a.md',
  heading: '标题',
  chunk_id: 'c1',
  score: 0.5,
  start_offset: 0,
  end_offset: 10,
  text: '引用内容',
}

describe('streamChat', () => {
  it('delivers every delta in order', async () => {
    installFetch(
      vi.fn(async (_url: string, _init: FetchInit) =>
        sseResponse([deltaFrame('你'), deltaFrame('好'), deltaFrame('！')]),
      ),
    )
    const rec = recorder()
    await streamChat([{ role: 'user', content: 'hi' }], rec.handlers)

    expect(rec.deltas).toEqual(['你', '好', '！'])
    expect(rec.done).toBe(1)
    expect(rec.errors).toHaveLength(0)
  })

  it('calls onReferences with the payload of the references event', async () => {
    installFetch(
      vi.fn(async (_url: string, _init: FetchInit) =>
        sseResponse([deltaFrame('答案'), referencesFrame([citation])]),
      ),
    )
    const rec = recorder()
    await streamChat([{ role: 'user', content: 'hi' }], rec.handlers)

    expect(rec.references).toHaveLength(1)
    expect(rec.references[0]).toEqual([citation])
    expect(rec.deltas).toEqual(['答案'])
  })

  it('calls onDone when the stream ends with [DONE]', async () => {
    installFetch(vi.fn(async (_url: string, _init: FetchInit) => sseResponse(['[DONE]'])))
    const rec = recorder()
    await streamChat([{ role: 'user', content: 'hi' }], rec.handlers)

    expect(rec.done).toBe(1)
    expect(rec.deltas).toHaveLength(0)
    expect(rec.errors).toHaveLength(0)
  })

  it('keeps the references that arrive after the first [DONE]', async () => {
    installFetch(
      vi.fn(async (_url: string, _init: FetchInit) =>
        sseResponse([deltaFrame('答案'), '[DONE]', referencesFrame([citation])]),
      ),
    )
    const rec = recorder()
    await streamChat([{ role: 'user', content: 'hi' }], rec.handlers)

    expect(rec.references).toHaveLength(1)
    expect(rec.done).toBe(1)
  })

  it('survives a malformed frame and keeps processing the following ones', async () => {
    installFetch(
      vi.fn(async (_url: string, _init: FetchInit) =>
        sseResponse(['{not json', deltaFrame('ok'), '[DONE]']),
      ),
    )
    const rec = recorder()
    await expect(
      streamChat([{ role: 'user', content: 'hi' }], rec.handlers),
    ).resolves.toBeUndefined()

    expect(rec.deltas).toEqual(['ok'])
    expect(rec.errors).toHaveLength(0)
    expect(rec.done).toBe(1)
  })

  it('ignores a frame that is valid JSON but not an object', async () => {
    installFetch(
      vi.fn(async (_url: string, _init: FetchInit) => sseResponse(['"a string"', deltaFrame('ok')])),
    )
    const rec = recorder()
    await streamChat([{ role: 'user', content: 'hi' }], rec.handlers)

    expect(rec.deltas).toEqual(['ok'])
    expect(rec.errors).toHaveLength(0)
  })

  it('ignores a delta frame without any content', async () => {
    installFetch(
      vi.fn(async (_url: string, _init: FetchInit) =>
        sseResponse([
          JSON.stringify({ choices: [] }),
          JSON.stringify({ choices: [{ delta: {} }] }),
          JSON.stringify({ choices: [{ delta: { content: '' } }] }),
          deltaFrame('ok'),
        ]),
      ),
    )
    const rec = recorder()
    await streamChat([{ role: 'user', content: 'hi' }], rec.handlers)

    expect(rec.deltas).toEqual(['ok'])
  })

  it('resolves (and does not error) when the stream is aborted', async () => {
    const controller = new AbortController()
    const encoder = new TextEncoder()
    const body = new ReadableStream<Uint8Array>({
      start(streamController) {
        streamController.enqueue(encoder.encode(`data: ${deltaFrame('部分')}\n\n`))
        // never closed — the abort below ends the request
      },
    })
    installFetch(
      vi.fn(async (_url: string, _init: FetchInit) =>
        ({
          ok: true,
          status: 200,
          statusText: 'OK',
          headers: {
            get: (name: string) =>
              name.toLowerCase() === 'content-type' ? 'text/event-stream' : null,
          },
          body,
          text: async () => '',
        }) as unknown as Response,
      ),
    )
    const rec = recorder()
    const promise = streamChat(
      [{ role: 'user', content: 'hi' }],
      rec.handlers,
      controller.signal,
    )
    controller.abort()
    await expect(promise).resolves.toBeUndefined()

    expect(rec.errors).toHaveLength(0)
    expect(rec.done).toBe(1)
  })

  it('does not reconnect after an aborted stream', async () => {
    const controller = new AbortController()
    const fetchMock = vi.fn(async (_url: string, _init: FetchInit) => sseResponse([deltaFrame('x')]))
    installFetch(fetchMock)
    const rec = recorder()
    const promise = streamChat(
      [{ role: 'user', content: 'hi' }],
      rec.handlers,
      controller.signal,
    )
    controller.abort()
    await promise

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('does not reconnect when the request fails', async () => {
    const fetchMock = vi.fn(async (_url: string, _init: FetchInit) => {
      throw new Error('network down')
    })
    installFetch(fetchMock)
    const rec = recorder()
    await expect(
      streamChat([{ role: 'user', content: 'hi' }], rec.handlers),
    ).resolves.toBeUndefined()

    // The SSE library would reconnect after one second — a retry would replay
    // the already delivered answer, so there must be only a single request.
    await sleep(1200)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(rec.errors).toHaveLength(1)
    expect(rec.errors[0].message).toBe('network down')
    expect(rec.done).toBe(0)
  })

  it('does not reconnect when the stream breaks mid-way', async () => {
    const fetchMock = vi.fn(async (_url: string, _init: FetchInit) => brokenResponse(deltaFrame('partial')))
    installFetch(fetchMock)
    const rec = recorder()
    await streamChat([{ role: 'user', content: 'hi' }], rec.handlers)

    // The stream asked for a 10ms retry interval — give a (forbidden) retry
    // the chance to happen.
    await sleep(100)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(rec.deltas).toEqual(['partial'])
    expect(rec.errors).toHaveLength(1)
    expect(rec.done).toBe(0)
  })

  it('reports a non-2xx answer of the gateway as an error', async () => {
    const fetchMock = vi.fn(async (_url: string, _init: FetchInit) =>
      sseResponse([], {
        status: 503,
        statusText: 'Service Unavailable',
        bodyText: JSON.stringify({ detail: '服务暂不可用' }),
      }),
    )
    installFetch(fetchMock)
    const rec = recorder()
    await expect(
      streamChat([{ role: 'user', content: 'hi' }], rec.handlers),
    ).resolves.toBeUndefined()

    expect(rec.errors).toHaveLength(1)
    expect(rec.errors[0].message).toContain('503')
    expect(rec.errors[0].message).toContain('服务暂不可用')
    expect(rec.done).toBe(0)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('reports a nested error detail of the gateway', async () => {
    installFetch(
      vi.fn(async (_url: string, _init: FetchInit) =>
        sseResponse([], {
          status: 401,
          statusText: 'Unauthorized',
          bodyText: JSON.stringify({ detail: { error: { message: '未授权' } } }),
        }),
      ),
    )
    const rec = recorder()
    await streamChat([{ role: 'user', content: 'hi' }], rec.handlers)

    expect(rec.errors).toHaveLength(1)
    expect(rec.errors[0].message).toContain('未授权')
  })

  it('reports a response that is not an SSE stream', async () => {
    installFetch(
      vi.fn(async (_url: string, _init: FetchInit) =>
        sseResponse([], { contentType: 'application/json', bodyText: '{}' }),
      ),
    )
    const rec = recorder()
    await streamChat([{ role: 'user', content: 'hi' }], rec.handlers)

    expect(rec.errors).toHaveLength(1)
    expect(rec.errors[0].message).toContain('SSE')
    expect(rec.errors[0].message).toContain('application/json')
    expect(rec.done).toBe(0)
  })

  it('posts the chat completion to the gateway as SSE', async () => {
    const fetchMock = vi.fn(async (_url: string, _init: FetchInit) => sseResponse(['[DONE]']))
    installFetch(fetchMock)
    const rec = recorder()
    const messages = [{ role: 'user', content: '你好' }]
    await streamChat(messages, rec.handlers)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/v1/chat/completions')
    expect(init.method).toBe('POST')
    expect(init.headers?.['Content-Type']).toBe('application/json')
    expect(JSON.parse(init.body ?? '{}')).toEqual({
      model: 'kb',
      messages,
      stream: true,
    })
  })
})
