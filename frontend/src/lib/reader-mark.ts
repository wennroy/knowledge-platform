/**
 * Highlighting a quoted passage in the rendered document.
 *
 * `Range.surroundContents` throws when the range spans more than one
 * element — and a quoted passage often does: a `[[wikilink]]` in the middle
 * of a sentence splits one text node into three. In that case every text
 * node of the range is wrapped on its own, which gives the same visual
 * result.
 *
 * The DOM is manipulated directly (no React re-render) — the reader owns the
 * rendered article and only needs a visual marker.
 */

/** One text node of a range, with the offsets that belong to the range. */
interface RangeSegment {
  node: Text
  start: number
  end: number
}

/** Collect the text nodes of a range and the offsets they contribute. */
function collectSegments(range: Range): RangeSegment[] {
  const segments: RangeSegment[] = []
  const walker = document.createTreeWalker(
    range.commonAncestorContainer,
    NodeFilter.SHOW_TEXT,
  )
  let current = walker.nextNode()
  while (current) {
    const node = current as Text
    if (isInsideRange(range, node)) {
      const start = node === range.startContainer ? range.startOffset : 0
      const end =
        node === range.endContainer ? range.endOffset : node.data.length
      if (end > start) {
        segments.push({ node, start, end })
      }
    }
    if (node === range.endContainer) {
      break
    }
    current = walker.nextNode()
  }
  return segments
}

/**
 * Is the text node part of the range?
 *
 * The document order is used instead of `compareBoundaryPoints` — the latter
 * compares its arguments in an order that differs between engines.
 */
function isInsideRange(range: Range, node: Text): boolean {
  if (node === range.startContainer || node === range.endContainer) {
    return true
  }
  const followsStart =
    (range.startContainer.compareDocumentPosition(node) &
      Node.DOCUMENT_POSITION_FOLLOWING) !==
    0
  const precedesEnd =
    (range.endContainer.compareDocumentPosition(node) &
      Node.DOCUMENT_POSITION_PRECEDING) !==
    0
  return followsStart && precedesEnd
}

/** Wrap `node[start..end]` in a `<mark>`. */
function wrapPart(
  node: Text,
  start: number,
  end: number,
  className: string,
): HTMLElement | null {
  const parent = node.parentNode
  if (!parent) {
    return null
  }
  let target = node
  if (start > 0) {
    target = target.splitText(start)
  }
  const length = end - start
  if (length < target.data.length) {
    target.splitText(length)
  }
  const mark = document.createElement('mark')
  mark.className = className
  parent.insertBefore(mark, target)
  mark.appendChild(target)
  return mark
}

/**
 * Wrap a range in a `<mark>`.
 *
 * Returns the created element, or `null` when the range could not be
 * highlighted — a failed highlight never breaks the jump itself.
 */
export function applyMark(range: Range, className: string): HTMLElement | null {
  try {
    const mark = document.createElement('mark')
    mark.className = className
    range.surroundContents(mark)
    return mark
  } catch {
    // The range spans several elements — wrap the parts one by one.
  }
  const segments = collectSegments(range)
  let first: HTMLElement | null = null
  for (const segment of segments) {
    const mark = wrapPart(segment.node, segment.start, segment.end, className)
    if (mark && !first) {
      first = mark
    }
  }
  return first
}
