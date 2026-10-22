import { useCallback, useRef } from 'react'
import ForceGraph2D, {
  type ForceGraphMethods,
  type LinkObject,
  type NodeObject,
} from 'react-force-graph-2d'

import type { ForceData, GLink, GNode } from '../lib/graph-types'

/** Node type as the library sees it (the wire type plus layout fields). */
type NodeT = NodeObject<GNode>
/** Link type as the library sees it. */
type LinkT = LinkObject<GNode, GLink>

/** Edge colours by edge type. */
const EDGE_COLOR: Record<string, string> = {
  wikilink: '#1e6fd9',
  'share-tag': '#9aa0a6',
}

const LIGHT = {
  node: '#2b2b2b',
  dangling: '#b34a4a',
  label: '#1a1a1a',
}

const DARK = {
  node: '#c9d1d9',
  dangling: '#ff6b6b',
  label: '#e6e9ef',
}

export interface ForceGraphCanvasProps {
  /** The d3-style graph payload. */
  data: ForceData
  /** Canvas width in CSS pixels. */
  width: number
  /** Canvas height in CSS pixels. */
  height: number
  /** True when the dark colour scheme is active. */
  dark: boolean
  /** Called when the user clicks a node. */
  onNodeClick: (node: GNode) => void
  /** Called with the hovered node (or `null` when the pointer leaves). */
  onNodeHover: (node: GNode | null) => void
}

/**
 * The force-directed canvas.
 *
 * Ported from the standalone `graph-viewer/` SPA. Three details of that
 * implementation are load-bearing and must not be "simplified" away:
 *
 *  1. `nodeCanvasObject` **replaces** the library's default node drawing
 *     entirely — the circle has to be drawn here as well, otherwise the
 *     nodes are invisible and only their labels remain.
 *  2. The canvas size comes in as a prop (state in the parent) — a ref
 *     would not trigger a re-render and the canvas would stay at its
 *     initial 600x480.
 *  3. The wrapper div is rendered by the parent unconditionally, so the
 *     ResizeObserver can attach to it.
 */
export function ForceGraphCanvas({
  data,
  width,
  height,
  dark,
  onNodeClick,
  onNodeHover,
}: ForceGraphCanvasProps) {
  const fgRef = useRef<ForceGraphMethods<NodeT, LinkT> | undefined>(undefined)
  const colors = dark ? DARK : LIGHT

  const linkColor = useCallback((link: LinkT) => EDGE_COLOR[link.type] ?? '#999', [])

  const linkWidth = useCallback(
    (link: LinkT) => Math.max(1, Math.min(4, link.weight)),
    [],
  )

  const nodeColor = useCallback(
    (node: NodeT) => (node.dangling ? colors.dangling : colors.node),
    [colors.dangling, colors.node],
  )

  const nodeVal = useCallback((node: NodeT) => Math.max(1, node.size / 50), [])

  const nodeLabel = useCallback((node: NodeT) => {
    const parts = [node.title ?? node.label]
    if (node.summary) {
      parts.push(node.summary)
    }
    return parts.join('\n\n')
  }, [])

  return (
    <ForceGraph2D<GNode, GLink>
      ref={fgRef}
      graphData={data}
      width={width}
      height={height}
      onEngineStop={() => {
        // Fit the whole graph into view once the layout settles.
        fgRef.current?.zoomToFit(600, 80)
      }}
      linkColor={linkColor}
      linkWidth={linkWidth}
      nodeColor={nodeColor}
      nodeLabel={nodeLabel}
      nodeRelSize={6}
      nodeVal={nodeVal}
      nodeCanvasObject={(node, ctx, scale) => {
        // Providing nodeCanvasObject replaces the library's default node
        // drawing entirely, so we must draw the circle ourselves as well as
        // the label (react-force-graph-2d draws no labels by default).
        const x = node.x ?? 0
        const y = node.y ?? 0
        const r = Math.max(3.5, Math.min(11, 1.5 + Math.sqrt(node.size) / 5))

        ctx.beginPath()
        ctx.arc(x, y, r, 0, 2 * Math.PI)
        ctx.fillStyle = node.dangling ? colors.dangling : colors.node
        ctx.fill()
        if (node.dangling) {
          ctx.strokeStyle = colors.dangling
          ctx.lineWidth = 1 / scale
          ctx.stroke()
        }

        const label = node.title ?? node.label
        const fontSize = Math.max(11 / scale, 3.2)
        ctx.font = `${fontSize}px system-ui, -apple-system, "Segoe UI", sans-serif`
        ctx.textAlign = 'center'
        ctx.textBaseline = 'top'
        ctx.fillStyle = colors.label
        ctx.fillText(label, x, y + r + 1.5 / scale)
      }}
      onNodeClick={(node) => onNodeClick(node as GNode)}
      onNodeHover={(node) => onNodeHover((node as GNode | null) ?? null)}
      cooldownTicks={120}
    />
  )
}
