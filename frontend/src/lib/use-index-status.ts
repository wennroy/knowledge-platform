import { useCallback, useEffect, useState } from 'react'

import { getIndexStatus } from '../api/client'
import type { IndexStatus } from '../api/types'

/** Index status per vault-relative path. */
export type IndexStatusMap = Map<string, IndexStatus>

export interface IndexStatusState {
  /** One row per indexed document, as reported by the backend. */
  rows: IndexStatus[]
  /** Re-runs the request (used after an upload). */
  refresh: () => void
}

/**
 * Maps the backend's index-status rows onto vault-relative paths.
 *
 * The backend used to report absolute paths and now reports vault-relative
 * ones, so both are accepted: a row matches a tree path when it *is* that
 * path or when it ends with `/<path>`. The longest match wins, so
 * `team/api.md` is preferred over `api.md`.
 */
export function mapIndexStatus(
  rows: IndexStatus[],
  paths: string[],
): IndexStatusMap {
  const map: IndexStatusMap = new Map()
  for (const row of rows) {
    const absolute = row.file_path.replace(/\\/g, '/')
    let best: string | null = null
    for (const path of paths) {
      if (absolute === path || absolute.endsWith(`/${path}`)) {
        if (best === null || path.length > best.length) {
          best = path
        }
      }
    }
    if (best !== null) {
      map.set(best, row)
    }
  }
  return map
}

/**
 * Loads `GET /admin/index/status`.
 *
 * The mapping onto the document tree is done by the caller, which knows the
 * relative paths.
 */
export function useIndexStatus(): IndexStatusState {
  const [rows, setRows] = useState<IndexStatus[]>([])
  const [nonce, setNonce] = useState(0)

  const refresh = useCallback(() => {
    setNonce((value) => value + 1)
  }, [])

  useEffect(() => {
    let cancelled = false
    getIndexStatus()
      .then((items) => {
        if (!cancelled) {
          setRows(items)
        }
      })
      .catch(() => {
        // A missing /admin endpoint must not break the tree — the markers
        // are an extra, not a requirement.
        if (!cancelled) {
          setRows([])
        }
      })
    return () => {
      cancelled = true
    }
  }, [nonce])

  return { rows, refresh }
}
