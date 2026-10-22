import { useEffect, useState } from 'react'

import {
  CODE_THEME,
  getHighlighter,
  resolveLang,
  type HighlighterLike,
} from '../lib/highlight'

export interface CodeBlockProps {
  /** The raw code (without the trailing newline markdown adds). */
  code: string
  /** The fence language, if the markdown block declared one. */
  lang?: string
}

/**
 * A fenced code block.
 *
 * Tokens are rendered as React elements (no `dangerouslySetInnerHTML`), so
 * the highlighted output can never inject markup. While the highlighter is
 * still loading — or when the language is unknown — the code is rendered as
 * plain text inside a `<pre>`.
 *
 * The highlighter is only requested for blocks that declare a language, so a
 * document without code never loads shiki at all.
 */
export function CodeBlock({ code, lang }: CodeBlockProps) {
  const [highlighter, setHighlighter] = useState<HighlighterLike | null>(null)

  useEffect(() => {
    if (!lang) {
      return
    }
    let alive = true
    getHighlighter()
      .then((instance) => {
        if (alive) {
          setHighlighter(instance)
        }
      })
      .catch(() => {
        // Degrade to plain code blocks — never break the page over it.
      })
    return () => {
      alive = false
    }
  }, [lang])

  const resolved = resolveLang(highlighter, lang)

  if (!highlighter || !resolved) {
    return (
      <pre className="code-block" data-lang={lang ?? 'text'}>
        <code>{code}</code>
      </pre>
    )
  }

  let tokens
  try {
    tokens = highlighter.codeToTokens(code, {
      lang: resolved,
      theme: CODE_THEME,
    }).tokens
  } catch {
    return (
      <pre className="code-block" data-lang={resolved}>
        <code>{code}</code>
      </pre>
    )
  }

  return (
    <pre className="code-block shiki" data-lang={resolved}>
      <code>
        {tokens.map((line, lineIndex) => (
          <span className="code-line" key={lineIndex}>
            {line.map((token, tokenIndex) => (
              <span
                key={tokenIndex}
                style={token.color ? { color: token.color } : undefined}
              >
                {token.content}
              </span>
            ))}
            {lineIndex < tokens.length - 1 ? '\n' : ''}
          </span>
        ))}
      </code>
    </pre>
  )
}
