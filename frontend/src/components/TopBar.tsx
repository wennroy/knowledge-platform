import { useEffect, useRef, useState, type FormEvent } from 'react'
import { NavLink } from 'react-router-dom'

import type { SearchMatch, SearchResult } from '../api/types'
import type { LoadStatus } from '../lib/load'

export type GatewayStatus = 'unknown' | 'online' | 'offline'

export interface TopBarProps {
  /** Called with the query when the user types (debounced) or submits. */
  onSearch?: (query: string) => void
  /** Results of the last search. */
  results?: SearchResult[]
  /** Lifecycle of the search request. */
  searchStatus?: LoadStatus
  /** Error message of the failed search request. */
  searchError?: string | null
  /** Called when the user picks a search result. */
  onSelectResult?: (result: SearchResult, match?: SearchMatch) => void
  /** Opens the upload dialog. */
  onUpload?: () => void
  /** Opens the chat panel when it is collapsed into a drawer (< 1100px). */
  onToggleChat?: () => void
  /** Backend/gateway health, shown as a dot on the right. */
  gatewayStatus?: GatewayStatus
}

const DEBOUNCE_MS = 300

/**
 * Application header: search, upload, graph entry point, gateway status.
 *
 * The search box talks to `GET /v1/search` — every keystroke is debounced by
 * 300 ms, and an empty query clears the results without hitting the API.
 */
export function TopBar({
  onSearch,
  results = [],
  searchStatus = 'idle',
  searchError = null,
  onSelectResult,
  onUpload,
  onToggleChat,
  gatewayStatus = 'unknown',
}: TopBarProps) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const timerRef = useRef<number | null>(null)

  // Debounce: the request is sent 300 ms after the last keystroke.
  useEffect(() => {
    const trimmed = query.trim()
    if (!trimmed) {
      onSearch?.('')
      return
    }
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null
      onSearch?.(trimmed)
    }, DEBOUNCE_MS)
    return () => {
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current)
        timerRef.current = null
      }
    }
  }, [query, onSearch])

  // Close the dropdown when the user clicks outside of it.
  useEffect(() => {
    const onPointerDown = (event: MouseEvent) => {
      if (!wrapperRef.current) {
        return
      }
      if (!wrapperRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onPointerDown)
    return () => document.removeEventListener('mousedown', onPointerDown)
  }, [])

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current)
      timerRef.current = null
    }
    const trimmed = query.trim()
    if (trimmed) {
      onSearch?.(trimmed)
    }
    setOpen(true)
  }

  const showDropdown = open && query.trim().length > 0

  return (
    <header className="topbar">
      <div className="topbar-brand">
        <span className="topbar-logo" aria-hidden="true">
          ◈
        </span>
        <span className="topbar-title">Knowledge Platform</span>
      </div>

      <div className="topbar-search-wrapper" ref={wrapperRef}>
        <form className="topbar-search" role="search" onSubmit={submit}>
          <input
            className="topbar-search-input"
            type="search"
            placeholder="搜索文档…"
            value={query}
            aria-label="全局搜索"
            onChange={(event) => {
              setQuery(event.target.value)
              setOpen(true)
            }}
            onFocus={() => setOpen(true)}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                setOpen(false)
              }
            }}
          />
          <button type="submit" className="btn btn-ghost">
            搜索
          </button>
        </form>

        {showDropdown ? (
          <div className="search-dropdown" role="listbox">
            {searchStatus === 'loading' ? (
              <p className="search-hint">搜索中…</p>
            ) : null}

            {searchStatus === 'error' ? (
              <p className="search-error">搜索失败：{searchError}</p>
            ) : null}

            {searchStatus === 'ready' && results.length === 0 ? (
              <p className="search-hint">没有匹配「{query.trim()}」的文档。</p>
            ) : null}

            {(searchStatus === 'ready' ? results : []).map((result) => (
              <div className="search-item" key={result.file_path}>
                <button
                  type="button"
                  className="search-item-head"
                  onClick={() => {
                    setOpen(false)
                    onSelectResult?.(result)
                  }}
                >
                  <span className="search-item-path">{result.file_path}</span>
                  {result.title ? (
                    <span className="search-item-title">{result.title}</span>
                  ) : null}
                </button>
                {result.matches.map((match) => (
                  <button
                    type="button"
                    className="search-match"
                    key={`${result.file_path}:${match.line}`}
                    onClick={() => {
                      setOpen(false)
                      onSelectResult?.(result, match)
                    }}
                  >
                    <span className="search-match-line">L{match.line}</span>
                    <span className="search-match-text">{match.text}</span>
                  </button>
                ))}
              </div>
            ))}
          </div>
        ) : null}
      </div>

      <nav className="topbar-actions">
        <button type="button" className="btn btn-ghost" onClick={onUpload}>
          上传
        </button>
        <NavLink to="/graph" className="btn btn-ghost">
          图谱
        </NavLink>
        <button
          type="button"
          className="btn btn-ghost only-narrow"
          onClick={onToggleChat}
          aria-label="切换问答面板"
        >
          问答
        </button>
        <span
          className={`gateway-dot gateway-${gatewayStatus}`}
          title={`网关状态: ${gatewayStatus}`}
          aria-label={`网关状态: ${gatewayStatus}`}
        />
      </nav>
    </header>
  )
}
