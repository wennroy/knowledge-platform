import { Children, isValidElement, useMemo } from 'react'
import Markdown, { defaultUrlTransform, type Components } from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'

import { KB_SCHEME, preprocessWikilinks } from '../lib/wikilink'
import { resolveWikilink, type WikilinkIndex } from '../lib/wikilink-index'
import { CodeBlock } from './CodeBlock'

export interface DocMarkdownProps {
  /** The markdown source of the document. */
  content: string
  /** Maps a wikilink target onto a vault path. */
  wikilinkIndex: WikilinkIndex
  /** Called when a `[[wikilink]]` is clicked — opens that document. */
  onOpenPath: (path: string) => void
}

/**
 * The markdown body of the reader.
 *
 * `[[wikilink]]` is rewritten into `kb://` links before rendering; a link
 * whose target cannot be resolved stays plain text (no error, no dead link).
 *
 * `react-markdown` runs without `rehype-raw`, so raw HTML in the document is
 * dropped — the safe default.
 */
export function DocMarkdown({
  content,
  wikilinkIndex,
  onOpenPath,
}: DocMarkdownProps) {
  const components = useMemo<Components>(
    () => ({
      // A fenced code block arrives as <pre><code class="language-x">…</code></pre>.
      // We take the block over completely so we can render shiki tokens.
      pre: (props) => {
        if (Children.count(props.children) !== 1) {
          return <pre>{props.children}</pre>
        }
        const child = Children.only(props.children)
        if (!isValidElement(child)) {
          return <pre>{props.children}</pre>
        }
        const childProps = child.props as {
          className?: string
          children?: unknown
        }
        const className = childProps.className ?? ''
        const lang = /language-([\w+#.-]+)/.exec(className)?.[1]
        const code =
          typeof childProps.children === 'string' ? childProps.children : ''
        return <CodeBlock code={code.replace(/\n$/, '')} lang={lang} />
      },
      // Inline code keeps the default look.
      code: (props) => {
        const { node: _node, className, children, ...rest } = props
        return (
          <code className={className} {...rest}>
            {children}
          </code>
        )
      },
      // `[[wikilink]]` was rewritten into a `kb://` link before rendering.
      a: (props) => {
        const { node: _node, href, children, ...rest } = props
        const target = href ?? ''
        if (!target.startsWith(KB_SCHEME)) {
          return (
            <a href={target} {...rest}>
              {children}
            </a>
          )
        }
        let raw = target.slice(KB_SCHEME.length)
        try {
          raw = decodeURIComponent(raw)
        } catch {
          // Keep the raw target when it is not valid percent-encoding.
        }
        const path = resolveWikilink(wikilinkIndex, raw)
        if (!path) {
          // Unknown target — plain text, no error.
          return <span className="wikilink-missing">[[{children}]]</span>
        }
        const hrefPath = path
          .split('/')
          .map((segment) => encodeURIComponent(segment))
          .join('/')
        return (
          <a
            className="wikilink"
            href={`/app/doc/${hrefPath}`}
            title={path}
            onClick={(event) => {
              event.preventDefault()
              onOpenPath(path)
            }}
          >
            {children}
          </a>
        )
      },
    }),
    [wikilinkIndex, onOpenPath],
  )

  // `[[wikilink]]` -> `kb://` links (code blocks are left alone).
  const source = useMemo(() => preprocessWikilinks(content), [content])

  return (
    <Markdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeKatex]}
      components={components}
      urlTransform={(url) =>
        url.startsWith(KB_SCHEME) ? url : defaultUrlTransform(url)
      }
    >
      {source}
    </Markdown>
  )
}
