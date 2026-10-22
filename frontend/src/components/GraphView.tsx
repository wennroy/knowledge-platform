import { useEffect, useState } from 'react'

export type GraphViewProps = Record<string, never>

interface GraphNode {
  id: string
  label?: string
  title?: string | null
  tags?: string[]
  size?: number
  summary?: string
  dangling?: boolean
}

interface GraphEdge {
  source: string
  target: string
  type: string
  weight: number
}

interface GraphPayload {
  nodes?: GraphNode[]
  edges?: GraphEdge[]
  degraded?: boolean
  note?: string
}

/**
 * Knowledge-graph view.
 *
 * F1 placeholder: it loads the `GET /graph` payload and renders a plain
 * node/edge summary. The force-directed canvas is ported over from the
 * standalone `graph-viewer/` SPA in F4.
 */
export function GraphView(_props: GraphViewProps) {
  const [graph, setGraph] = useState<GraphPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    fetch('/graph')
      .then((response) => {
        if (!response.ok) {
          throw new Error(`${response.status} ${response.statusText}`)
        }
        return response.json() as Promise<GraphPayload>
      })
      .then((payload) => {
        if (!cancelled) {
          setGraph(payload)
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

  const nodes = graph?.nodes ?? []
  const edges = graph?.edges ?? []

  return (
    <div className="graph-view">
      <div className="pane-header">
        <span className="pane-title">知识图谱</span>
        <span className="pane-hint">
          {nodes.length} 个节点 · {edges.length} 条边
        </span>
      </div>

      {loading ? <p className="empty-hint">正在加载图谱…</p> : null}
      {error ? <p className="error-text">{error}</p> : null}
      {graph?.degraded ? <p className="empty-hint">{graph.note}</p> : null}

      {!loading && !error ? (
        <div className="graph-placeholder">
          <p className="empty-hint">
            力导向图谱将在 F4 阶段从旧的 graph-viewer 迁入。当前先列出节点。
          </p>
          <ul className="graph-node-list">
            {nodes.map((node) => (
              <li key={node.id} className="graph-node-item">
                <span className="graph-node-label">{node.label ?? node.id}</span>
                <span className="graph-node-path">{node.id}</span>
                {node.tags && node.tags.length > 0 ? (
                  <span className="graph-node-tags">
                    {node.tags.map((tag) => (
                      <span className="tag" key={tag}>
                        {tag}
                      </span>
                    ))}
                  </span>
                ) : null}
                {node.dangling ? (
                  <span className="tag tag-dangling">未创建</span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}
