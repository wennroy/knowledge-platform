import { useVirtualizer } from '@tanstack/react-virtual'
import { useMemo, useRef, useState } from 'react'

import type { TreeNode } from '../api/types'

export interface DocTreeProps {
  /** The nested tree from `GET /v1/tree`. */
  tree: TreeNode[]
  /** Vault-relative path of the document currently open. */
  currentPath: string | null
  /** Called with the vault-relative path of the clicked file. */
  onSelect: (path: string) => void
}

/** One rendered row of the flattened tree. */
interface FlatRow {
  node: TreeNode
  depth: number
}

const ROW_HEIGHT = 28

/** Flatten the tree into the rows that are actually visible. */
function flatten(tree: TreeNode[], expanded: Set<string>, depth = 0): FlatRow[] {
  const rows: FlatRow[] = []
  for (const node of tree) {
    rows.push({ node, depth })
    if (node.type === 'dir' && expanded.has(node.path) && node.children?.length) {
      rows.push(...flatten(node.children, expanded, depth + 1))
    }
  }
  return rows
}

/**
 * Left-hand document tree.
 *
 * The tree is flattened and rendered through a virtualizer so very large
 * vaults stay smooth (see §6.2 of the plan).
 */
export function DocTree({ tree, currentPath, onSelect }: DocTreeProps) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())
  const scrollRef = useRef<HTMLDivElement>(null)

  const rows = useMemo(() => flatten(tree, expanded), [tree, expanded])

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

  return (
    <div className="doc-tree">
      <div className="pane-header">
        <span className="pane-title">文档</span>
        <span className="pane-hint">{rows.length} 项</span>
      </div>
      <div className="doc-tree-scroll" ref={scrollRef} role="tree">
        {rows.length === 0 ? (
          <p className="empty-hint">知识库为空，先上传一份文档吧。</p>
        ) : (
          <div
            className="doc-tree-inner"
            style={{ height: virtualizer.getTotalSize() }}
          >
            {virtualizer.getVirtualItems().map((item) => {
              const row = rows[item.index]
              const isDir = row.node.type === 'dir'
              const isOpen = expanded.has(row.node.path)
              const isCurrent = row.node.path === currentPath
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
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
