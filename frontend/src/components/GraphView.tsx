import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import type { ForceData, GNode, WireData } from '../lib/graph-types'
import { usePrefersDark } from '../lib/use-prefers-dark'
import { useWorkspace } from '../workspace'
import { ForceGraphCanvas } from './ForceGraphCanvas'

/**
 * Knowledge-graph view (route `/app/graph`).
 *
 * The force-directed canvas is ported over from the standalone
 * `graph-viewer/` SPA; the API stays on the root path (`/graph`), which is
 * *not* affected by the Vite `base: '/app/'` of the SPA.
 */
export function GraphView() {
  const workspace = useWorkspace()
  const dark = usePrefersDark()
  const [data, setData] = useState<WireData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [hover, setHover] = useState<GNode | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  // The canvas size lives in state, not in a ref: a ref change does not
  // trigger a re-render, so the canvas would stay at its initial 600x480
  // and the graph would be crammed into the top-left corner.
  const [size, setSize] = useState({ w: 600, h: 480 })
  const wrapRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch('/graph')
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status} ${response.statusText}`)
        }
        return response.json() as Promise<WireData>
      })
      .then((payload) => {
        if (!cancelled) {
          setData(payload)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : '加载图谱失败')
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  // The wrapper div is rendered unconditionally (see below), so the observer
  // can attach to it. The effect re-runs when the payload arrives so the
  // canvas picks up the real size of the freshly rendered tree.
  useEffect(() => {
    const element = wrapRef.current
    if (!element) {
      return
    }
    const measure = () => {
      const rect = element.getBoundingClientRect()
      if (rect.width > 0 && rect.height > 0) {
        setSize({ w: rect.width, h: rect.height })
      }
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [data])

  // react-force-graph-2d expects `links`, not `edges`.
  const forceData = useMemo<ForceData | null>(
    () => (data ? { nodes: data.nodes, links: data.edges } : null),
    [data],
  )

  const handleNodeClick = useCallback(
    (node: GNode) => {
      if (node.dangling) {
        setNotice(`目标不存在：${node.id}（该 wikilink 没有对应的文档）`)
        return
      }
      setNotice(null)
      // `selectPath` opens the document and pushes `/doc/<path>`, so the
      // reader, the tree highlight and the URL stay in sync.
      workspace.selectPath(node.id)
    },
    [workspace.selectPath],
  )

  return (
    <div className="graph-view">
      <div className="pane-header">
        <span className="pane-title">知识图谱</span>
        <span className="pane-hint">
          {data ? `${data.nodes.length} 个节点 · ${data.edges.length} 条边` : ''}
        </span>
      </div>

      {data?.degraded ? (
        <div className="graph-banner">
          降级模式：{data.note ?? '仅渲染部分节点'}
        </div>
      ) : null}

      {notice ? <div className="graph-banner graph-banner-warn">{notice}</div> : null}

      <div className="graph-canvas-wrap" ref={wrapRef}>
        {loading ? <p className="empty-hint">正在加载图谱…</p> : null}
        {error ? <p className="error-text">加载图谱失败：{error}</p> : null}

        {forceData ? (
          <ForceGraphCanvas
            data={forceData}
            width={size.w}
            height={size.h}
            dark={dark}
            onNodeClick={handleNodeClick}
            onNodeHover={setHover}
          />
        ) : null}

        {hover ? <GraphHoverCard node={hover} /> : null}
      </div>
    </div>
  )
}

/** The floating card that shows the hovered node's title and summary. */
function GraphHoverCard({ node }: { node: GNode }) {
  return (
    <div className="graph-hover">
      <strong>{node.title ?? node.label}</strong>
      <div className="graph-hover-sub">{node.id}</div>
      {node.summary ? <div className="graph-hover-summary">{node.summary}</div> : null}
      {node.dangling ? <div className="graph-hover-warn">目标不存在</div> : null}
      {node.tags.length > 0 ? (
        <div className="graph-hover-tags">
          {node.tags.map((tag) => (
            <span className="tag" key={tag}>
              {tag}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  )
}

export default GraphView
