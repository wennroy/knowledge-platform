/**
 * Knowledge-graph wire types.
 *
 * They mirror the `GET /graph` payload of the backend (see
 * `backend/app/routes/graph.py`) plus the d3-style shape that
 * `react-force-graph-2d` consumes.
 *
 * NOTE: these are `type` aliases, not `interface`s — an object type alias
 * gets an implicit index signature, which is what makes it assignable to the
 * library's `NodeObject` / `LinkObject` types (which carry an index
 * signature). An `interface` would not be.
 */

/** One document (or dangling wikilink target) in the graph. */
export type GNode = {
  /** Vault-relative path of the document, e.g. `team/tech-stack.md`. */
  id: string
  /** File stem of the document. */
  label: string
  /** Frontmatter title, if the document has one. */
  title?: string | null
  /** Frontmatter tags. */
  tags: string[]
  /** Body size in characters — drives the node radius. */
  size: number
  /** First 200 characters of the body. */
  summary?: string
  /** True when the wikilink target does not exist in the vault. */
  dangling?: boolean
}

/** One edge between two nodes. */
export type GLink = {
  source: string
  target: string
  /** `wikilink` (a `[[link]]` in the body) or `share-tag` (shared tags). */
  type: 'wikilink' | 'share-tag'
  /** Number of shared tags for `share-tag` edges; always 1 for wikilinks. */
  weight: number
}

/** The raw `GET /graph` payload. */
export type WireData = {
  nodes: GNode[]
  edges: GLink[]
  /** True when the vault is too large and only the top nodes are returned. */
  degraded?: boolean
  /** Human-readable explanation of the degradation. */
  note?: string
}

/**
 * The shape `react-force-graph-2d` expects: `links`, not `edges` (which is
 * what d3-force uses).
 */
export type ForceData = {
  nodes: GNode[]
  links: GLink[]
}
