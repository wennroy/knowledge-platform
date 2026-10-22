import { useCallback, useEffect, useRef, useState } from 'react'

import { streamChat } from '../api/chat'
import type { ChatMessage, Citation } from '../api/types'

/**
 * The chat state of the right-hand panel.
 *
 * One answer runs at a time: sending again aborts the previous stream, and
 * every late event of an aborted stream is ignored, so two streams can never
 * write into the same state.
 */
export interface ChatState {
  /** All messages, oldest first. */
  messages: ChatMessage[]
  /** Error message per assistant message id. */
  messageErrors: Record<string, string>
  /** True while an answer is streaming in. */
  isStreaming: boolean
  /** Sends a question and streams the answer. */
  sendMessage: (text: string) => void
  /** Aborts the running answer. */
  stopStreaming: () => void
}

/**
 * Map an absolute file path onto its vault-relative form.
 *
 * The index stores absolute paths, so the `references` event may carry an
 * absolute `file_path`. The document tree is the only place that knows the
 * vault-relative form, so the absolute path is mapped back onto it.
 */
function toVaultPath(filePath: string, knownPaths: string[]): string {
  const raw = filePath.trim()
  if (!raw.startsWith('/')) {
    return raw
  }
  for (const candidate of knownPaths) {
    if (raw === candidate || raw.endsWith(`/${candidate}`)) {
      return candidate
    }
  }
  return raw
}

/**
 * The chat panel state: the message list and the SSE stream behind it.
 *
 * @param vaultPaths vault-relative paths of every file in the tree
 */
export function useChat(vaultPaths: string[]): ChatState {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [messageErrors, setMessageErrors] = useState<Record<string, string>>({})

  /** The controller of the running stream — at most one at a time. */
  const activeControllerRef = useRef<AbortController | null>(null)
  const messageIdRef = useRef(0)
  const vaultPathsRef = useRef<string[]>([])

  useEffect(() => {
    vaultPathsRef.current = vaultPaths
  }, [vaultPaths])

  /** Stop the running stream (if any) and clear the streaming state. */
  const abortStream = useCallback(() => {
    const controller = activeControllerRef.current
    if (!controller) {
      return
    }
    activeControllerRef.current = null
    controller.abort()
    setIsStreaming(false)
    setMessages((previous) =>
      previous.map((message) =>
        message.streaming ? { ...message, streaming: false } : message,
      ),
    )
  }, [])

  const stopStreaming = useCallback(() => {
    abortStream()
  }, [abortStream])

  /**
   * Send a question and stream the answer.
   *
   * The assistant message is appended empty and filled while the SSE stream
   * runs; the `references` event arrives after the last delta and fills the
   * citations.
   */
  const sendMessage = useCallback(
    (text: string) => {
      const trimmed = text.trim()
      if (!trimmed) {
        return
      }

      // Only one stream at a time — abort the previous one.
      abortStream()

      const controller = new AbortController()
      activeControllerRef.current = controller

      messageIdRef.current += 1
      const userId = `m-${messageIdRef.current}`
      messageIdRef.current += 1
      const assistantId = `m-${messageIdRef.current}`

      const history = [
        ...messages
          .filter(
            (message) =>
              (message.role === 'user' || message.role === 'assistant') &&
              message.content.length > 0,
          )
          .map((message) => ({ role: message.role, content: message.content })),
        { role: 'user', content: trimmed },
      ]

      setMessages((previous) => [
        ...previous,
        { id: userId, role: 'user', content: trimmed },
        { id: assistantId, role: 'assistant', content: '', streaming: true },
      ])
      setMessageErrors((previous) => {
        const next = { ...previous }
        delete next[assistantId]
        return next
      })
      setIsStreaming(true)

      /** Ignore late events of a stream that is no longer the active one. */
      const isCurrent = () => activeControllerRef.current === controller

      const finishMessage = () => {
        activeControllerRef.current = null
        setIsStreaming(false)
        setMessages((previous) =>
          previous.map((message) =>
            message.id === assistantId
              ? { ...message, streaming: false }
              : message,
          ),
        )
      }

      void streamChat(
        history,
        {
          onDelta: (chunk) => {
            if (!isCurrent()) {
              return
            }
            setMessages((previous) =>
              previous.map((message) =>
                message.id === assistantId
                  ? { ...message, content: message.content + chunk }
                  : message,
              ),
            )
          },
          onReferences: (references: Citation[]) => {
            if (!isCurrent()) {
              return
            }
            const citations = references.map((reference) => ({
              ...reference,
              file_path: toVaultPath(reference.file_path, vaultPathsRef.current),
            }))
            setMessages((previous) =>
              previous.map((message) =>
                message.id === assistantId ? { ...message, citations } : message,
              ),
            )
          },
          onDone: () => {
            if (!isCurrent()) {
              return
            }
            finishMessage()
          },
          onError: (error) => {
            if (!isCurrent()) {
              return
            }
            finishMessage()
            setMessageErrors((previous) => ({
              ...previous,
              [assistantId]: error.message,
            }))
          },
        },
        controller.signal,
      )
    },
    [abortStream, messages],
  )

  // Unmounting aborts a running stream.
  useEffect(
    () => () => {
      activeControllerRef.current?.abort()
    },
    [],
  )

  return { messages, messageErrors, isStreaming, sendMessage, stopStreaming }
}
