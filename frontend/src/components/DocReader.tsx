import { useEffect, useRef, useState } from 'react'
import 'katex/dist/katex.min.css'

import type { Citation, FileDoc } from '../api/types'
import type { LoadStatus } from '../lib/load'
import { applyMark } from '../lib/reader-mark'
import type { WikilinkIndex } from '../lib/wikilink-index'
import {
  clearMarks,
  deriveHeading,
  findHeadingElement,
  findTextRange,
  resolveRange,
  type DocTarget,
} from '../lib/reader-target'
import { DocMarkdown } from './DocMarkdown'
import { DocToc, type TocItem } from './DocToc'

export interface DocReaderProps {
  /** The document to render; `null` when nothing is selected. */
  doc: FileDoc | null
  /** Lifecycle of the document request. */
  status: LoadStatus
  /** Error message of the failed document request. */
  error: string | null
  /** Re-runs the document request. */
  onRetry: () => void
  /** Where the reader should jump to. */
  target: DocTarget | null
  /**
   * Called when the reader wants to jump to a citation.
   *
   * Reserved for the `[[wikilink]]` support (F2 ships the plumbing, the
   * link rendering itself is not part of this batch).
   */
  onCitationJump: (citation: Citation) => void
  /** Called when a `[[wikilink]]` is clicked — opens that document. */
  onOpenPath: (path: string) => void
  /** Maps a wikilink target onto a vault path. */
  wikilinkIndex: WikilinkIndex
}

const MARK_CLASS = 'reader-mark'

/**
 * Find a quoted passage that is only a part of a larger chunk.
 *
 * The chunker merges the paragraphs of a section, so the quoted text may
 * span several paragraphs — and the rendered document puts the headings
 * between them, which breaks a contiguous match. In that case the first
 * paragraph of the quote is located on its own.
 */
function findParagraphRange(
  root: HTMLElement,
  quoted: string,
  after?: Element | null,
): Range | null {
  const paragraphs = quoted
    .split(/\n{2,}/)
    .map((part) => part.trim())
    .filter((part) => part.length > 0)
  for (const paragraph of paragraphs) {
    const range = findTextRange(root, paragraph, after)
    if (range) {
      return range
    }
  }
  return null
}

/** Frontmatter tags are free-form — coerce them into a list of strings. */
function readTags(frontmatter: Record<string, unknown>): string[] {
  const raw = frontmatter?.tags
  if (Array.isArray(raw)) {
    return raw.filter((tag): tag is string => typeof tag === 'string')
  }
  if (typeof raw === 'string') {
    return raw
      .split(',')
      .map((tag) => tag.trim())
      .filter(Boolean)
  }
  return []
}

/**
 * Middle column: renders the markdown document.
 *
 * `react-markdown` without `rehype-raw` drops raw HTML — the safe default
 * (see §2 of the plan). Code blocks are highlighted with shiki, and a jump
 * request (`target`) is resolved against the rendered DOM.
 */
export function DocReader({
  doc,
  status,
  error,
  onRetry,
  target,
  onOpenPath,
  wikilinkIndex,
}: DocReaderProps) {
  const articleRef = useRef<HTMLElement>(null)
  const [toc, setToc] = useState<TocItem[]>([])
  const [tocOpen, setTocOpen] = useState(false)
  const [located, setLocated] = useState<string | null>(null)

  // Outline: read the headings back out of the rendered document.
  useEffect(() => {
    const article = articleRef.current
    if (!article || !doc) {
      setToc([])
      return
    }
    const headings = Array.from(article.querySelectorAll('h1, h2, h3'))
    setToc(
      headings.map((heading, index) => {
        const id = `sec-${index}`
        heading.id = id
        return {
          id,
          text: (heading.textContent ?? '').trim(),
          level: Number(heading.tagName.slice(1)),
        }
      }),
    )
  }, [doc])

  // Jump request: locate the heading first, the quoted text as an enhancement.
  useEffect(() => {
    const article = articleRef.current
    if (!article || !doc) {
      return
    }
    clearMarks(article, MARK_CLASS)
    for (const element of Array.from(article.querySelectorAll('.is-target'))) {
      element.classList.remove('is-target')
    }
    if (!target) {
      setLocated(null)
      return
    }

    const range = resolveRange(doc.content, target)
    const quoted =
      target.text ?? (range ? doc.content.slice(range.start, range.end) : '')
    // The chunker labels a chunk with the heading of its *last* segment, so
    // the end offset points at the section the citation really belongs to.
    const headingText = range
      ? (deriveHeading(doc.content, range.end) ??
        deriveHeading(doc.content, range.start))
      : null
    const heading = headingText
      ? findHeadingElement(article, headingText)
      : null
    const hit =
      findTextRange(article, quoted, heading) ??
      findParagraphRange(article, quoted, heading)

    if (target.mode === 'exact' && hit) {
      applyMark(hit, MARK_CLASS)
      hit.startContainer.parentElement?.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      })
      setLocated(
        target.line ? `已定位到第 ${target.line} 行` : '已定位到目标片段',
      )
      return
    }

    if (heading) {
      heading.classList.add('is-target')
      heading.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
    if (hit) {
      applyMark(hit, MARK_CLASS)
    }
    setLocated(
      hit
        ? '已定位引用片段'
        : heading
          ? '已定位到所属章节（原文片段未能精确匹配）'
          : '未能定位到引用片段，已显示完整文档',
    )
  }, [doc, target, wikilinkIndex])

  const tags = doc ? readTags(doc.frontmatter) : []


  return (
    <div className="doc-reader">
      <div className="pane-header">
        <span className="pane-title" title={doc?.file_path ?? ''}>
          {doc?.file_path ?? '阅读区'}
        </span>
        <span className="pane-hint">
          {doc
            ? `${Math.max(1, Math.round(doc.size_bytes / 1024))} KB · ${doc.updated_at.slice(0, 10)}`
            : ''}
        </span>
        <button
          type="button"
          className="pane-action"
          onClick={() => setTocOpen((open) => !open)}
          disabled={toc.length === 0}
        >
          大纲 ({toc.length})
        </button>
      </div>

      {status === 'loading' ? (
        <p className="empty-hint">正在加载文档…</p>
      ) : null}

      {status === 'error' ? (
        <div className="pane-error">
          <p className="error-text">读取文档失败：{error}</p>
          <button type="button" className="btn" onClick={onRetry}>
            重试
          </button>
        </div>
      ) : null}

      {tags.length > 0 ? (
        <div className="reader-tags">
          {tags.map((tag) => (
            <span className="tag" key={tag}>
              {tag}
            </span>
          ))}
        </div>
      ) : null}

      {target?.text ? (
        <div className="reader-quote">
          <div className="reader-quote-label">引用原文</div>
          <blockquote>{target.text}</blockquote>
        </div>
      ) : null}

      {located ? (
        <div className="reader-highlight-note">{located}</div>
      ) : null}

      {tocOpen ? (
        <DocToc
          items={toc}
          onSelect={(id) => {
            document.getElementById(id)?.scrollIntoView({
              behavior: 'smooth',
              block: 'start',
            })
          }}
        />
      ) : null}

      <article className="markdown-body" ref={articleRef}>
        {doc ? (
          <DocMarkdown
            content={doc.content}
            wikilinkIndex={wikilinkIndex}
            onOpenPath={onOpenPath}
          />
        ) : status === 'idle' ? (
          <p className="empty-hint">从左侧选择一个文档开始阅读。</p>
        ) : null}
      </article>
    </div>
  )
}
