import { useCallback, useRef, useState } from 'react'

import { search as searchApi } from '../api/client'
import type { SearchMatch, SearchResult } from '../api/types'
import { errorMessage, type LoadStatus } from '../lib/load'
import type { DocTarget } from '../lib/reader-target'

export interface VaultSearch {
  searchResults: SearchResult[]
  searchStatus: LoadStatus
  searchError: string | null
  runSearch: (query: string) => void
  openSearchResult: (result: SearchResult, match?: SearchMatch) => void
}

/**
 * Global search (`GET /v1/search`).
 *
 * Only the newest request may write to the state — the response of a slow
 * request must never overwrite the results of a newer one.
 */
export function useSearch(
  selectPath: (path: string) => void,
  setTarget: (target: DocTarget | null) => void,
): VaultSearch {
  const [searchResults, setSearchResults] = useState<SearchResult[]>([])
  const [searchStatus, setSearchStatus] = useState<LoadStatus>('idle')
  const [searchError, setSearchError] = useState<string | null>(null)
  const seqRef = useRef(0)

  const runSearch = useCallback((query: string) => {
    const trimmed = query.trim()
    const seq = ++seqRef.current
    if (!trimmed) {
      setSearchResults([])
      setSearchStatus('idle')
      setSearchError(null)
      return
    }
    setSearchStatus('loading')
    setSearchError(null)
    searchApi(trimmed)
      .then((results) => {
        if (seq !== seqRef.current) {
          return
        }
        setSearchResults(results)
        setSearchStatus('ready')
      })
      .catch((error: unknown) => {
        if (seq !== seqRef.current) {
          return
        }
        setSearchResults([])
        setSearchStatus('error')
        setSearchError(errorMessage(error, '搜索失败'))
      })
  }, [])

  const openSearchResult = useCallback(
    (result: SearchResult, match?: SearchMatch) => {
      selectPath(result.file_path)
      // The hit is a line of the document — the reader scrolls to it.
      // `selectPath` clears the target, so it is set afterwards.
      setTarget({
        mode: 'exact',
        line: match?.line,
        text: match?.text,
      })
    },
    [selectPath, setTarget],
  )

  return { searchResults, searchStatus, searchError, runSearch, openSearchResult }
}
