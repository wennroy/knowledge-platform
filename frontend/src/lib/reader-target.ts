/**
 * Resolving "where should the reader jump to".
 *
 * The backend hands out character offsets into the *markdown source* of a
 * document. After rendering, the DOM is a different shape, and the chunker's
 * offset estimate drifts on CJK text — so locating a quote is best effort:
 *
 *  1. locate the section heading (stable, always possible when the document
 *     has the heading) and scroll to it;
 *  2. locate the quoted text itself and wrap it in a `<mark>`;
 *  3. if neither works, degrade silently — never throw, never blank the page.
 */

/**
 * A jump request for the reader pane.
 *
 * `mode` selects the primary strategy: `heading` (a citation — scroll to the
 * section it belongs to) or `exact` (a search hit — scroll to the line).
 */
export interface DocTarget {
  mode: 'heading' | 'exact'
  /** Character range inside `doc.content` (frontmatter already stripped). */
  start?: number
  end?: number
  /** 1-based line number inside `doc.content`. */
  line?: number
  /** The quoted passage — the text search fallback. */
  text?: string
}

const HEADING_RE = /^(#{1,6})\s+(.+?)\s*$/

/** Characters that carry meaning for a text match (letters, digits, CJK). */
const SIGNIFICANT_RE = /[\p{L}\p{N}]/u

/** Reduce a string to its significant characters, lower-cased. */
export function normalizeText(text: string): string {
  let out = ''
  for (const char of text) {
    if (SIGNIFICANT_RE.test(char)) {
      out += char.toLowerCase()
    }
  }
  return out
}

/**
 * The heading that contains `offset` — the last ATX heading that starts at or
 * before the offset, or `null` when the offset is not below any heading.
 */
export function deriveHeading(content: string, offset: number): string | null {
  let heading: string | null = null
  let position = 0
  for (const line of content.split('\n')) {
    if (position > offset) {
      break
    }
    const match = HEADING_RE.exec(line)
    if (match) {
      heading = match[2]
    }
    position += line.length + 1
  }
  return heading
}

/** Turn a target into a character range inside `content`, when possible. */
export function resolveRange(
  content: string,
  target: DocTarget,
): { start: number; end: number } | null {
  if (typeof target.start === 'number' && typeof target.end === 'number') {
    const start = Math.max(0, Math.min(target.start, content.length))
    const end = Math.max(start, Math.min(target.end, content.length))
    return { start, end }
  }
  if (typeof target.line === 'number') {
    const lines = content.split('\n')
    const index = target.line - 1
    if (index < 0 || index >= lines.length) {
      return null
    }
    let start = 0
    for (let i = 0; i < index; i += 1) {
      start += lines[i].length + 1
    }
    return { start, end: start + lines[index].length }
  }
  return null
}

/** Find the heading element whose text matches `text`. */
export function findHeadingElement(
  root: HTMLElement,
  text: string,
): Element | null {
  const needle = normalizeText(text)
  if (!needle) {
    return null
  }
  const headings = Array.from(
    root.querySelectorAll('h1, h2, h3, h4, h5, h6'),
  )
  for (const heading of headings) {
    if (normalizeText(heading.textContent ?? '') === needle) {
      return heading
    }
  }
  return null
}

/**
 * Find `needle` in the rendered text of `root` and return the matching DOM
 * range.
 *
 * The needle comes from the markdown source, the DOM from the rendered
 * markdown — so both sides are reduced to their significant characters
 * before matching (markdown syntax such as `**` or backticks disappears in
 * the DOM). When `after` is given, only text that follows that element is
 * searched, which keeps the match next to the heading we scrolled to.
 */
export function findTextRange(
  root: HTMLElement,
  needle: string,
  after?: Element | null,
): Range | null {
  const normalizedNeedle = normalizeText(needle)
  if (!normalizedNeedle) {
    return null
  }

  const nodes: Text[] = []
  const offsets: number[] = []
  const normalized: string[] = []
  const normalizedToPlain: number[] = []

  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  let current = walker.nextNode()
  while (current) {
    const node = current as Text
    const parent = node.parentElement
    const skipTag =
      parent !== null &&
      (parent.tagName === 'SCRIPT' ||
        parent.tagName === 'STYLE' ||
        parent.tagName === 'NOSCRIPT')
    const before =
      after != null &&
      (node.compareDocumentPosition(after) & Node.DOCUMENT_POSITION_FOLLOWING) !==
        0
    if (!skipTag && !before) {
      const text = node.data
      for (let i = 0; i < text.length; i += 1) {
        const char = text[i]
        const plainIndex = nodes.length
        nodes.push(node)
        offsets.push(i)
        if (SIGNIFICANT_RE.test(char)) {
          normalized.push(char.toLowerCase())
          normalizedToPlain.push(plainIndex)
        }
      }
    }
    current = walker.nextNode()
  }

  const haystack = normalized.join('')
  const at = haystack.indexOf(normalizedNeedle)
  if (at < 0) {
    return null
  }
  const startPlain = normalizedToPlain[at]
  const endPlain = normalizedToPlain[at + normalizedNeedle.length - 1]
  if (startPlain === undefined || endPlain === undefined) {
    return null
  }

  const range = document.createRange()
  range.setStart(nodes[startPlain], offsets[startPlain])
  range.setEnd(nodes[endPlain], offsets[endPlain] + 1)
  return range
}

/** Wrap a range in a `<mark>`; returns the element, or `null` on failure. */
export function markRange(range: Range, className: string): HTMLElement | null {
  try {
    const mark = document.createElement('mark')
    mark.className = className
    range.surroundContents(mark)
    return mark
  } catch {
    return null
  }
}

/** Remove every `<mark class="...">` we added earlier. */
export function clearMarks(root: HTMLElement, className: string): void {
  const marks = Array.from(root.querySelectorAll(`mark.${className}`))
  for (const mark of marks) {
    const parent = mark.parentNode
    if (!parent) {
      continue
    }
    while (mark.firstChild) {
      parent.insertBefore(mark.firstChild, mark)
    }
    parent.removeChild(mark)
    parent.normalize()
  }
}
