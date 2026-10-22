import { createHighlighterCore } from 'shiki/core'
import { createJavaScriptRegexEngine } from 'shiki/engine/javascript'

import type { HighlighterLike } from './highlight'

/**
 * The shiki setup, isolated in its own module so it can be loaded lazily.
 *
 * We use the *core* bundle with an explicit grammar list instead of the full
 * bundle: the full one ships a loader for all 300+ languages plus a 600 kB
 * oniguruma WASM blob, while we only ever highlight a handful of languages.
 * The JavaScript regex engine avoids the WASM entirely.
 */

/** Grammars we are willing to load (one dynamic import each). */
const LANGS = [
  import('shiki/langs/markdown.mjs'),
  import('shiki/langs/json.mjs'),
  import('shiki/langs/yaml.mjs'),
  import('shiki/langs/toml.mjs'),
  import('shiki/langs/ini.mjs'),
  import('shiki/langs/python.mjs'),
  import('shiki/langs/javascript.mjs'),
  import('shiki/langs/jsx.mjs'),
  import('shiki/langs/typescript.mjs'),
  import('shiki/langs/tsx.mjs'),
  import('shiki/langs/bash.mjs'),
  import('shiki/langs/html.mjs'),
  import('shiki/langs/xml.mjs'),
  import('shiki/langs/css.mjs'),
  import('shiki/langs/scss.mjs'),
  import('shiki/langs/go.mjs'),
  import('shiki/langs/rust.mjs'),
  import('shiki/langs/java.mjs'),
  import('shiki/langs/kotlin.mjs'),
  import('shiki/langs/sql.mjs'),
  import('shiki/langs/dockerfile.mjs'),
  import('shiki/langs/diff.mjs'),
]

/** Build the shared highlighter. */
export async function createHighlighter(): Promise<HighlighterLike> {
  const highlighter = await createHighlighterCore({
    themes: [import('shiki/themes/github-light.mjs')],
    langs: LANGS,
    engine: createJavaScriptRegexEngine(),
  })
  return highlighter as unknown as HighlighterLike
}
