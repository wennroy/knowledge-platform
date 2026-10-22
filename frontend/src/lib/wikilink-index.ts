/**
 * The `wikilink target → vault path` index.
 *
 * The document tree (`GET /v1/tree`) already lists every file of the vault
 * with its vault-relative path, so the index can be built synchronously
 * from it — no extra request, and no flicker while a request is in flight.
 */

/** The vault-relative path of a wikilink target. */
export interface WikilinkIndex {
  /** `team/tech-stack.md` and `team/tech-stack` → the same path. */
  byPath: Map<string, string>
  /** `tech-stack` → `team/tech-stack.md`. */
  byStem: Map<string, string>
}

/** An empty index — every wikilink stays plain text. */
export const EMPTY_WIKILINK_INDEX: WikilinkIndex = {
  byPath: new Map(),
  byStem: new Map(),
}

/** Prefer the shortest path, then the lexicographically first one. */
function isBetterPath(candidate: string, current: string | undefined): boolean {
  if (!current) {
    return true
  }
  const candidateDepth = candidate.split('/').length
  const currentDepth = current.split('/').length
  if (candidateDepth !== currentDepth) {
    return candidateDepth < currentDepth
  }
  return candidate < current
}

/**
 * Build the index from the vault-relative paths of the document tree.
 *
 * A bare basename (`tech-stack`) is resolved through `byStem`; an explicit
 * path (`team/tech-stack.md`) through `byPath`.
 */
export function buildWikilinkIndex(paths: string[]): WikilinkIndex {
  const byPath = new Map<string, string>()
  const byStem = new Map<string, string>()
  for (const path of paths) {
    if (!path) {
      continue
    }
    byPath.set(path, path)
    if (path.endsWith('.md')) {
      byPath.set(path.slice(0, -3), path)
    } else {
      byPath.set(`${path}.md`, path)
    }
    const stem = path.slice(path.lastIndexOf('/') + 1).replace(/\.md$/, '')
    if (isBetterPath(path, byStem.get(stem))) {
      byStem.set(stem, path)
    }
  }
  return { byPath, byStem }
}

/** Resolve a wikilink target to a vault-relative path. */
export function resolveWikilink(
  index: WikilinkIndex,
  target: string,
): string | null {
  const raw = target.trim()
  if (!raw) {
    return null
  }
  const withoutExt = raw.endsWith('.md') ? raw.slice(0, -3) : raw
  const direct =
    index.byPath.get(raw) ??
    index.byPath.get(`${withoutExt}.md`) ??
    index.byPath.get(withoutExt)
  if (direct) {
    return direct
  }
  const stem = withoutExt.slice(withoutExt.lastIndexOf('/') + 1)
  return index.byStem.get(stem) ?? null
}
