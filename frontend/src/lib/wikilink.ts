/**
 * `[[wikilink]]` parsing.
 *
 * The vault uses Obsidian-style wikilinks (`[[tech-stack]]`) which plain
 * markdown renders as literal text. This module parses them and rewrites
 * them into markdown links with the `kb://` scheme, which the reader then
 * turns into clickable links.
 *
 * The `kb://target` → vault path mapping lives in `wikilink-index.ts`.
 */

/** A parsed wikilink: `[[target]]` or `[[target|alias]]`. */
export interface Wikilink {
  /** The link target, e.g. `tech-stack`. */
  target: string
  /** The optional display text, e.g. `技术栈`. */
  alias?: string
}

/** A piece of text: either plain text or a wikilink. */
export type WikilinkSegment =
  | { type: 'text'; value: string }
  | { type: 'link'; value: Wikilink }

/** The scheme used for the generated markdown links. */
export const KB_SCHEME = 'kb://'

const WIKILINK_RE = /\[\[([^\]\n]+?)\]\]/g

/** Matches the opening (or closing) fence of a code block. */
const FENCE_RE = /^(?:`{3,}|~{3,})/

/** Matches the start of a list item, capturing indentation, marker and gap. */
const LIST_RE = /^(\s*)([-*+]|\d+[.)])(\s+)\S/

/** Parse every wikilink of a text. */
export function parseWikilinks(text: string): Wikilink[] {
  const links: Wikilink[] = []
  for (const match of text.matchAll(WIKILINK_RE)) {
    const link = toWikilink(match[1])
    if (link) {
      links.push(link)
    }
  }
  return links
}

/** Split a text into plain-text and wikilink segments. */
export function splitWikilinks(text: string): WikilinkSegment[] {
  const segments: WikilinkSegment[] = []
  let cursor = 0
  for (const match of text.matchAll(WIKILINK_RE)) {
    const index = match.index ?? 0
    const link = toWikilink(match[1])
    if (!link) {
      continue
    }
    if (index > cursor) {
      segments.push({ type: 'text', value: text.slice(cursor, index) })
    }
    segments.push({ type: 'link', value: link })
    cursor = index + match[0].length
  }
  if (cursor < text.length) {
    segments.push({ type: 'text', value: text.slice(cursor) })
  }
  return segments
}

/** Build a wikilink from the raw `target|alias` part. */
function toWikilink(raw: string): Wikilink | null {
  const pipe = raw.indexOf('|')
  const target = (pipe === -1 ? raw : raw.slice(0, pipe)).trim()
  const alias = pipe === -1 ? '' : raw.slice(pipe + 1).trim()
  if (!target) {
    return null
  }
  return alias ? { target, alias } : { target }
}

/** Replace one wikilink with a markdown link using the `kb://` scheme. */
function toMarkdownLink(link: Wikilink): string {
  const label = link.alias ?? link.target
  const href = `${KB_SCHEME}${encodeURIComponent(link.target)}`
  return `[${label}](${href})`
}

/**
 * Split a line into inline-code and non-code parts.
 *
 * Inline code (`` `like this` ``) must not be rewritten — a wikilink inside
 * a code span is a literal string, not a link.
 */
function splitInlineCode(line: string): { text: string; code: boolean }[] {
  const parts: { text: string; code: boolean }[] = []
  let buffer = ''
  let index = 0
  while (index < line.length) {
    if (line[index] === '`') {
      let runEnd = index
      while (runEnd < line.length && line[runEnd] === '`') {
        runEnd += 1
      }
      const run = line.slice(index, runEnd)
      const close = line.indexOf(run, runEnd)
      if (close !== -1) {
        if (buffer) {
          parts.push({ text: buffer, code: false })
          buffer = ''
        }
        parts.push({ text: line.slice(index, close + run.length), code: true })
        index = close + run.length
        continue
      }
    }
    buffer += line[index]
    index += 1
  }
  if (buffer) {
    parts.push({ text: buffer, code: false })
  }
  return parts
}

/** Rewrite the wikilinks of a single (non-code) line. */
function transformLine(line: string): string {
  return splitInlineCode(line)
    .map((part) =>
      part.code
        ? part.text
        : part.text.replace(WIKILINK_RE, (whole, raw: string) => {
            const link = toWikilink(raw)
            return link ? toMarkdownLink(link) : whole
          }),
    )
    .join('')
}

/**
 * The column width of a line's leading whitespace.
 *
 * A tab advances to the next multiple of four, which is what CommonMark
 * assumes.
 */
function indentWidth(line: string): number {
  let width = 0
  for (const ch of line) {
    if (ch === ' ') {
      width += 1
    } else if (ch === '\t') {
      width += 4 - (width % 4)
    } else {
      break
    }
  }
  return width
}

/**
 * The content column of a list item — the column its content starts at.
 *
 * `- item` puts its content at column 2; `1. item` at column 3. Blocks
 * inside the item are measured relative to that column, which is what
 * CommonMark does.
 */
function listContentIndent(line: string): number | null {
  const match = LIST_RE.exec(line)
  if (!match) {
    return null
  }
  return match[1].length + match[2].length + match[3].length
}

/**
 * Rewrite every wikilink of a markdown document into a `kb://` link.
 *
 * Fenced code blocks, indented code blocks and inline code spans are left
 * untouched — a wikilink inside code is a literal string, not a link.
 *
 * Indentation is measured *relative to the enclosing list item's content
 * column*, so both a list item's own code block (6+ spaces) and a fence
 * nested inside a list item (indented to the item's content column) are
 * recognised correctly.
 */
export function preprocessWikilinks(markdown: string): string {
  const lines = markdown.split('\n')
  const out: string[] = []
  let inFence = false
  // Content column of the list item we are currently inside; 0 = top level.
  let listIndent = 0

  for (const line of lines) {
    // The leading whitespace, counted in characters (for slicing) and in
    // columns (for the code-block rules — a tab is worth four columns).
    const charIndent = /^[ \t]*/.exec(line)?.[0].length ?? 0
    const columns = indentWidth(line)
    const content = line.slice(charIndent)

    // Track the enclosing list item.
    const itemIndent = listContentIndent(line)
    if (itemIndent !== null) {
      listIndent = itemIndent
    } else if (line.trim() && columns < listIndent) {
      // Dedented back out of the list item.
      listIndent = 0
    }

    const effectiveIndent = Math.max(0, columns - listIndent)

    // A fence may be indented by up to 3 columns relative to its context.
    const isFence = effectiveIndent <= 3 && FENCE_RE.test(content)
    if (isFence) {
      inFence = !inFence
      out.push(line)
      continue
    }

    // Four columns of relative indentation make a code block.
    const isIndentedCode = !inFence && effectiveIndent >= 4
    out.push(inFence || isIndentedCode ? line : transformLine(line))
  }
  return out.join('\n')
}
