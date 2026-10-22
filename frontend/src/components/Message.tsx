import Markdown, { type Components } from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import 'katex/dist/katex.min.css'

import type { ChatMessage, Citation } from '../api/types'
import { CitationMarker } from './CitationMarker'

export interface MessageProps {
  /** The message to render. */
  message: ChatMessage
  /** Called when a citation marker is clicked. */
  onCitationJump: (citation: Citation) => void
  /** Error of this message, if the stream failed. */
  error?: string | undefined
}

/**
 * External links open in a new tab — the chat panel is a SPA route and a
 * plain anchor would unload the whole application.
 */
const components: Components = {
  a: ({ href, children, ...rest }) => {
    const target = href ?? ''
    if (/^https?:\/\//i.test(target)) {
      return (
        <a href={target} target="_blank" rel="noreferrer noopener" {...rest}>
          {children}
        </a>
      )
    }
    return (
      <a href={target} {...rest}>
        {children}
      </a>
    )
  },
}

/**
 * One chat message.
 *
 * User messages are plain right-aligned bubbles, assistant messages are
 * rendered as markdown. The citation markers live *below* the body: the
 * backend does not emit inline markers, and the `references` event only
 * arrives after the last delta, so their position cannot be guessed.
 */
export function Message({ message, onCitationJump, error }: MessageProps) {
  const citations = message.citations ?? []

  if (message.role === 'user') {
    return (
      <div className="chat-message chat-user">
        <div className="chat-role">我</div>
        <div className="chat-content chat-bubble">{message.content}</div>
      </div>
    )
  }

  return (
    <div className="chat-message chat-assistant">
      <div className="chat-role">助手</div>
      <div className="chat-content chat-body">
        {message.content ? (
          <div className="chat-markdown">
            <Markdown
              remarkPlugins={[remarkGfm, remarkMath]}
              rehypePlugins={[rehypeKatex]}
              components={components}
            >
              {message.content}
            </Markdown>
          </div>
        ) : null}
        {message.streaming ? <span className="caret" aria-hidden="true" /> : null}
      </div>

      {error ? (
        <div className="chat-error" role="alert">
          回答出错：{error}
        </div>
      ) : null}

      {citations.length > 0 ? (
        <div className="chat-references">
          <div className="chat-references-title">来源</div>
          <div className="chat-citations">
            {citations.map((citation, index) => (
              <CitationMarker
                key={`${message.id}-${citation.chunk_id}-${index}`}
                citation={citation}
                index={index + 1}
                onClick={onCitationJump}
              />
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}
