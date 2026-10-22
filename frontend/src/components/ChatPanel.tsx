import { useState } from 'react'

import type { ChatMessage, Citation } from '../api/types'
import { CitationMarker } from './CitationMarker'
import { SourcesDrawer } from './SourcesDrawer'

export interface ChatPanelProps {
  /** Messages shown in the panel, oldest first. */
  messages: ChatMessage[]
  /** Called with the user's message when they press send. */
  onSend: (text: string) => void
  /** True while an answer is streaming in. */
  isStreaming: boolean
  /** Called when an inline citation marker is clicked. */
  onCitationJump?: (citation: Citation) => void
}

/**
 * Right-hand column: the AI question-and-answer panel.
 *
 * F1 renders static messages; the SSE wiring lands in F3.
 */
export function ChatPanel({
  messages,
  onSend,
  isStreaming,
  onCitationJump,
}: ChatPanelProps) {
  const [draft, setDraft] = useState('')
  const [sourcesOpen, setSourcesOpen] = useState(false)

  const citations = messages
    .flatMap((message) => message.citations ?? [])
    .slice(-8)

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

      <div className="chat-messages">
        {messages.length === 0 ? (
          <p className="empty-hint">问点什么吧，答案会带上文档引用。</p>
        ) : (
          messages.map((message) => (
            <div className={`chat-message chat-${message.role}`} key={message.id}>
              <div className="chat-role">
                {message.role === 'user' ? '我' : '助手'}
              </div>
              <div className="chat-content">
                {message.content}
                {message.streaming ? <span className="caret" /> : null}
              </div>
              {message.citations && message.citations.length > 0 ? (
                <div className="chat-citations">
                  {message.citations.map((citation, index) => (
                    <CitationMarker
                      key={`${message.id}-${citation.chunk_id}-${index}`}
                      citation={citation}
                      index={index + 1}
                      onClick={(target) => onCitationJump?.(target)}
                    />
                  ))}
                </div>
              ) : null}
            </div>
          ))
        )}
      </div>

      <SourcesDrawer
        citations={citations}
        open={sourcesOpen}
        onClose={() => setSourcesOpen(false)}
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
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              submit()
            }
          }}
        />
        <button type="submit" className="btn btn-primary" disabled={isStreaming}>
          {isStreaming ? '回答中…' : '发送'}
        </button>
      </form>
    </div>
  )
}
