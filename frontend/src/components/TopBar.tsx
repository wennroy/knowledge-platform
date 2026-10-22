import { useState } from 'react'
import { NavLink } from 'react-router-dom'

export type GatewayStatus = 'unknown' | 'online' | 'offline'

export interface TopBarProps {
  /** Called with the query when the user submits the search box. */
  onSearch?: (query: string) => void
  /** Opens the upload dialog. */
  onUpload?: () => void
  /** Opens the chat panel when it is collapsed into a drawer (< 1100px). */
  onToggleChat?: () => void
  /** Backend/gateway health, shown as a dot on the right. */
  gatewayStatus?: GatewayStatus
}

/**
 * Application header: search, upload, graph entry point, gateway status.
 */
export function TopBar({
  onSearch,
  onUpload,
  onToggleChat,
  gatewayStatus = 'unknown',
}: TopBarProps) {
  const [query, setQuery] = useState('')

  return (
    <header className="topbar">
      <div className="topbar-brand">
        <span className="topbar-logo" aria-hidden="true">
          ◈
        </span>
        <span className="topbar-title">Knowledge Platform</span>
      </div>

      <form
        className="topbar-search"
        role="search"
        onSubmit={(event) => {
          event.preventDefault()
          onSearch?.(query)
        }}
      >
        <input
          className="topbar-search-input"
          type="search"
          placeholder="搜索文档…"
          value={query}
          aria-label="全局搜索"
          onChange={(event) => setQuery(event.target.value)}
        />
        <button type="submit" className="btn btn-ghost">
          搜索
        </button>
      </form>

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
