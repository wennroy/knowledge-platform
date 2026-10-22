/**
 * Shiki integration.
 *
 * The highlighter is created lazily and shared by every code block: building
 * it loads the grammars, which is far too expensive to do per document (or
 * per code block). The shiki setup itself lives in `./shiki-core` and is
 * imported dynamically, so documents without code never pay for it.
 *
 * The `lang` of a markdown fence is untrusted input, so it never reaches
 * shiki directly — it is mapped through {@link resolveLang} onto one of the
 * grammars we actually loaded, and everything else falls back to plain text.
 */

/** The theme every code block is highlighted with. */
export const CODE_THEME = 'github-light'

/**
 * Languages shiki renders without a grammar — they are plain text.
 *
 * `plaintext` is not a bundled language, but shiki special-cases it (and its
 * aliases) so it always works.
 */
const PLAIN_LANGS = new Set(['plaintext'])

/** Fence aliases mapped onto the canonical grammar ids we load. */
const ALIASES: Record<string, string> = {
  md: 'markdown',
  markdown: 'markdown',
  json: 'json',
  jsonc: 'json',
  yml: 'yaml',
  yaml: 'yaml',
  toml: 'toml',
  ini: 'ini',
  cfg: 'ini',
  py: 'python',
  python: 'python',
  js: 'javascript',
  javascript: 'javascript',
  jsx: 'jsx',
  node: 'javascript',
  ts: 'typescript',
  typescript: 'typescript',
  tsx: 'tsx',
  sh: 'bash',
  shell: 'bash',
  zsh: 'bash',
  bash: 'bash',
  console: 'bash',
  html: 'html',
  xml: 'xml',
  svg: 'xml',
  vue: 'html',
  css: 'css',
  scss: 'scss',
  less: 'css',
  go: 'go',
  golang: 'go',
  rust: 'rust',
  rs: 'rust',
  java: 'java',
  kotlin: 'kotlin',
  kt: 'kotlin',
  sql: 'sql',
  dockerfile: 'dockerfile',
  docker: 'dockerfile',
  diff: 'diff',
  patch: 'diff',
  text: 'plaintext',
  txt: 'plaintext',
  plain: 'plaintext',
  plaintext: 'plaintext',
}

/** One highlighted token of a code line. */
export interface HighlightToken {
  content: string
  color?: string
}

/**
 * The slice of shiki's `Highlighter` we use.
 *
 * Declared locally so we can call it with plain strings — shiki's bundled
 * type only accepts the literal union of bundled language ids.
 */
export interface HighlighterLike {
  codeToTokens(
    code: string,
    options: { lang: string; theme: string },
  ): { tokens: HighlightToken[][] }
  getLoadedLanguages(): string[]
}

let pending: Promise<HighlighterLike> | null = null

/** Create (once) and return the shared highlighter. */
export function getHighlighter(): Promise<HighlighterLike> {
  if (!pending) {
    pending = import('./shiki-core')
      .then((module) => module.createHighlighter())
      .catch((error: unknown) => {
        // Allow a later attempt to retry instead of caching the failure.
        pending = null
        throw error
      })
  }
  return pending
}

/**
 * Map a fence language onto a loaded grammar, or `null` when the language is
 * unknown (the caller then renders plain, unhighlighted code).
 */
export function resolveLang(
  highlighter: HighlighterLike | null,
  raw: string | undefined,
): string | null {
  if (!highlighter || !raw) {
    return null
  }
  const key = raw.trim().toLowerCase()
  const candidate = ALIASES[key] ?? key
  if (PLAIN_LANGS.has(candidate)) {
    return candidate
  }
  const loaded = highlighter.getLoadedLanguages()
  return loaded.includes(candidate) ? candidate : null
}
