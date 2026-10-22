import Markdown from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import 'katex/dist/katex.min.css'

import type { Citation, FileDoc, HighlightRange } from '../api/types'

export interface DocReaderProps {
  /** The document to render; `null` when nothing is selected. */
  doc: FileDoc | null
  /** Character range to highlight (from a citation jump). */
  highlight: HighlightRange | null
  /** Called when the reader wants to jump to a citation. */
  onCitationJump: (citation: Citation) => void
}

/**
 * Middle column: renders the markdown document.
 *
 * `react-markdown` without `rehype-raw` drops raw HTML — the safe default
 * (see §2 of the plan). Code highlighting via shiki is wired in F2.
 */
export function DocReader({
  doc,
  highlight,
  // Reserved for F2: clicking an inline reference inside the rendered
  // markdown jumps to the cited document.
  onCitationJump: _onCitationJump,
}: DocReaderProps) {
  if (!doc) {
    return (
      <div className="doc-reader">
        <div className="pane-header">
          <span className="pane-title">阅读区</span>
        </div>
        <p className="empty-hint">从左侧选择一个文档开始阅读。</p>
      </div>
    )
  }

  return (
    <div className="doc-reader">
      <div className="pane-header">
        <span className="pane-title" title={doc.file_path}>
          {doc.file_path}
        </span>
        <span className="pane-hint">
          {Math.round(doc.size_bytes / 1024)} KB · {doc.updated_at.slice(0, 10)}
        </span>
      </div>

      {highlight ? (
        <div className="reader-highlight-note">
          已定位引用片段（字符 {highlight.start}–{highlight.end}）
        </div>
      ) : null}

      <article className="markdown-body">
        <Markdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
          {doc.content}
        </Markdown>
      </article>
    </div>
  )
}
