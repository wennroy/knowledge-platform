import { useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';

type GNode = {
  id: string;
  label: string;
  title?: string | null;
  tags: string[];
  size: number;
  summary?: string;
  dangling?: boolean;
};

type GLink = {
  source: string;
  target: string;
  type: 'wikilink' | 'share-tag';
  weight: number;
};

type WireData = {
  nodes: GNode[];
  edges: GLink[];
  degraded?: boolean;
  note?: string;
};

// react-force-graph-2d expects `links`, not `edges` (which matches d3-force).
type ForceData = {
  nodes: GNode[];
  links: GLink[];
};

const EDGE_COLOR: Record<string, string> = {
  wikilink: '#1e6fd9',
  'share-tag': '#9aa0a6',
};
const NODE_COLOR = '#2b2b2b';
const DANGLE_COLOR = '#b34a4a';

export default function App() {
  const [data, setData] = useState<WireData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hover, setHover] = useState<GNode | null>(null);
  const sizeRef = useRef<{ w: number; h: number }>({ w: 600, h: 480 });
  const wrapRef = useRef<HTMLDivElement | null>(null);

  // re-frame wire payload as the d3-style shape that react-force-graph-2d
  // requires (nodes / links instead of nodes / edges).
  const forceData = useMemo<ForceData | null>(() => {
    if (!data) return null;
    return { nodes: data.nodes, links: data.edges };
  }, [data]);

  useEffect(() => {
    fetch('/graph')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((j: WireData) => setData(j))
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!wrapRef.current) return;
    const ro = new ResizeObserver(() => {
      if (!wrapRef.current) return;
      const rect = wrapRef.current.getBoundingClientRect();
      sizeRef.current = { w: rect.width, h: rect.height };
    });
    ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, []);

  const linkColor = useMemo(() => (l: object) => {
    const t = (l as GLink).type;
    return EDGE_COLOR[t] ?? '#999';
  }, []);

  if (error) {
    return (
      <div style={styles.status}>Graph load failed: {error}</div>
    );
  }
  if (!data || !forceData) {
    return <div style={styles.status}>Loading graph…</div>;
  }
  if (data.degraded) {
    return (
      <div ref={wrapRef} style={styles.root}>
        <div style={styles.banner}>
          Degraded mode: {data.note ?? 'rendering top-N by size'}
        </div>
        <Graph
          data={forceData}
          hover={hover}
          setHover={setHover}
          sizeRef={sizeRef}
          linkColor={linkColor}
        />
      </div>
    );
  }
  return (
    <div ref={wrapRef} style={styles.root}>
      <Graph
        data={forceData}
        hover={hover}
        setHover={setHover}
        sizeRef={sizeRef}
        linkColor={linkColor}
      />
    </div>
  );
}

function Graph({
  data,
  hover,
  setHover,
  sizeRef,
  linkColor,
}: {
  data: ForceData;
  hover: GNode | null;
  setHover: (n: GNode | null) => void;
  sizeRef: React.MutableRefObject<{ w: number; h: number }>;
  linkColor: (l: object) => string;
}): JSX.Element {
  return (
    <>
      <ForceGraph2D
        graphData={data}
        width={sizeRef.current.w}
        height={sizeRef.current.h}
        linkColor={linkColor}
        linkWidth={(l: object) => Math.max(1, Math.min(4, (l as GLink).weight))}
        nodeLabel={(n: object) => {
          const node = n as GNode;
          const parts = [node.title ?? node.label];
          if (node.summary) parts.push(node.summary);
          return parts.join('\n\n');
        }}
        nodeColor={(n: object) =>
          (n as GNode).dangling ? DANGLE_COLOR : NODE_COLOR
        }
        nodeRelSize={4}
        nodeVal={(n: object) => Math.max(1, (n as GNode).size / 50)}
        onNodeHover={(n) => setHover((n as GNode) ?? null)}
        cooldownTicks={120}
      />
      {hover ? (
        <div style={styles.hover}>
          <strong>{hover.title ?? hover.label}</strong>
          <div style={styles.hoverSub}>{hover.id}</div>
          {hover.summary ? (
            <div style={styles.hoverSummary}>{hover.summary}</div>
          ) : null}
          {hover.tags.length ? (
            <div style={styles.hoverTags}>
              {hover.tags.map((t) => (
                <span key={t} style={styles.tag}>
                  {t}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

const styles: Record<string, React.CSSProperties> = {
  root: {
    position: 'absolute',
    inset: 0,
    background: '#fafafa',
    fontFamily:
      'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
    color: '#222',
  },
  status: { padding: 24, fontSize: 14 },
  banner: {
    background: '#fff3cd',
    borderBottom: '1px solid #f0c36d',
    color: '#5c3e00',
    padding: '6px 12px',
    fontSize: 13,
  },
  hover: {
    position: 'absolute',
    right: 16,
    top: 16,
    background: 'rgba(255,255,255,0.95)',
    border: '1px solid #ccc',
    borderRadius: 6,
    padding: 10,
    maxWidth: 320,
    fontSize: 12,
    boxShadow: '0 4px 14px rgba(0,0,0,0.08)',
    pointerEvents: 'none',
  },
  hoverSub: { color: '#666', marginTop: 4, fontSize: 11 },
  hoverSummary: { marginTop: 6, color: '#333', whiteSpace: 'pre-wrap' },
  hoverTags: { marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 4 },
  tag: {
    background: '#eef',
    color: '#335',
    borderRadius: 10,
    padding: '1px 8px',
    fontSize: 11,
  },
};
