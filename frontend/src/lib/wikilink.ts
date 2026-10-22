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
const FENCE_RE = /^\s{0,3}(`{3,}|~{3,})/

/** Matches the start of a list item. */
const LIST_RE = /^\s*(?:[-*+]|\d+[.)])\s/

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
 * Rewrite every wikilink of a markdown document into a `kb://` link.
 *
 * Fenced code blocks, indented code blocks and inline code spans are left
 * untouched — a wikilink inside code is a literal string, not a link.
 */
export function preprocessWikilinks(markdown: string): string {
  const lines = markdown.split('\n')
  const out: string[] = []
  let inFence = false
  let previousMeaningful = ''
  for (const line of lines) {
    if (FENCE_RE.test(line)) {
      inFence = !inFence
      out.push(line)
      if (line.trim()) {
        previousMeaningful = line
      }
      continue
    }
    // An indented block is code — unless it continues a list item.
    const indentedCode =
      !inFence &&
      /^(?: {4,}|\t)/.test(line) &&
      !LIST_RE.test(previousMeaningful)
    out.push(inFence || indentedCode ? line : transformLine(line))
    if (line.trim()) {
      previousMeaningful = line
    }
  }
  return out.join('\n')
}
