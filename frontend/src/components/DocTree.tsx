import { useVirtualizer } from '@tanstack/react-virtual'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import type { TreeNode } from '../api/types'
import type { LoadStatus } from '../lib/load'
import type { IndexStatusMap } from '../lib/use-index-status'
import { ancestorsOf, flattenTree } from '../lib/tree'
import { TreeContextMenu, type ContextMenu } from './TreeContextMenu'

export interface DocTreeProps {
  /** The nested tree from `GET /v1/tree`. */
  tree: TreeNode[]
  /** Vault-relative path of the document currently open. */
  currentPath: string | null
  /** Lifecycle of the tree request. */
  status: LoadStatus
  /** Error message of the failed tree request. */
  error: string | null
  /** Re-runs the tree request. */
  onRetry: () => void
  /** Called with the vault-relative path of the clicked file. */
  onSelect: (path: string) => void
  /** Index status per vault-relative path — documents that failed to index
   *  are marked with a red dot. */
  indexStatus?: IndexStatusMap
  /** Deletes a document from the vault (right-click menu). */
  onDelete?: (path: string) => Promise<void>
}

const ROW_HEIGHT = 28

/**
 * Left-hand document tree.
 *
 * The tree is flattened and rendered through a virtualizer so very large
 * vaults stay smooth (see §6.2 of the plan).
 */
export function DocTree({
  tree,
  currentPath,
  status,
  error,
  onRetry,
  onSelect,
  indexStatus,
  onDelete,
}: DocTreeProps) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())
  const [menu, setMenu] = useState<ContextMenu | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const seededRef = useRef(false)

  // Expand the top-level directories by default. With everything collapsed
  // the tree shows two lonely entries ("team", "README.md") and the user
  // cannot tell that `team/` holds documents.
  useEffect(() => {
    if (seededRef.current || tree.length === 0) {
      return
    }
    seededRef.current = true
    setExpanded((previous) => {
      const next = new Set(previous)
      for (const node of tree) {
        if (node.type === 'dir') {
          next.add(node.path)
        }
      }
      return next
    })
  }, [tree])

  const rows = useMemo(() => flattenTree(tree, expanded), [tree, expanded])

  // Reveal the document that is open — also after a deep link.
  useEffect(() => {
    if (!currentPath) {
      return
    }
    const ancestors = ancestorsOf(tree, currentPath)
    if (ancestors.length === 0) {
      return
    }
    setExpanded((previous) => {
      const next = new Set(previous)
      let changed = false
      for (const ancestor of ancestors) {
        if (!next.has(ancestor)) {
          next.add(ancestor)
          changed = true
        }
      }
      return changed ? next : previous
    })
  }, [currentPath, tree])

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
  })

  const toggle = (path: string) => {
    setExpanded((previous) => {
      const next = new Set(previous)
      if (next.has(path)) {
        next.delete(path)
      } else {
        next.add(path)
      }
      return next
    })
  }

  // Close the right-click menu on a click outside of it or on Escape.
  const closeMenu = useCallback(() => setMenu(null), [])

  const handleDelete = async (path: string, name: string) => {
    setMenu(null)
    setDeleteError(null)
    if (!window.confirm(`确定从知识库删除「${name}」吗？此操作不可撤销。`)) {
      return
    }
    if (!onDelete) {
      return
    }
    try {
      await onDelete(path)
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : '删除失败')
    }
  }

  return (
    <div className="doc-tree">
      <div className="pane-header">
        <span className="pane-title">文档</span>
        <span className="pane-hint">
          {status === 'ready' ? `${rows.length} 项` : ''}
        </span>
      </div>

      {status === 'loading' ? (
        <div className="doc-tree-status">
          <div className="skeleton-row" />
          <div className="skeleton-row" />
          <div className="skeleton-row" />
          <p className="empty-hint">正在加载文档树…</p>
        </div>
      ) : null}

      {status === 'error' ? (
        <div className="doc-tree-status">
          <p className="error-text">读取文档树失败：{error}</p>
          <button type="button" className="btn" onClick={onRetry}>
            重试
          </button>
        </div>
      ) : null}

      {status === 'ready' && rows.length === 0 ? (
        <div className="doc-tree-status">
          <p className="empty-hint">
            知识库还是空的。用右上角的「上传」把 Markdown、PDF 或 Office
            文档放进知识库。
          </p>
        </div>
      ) : null}

      {rows.length > 0 ? (
        <div className="doc-tree-scroll" ref={scrollRef} role="tree">
          <div
            className="doc-tree-inner"
            style={{ height: virtualizer.getTotalSize() }}
          >
            {virtualizer.getVirtualItems().map((item) => {
              const row = rows[item.index]
              const isDir = row.node.type === 'dir'
              const isOpen = expanded.has(row.node.path)
              const isCurrent = row.node.path === currentPath
              // A document whose index status is not `ok` (e.g. the embedding
              // gateway was unreachable) is still listed, but marked.
              const status = isDir ? undefined : indexStatus?.get(row.node.path)
              const indexFailed = status !== undefined && status.status !== 'ok'
              return (
                <div
                  key={row.node.path}
                  className={[
                    'tree-row',
                    isDir ? 'tree-row-dir' : 'tree-row-file',
                    isCurrent ? 'is-current' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  style={{
                    transform: `translateY(${item.start}px)`,
                    paddingLeft: 8 + row.depth * 14,
                  }}
                  role="treeitem"
                  aria-expanded={isDir ? isOpen : undefined}
                  aria-selected={isCurrent}
                  onClick={() => {
                    if (isDir) {
                      toggle(row.node.path)
                    } else {
                      onSelect(row.node.path)
                    }
                  }}
                  onContextMenu={(event) => {
                    if (isDir || !onDelete) {
                      return
                    }
                    event.preventDefault()
                    setMenu({
                      x: event.clientX,
                      y: event.clientY,
                      path: row.node.path,
                      name: row.node.name,
                    })
                  }}
                >
                  <span className="tree-icon" aria-hidden="true">
                    {isDir ? (isOpen ? '▾' : '▸') : '·'}
                  </span>
                  <span className="tree-name">{row.node.name}</span>
                  {row.node.tags && row.node.tags.length > 0 ? (
                    <span className="tree-tags">
                      {row.node.tags.slice(0, 2).map((tag) => (
                        <span className="tag" key={tag}>
                          {tag}
                        </span>
                      ))}
                    </span>
                  ) : null}
                  {indexFailed ? (
                    <span
                      className="tree-index-dot"
                      title={
                        status?.error
                          ? `索引失败：${status.error}`
                          : `索引状态：${status?.status ?? 'unknown'}`
                      }
                      aria-label="索引失败"
                    >
                      !
                    </span>
                  ) : null}
                </div>
              )
            })}
          </div>
        </div>
      ) : null}

      {deleteError ? <p className="error-text">删除失败：{deleteError}</p> : null}

      <TreeContextMenu
        menu={menu}
        onClose={closeMenu}
        onDelete={(path, name) => void handleDelete(path, name)}
      />
    </div>
  )
}
