import { useEffect, useMemo, useRef, useState } from 'react'

import type { ChatMessage, Citation } from '../api/types'
import { Message } from './Message'
import { SourcesDrawer } from './SourcesDrawer'

export interface ChatPanelProps {
  /** Messages shown in the panel, oldest first. */
  messages: ChatMessage[]
  /** Called with the user's message when they press send. */
  onSend: (text: string) => void
  /** True while an answer is streaming in. */
  isStreaming: boolean
  /** Called when the user stops the running answer. */
  onStop: () => void
  /** Called when a citation marker is clicked. */
  onCitationJump?: (citation: Citation) => void
  /** Error of a message, keyed by message id. */
  messageErrors?: Record<string, string>
}

/**
 * Right-hand column: the AI question-and-answer panel.
 *
 * The answer streams in through `onSend` / `isStreaming`; the citation markers
 * of the last answer are also listed in the sources drawer.
 */
export function ChatPanel({
  messages,
  onSend,
  isStreaming,
  onStop,
  onCitationJump,
  messageErrors,
}: ChatPanelProps) {
  const [draft, setDraft] = useState('')
  const [sourcesOpen, setSourcesOpen] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  /** The citations of the most recent answer. */
  const citations = useMemo(() => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index]
      if (message.role === 'assistant' && message.citations?.length) {
        return message.citations
      }
    }
    return []
  }, [messages])

  // Follow the stream: keep the newest content in view.
  useEffect(() => {
    const element = scrollRef.current
    if (element) {
      element.scrollTop = element.scrollHeight
    }
  }, [messages])

  const submit = () => {
    const text = draft.trim()
    if (!text || isStreaming) {
      return
    }
    onSend(text)
    setDraft('')
  }

  return (
    <div className="chat-panel">
      <div className="pane-header">
        <span className="pane-title">问答</span>
        <button
          type="button"
          className="pane-action"
          onClick={() => setSourcesOpen((open) => !open)}
        >
          来源 ({citations.length})
        </button>
      </div>

      <div className="chat-messages" ref={scrollRef}>
        {messages.length === 0 ? (
          <p className="empty-hint">问点什么吧，答案会带上文档引用。</p>
        ) : (
          messages.map((message) => (
            <Message
              key={message.id}
              message={message}
              onCitationJump={(citation) => onCitationJump?.(citation)}
              error={messageErrors?.[message.id]}
            />
          ))
        )}
      </div>

      <SourcesDrawer
        citations={citations}
        open={sourcesOpen}
        onClose={() => setSourcesOpen(false)}
        onSelect={(citation) => {
          setSourcesOpen(false)
          onCitationJump?.(citation)
        }}
      />

      <form
        className="chat-composer"
        onSubmit={(event) => {
          event.preventDefault()
          submit()
        }}
      >
        <textarea
          className="chat-input"
          value={draft}
          placeholder="对知识库提问…"
          rows={2}
          disabled={isStreaming}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              submit()
            }
          }}
        />
        {isStreaming ? (
          <button type="button" className="btn btn-danger" onClick={onStop}>
            停止
          </button>
        ) : (
          <button type="submit" className="btn btn-primary" disabled={!draft.trim()}>
            发送
          </button>
        )}
      </form>
    </div>
  )
}
