/**
 * Shared API types.
 *
 * These mirror the backend contracts:
 *   GET /v1/tree            -> TreeNode[]
 *   GET /v1/files/{path}    -> FileDoc
 *   GET /v1/search?q=       -> SearchResult[]
 *   GET /admin/index/status -> IndexStatus[]
 *   POST /v1/files          -> UploadResponse
 *   references SSE event    -> Citation[]
 */

/** A node in the vault document tree. */
export interface TreeNode {
  /** File or directory name (basename). */
  name: string
  type: 'dir' | 'file'
  /** Path relative to the vault root, POSIX separators. */
  path: string
  /** Children of a directory node. */
  children?: TreeNode[]
  /** Frontmatter tags of a file node. */
  tags?: string[]
  size_bytes?: number
  updated_at?: string
}

/** A markdown document with its frontmatter. */
export interface FileDoc {
  file_path: string
  /** Markdown body, frontmatter stripped. */
  content: string
  frontmatter: Record<string, unknown>
  size_bytes: number
  updated_at: string
}

/** One matching line inside a searched file. */
export interface SearchMatch {
  /** 1-based line number, relative to the document body. */
  line: number
  /** The matching line, truncated to 200 characters. */
  text: string
}

/** One hit of the global search. */
export interface SearchResult {
  file_path: string
  title: string
  matches: SearchMatch[]
}

/** A citation extracted from the `references` SSE event. */
export interface Citation {
  file_path: string
  heading: string
  chunk_id: string
  score: number
  /** Character offset of the quoted chunk inside the source markdown. */
  start_offset: number
  /** Character offset (exclusive) of the quoted chunk. */
  end_offset: number
  /** The quoted passage itself — shown in the hover card / sources drawer. */
  text: string
}

export type ChatRole = 'user' | 'assistant' | 'system'

/** One chat message in the right-hand panel. */
export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  /** References attached to an assistant message. */
  citations?: Citation[]
  /** True while the message is still streaming in. */
  streaming?: boolean
}

/** Result of `POST /v1/files`. */
export interface UploadResponse {
  id: string
  status: string
  parser: string
  chunks: number
  file_path?: string | null
  error?: string | null
}

/** One row of `GET /admin/index/status`. */
export interface IndexStatus {
  file_path: string
  file_hash: string
  chunk_count: number
  status: string
  updated_at: string
  error?: string | null
}

/** A character range to highlight inside a document. */
export interface HighlightRange {
  start: number
  end: number
}
