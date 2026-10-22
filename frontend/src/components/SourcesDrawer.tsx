import type { Citation } from '../api/types'

export interface SourcesDrawerProps {
  /** References attached to the current answer. */
  citations: Citation[]
  /** Whether the drawer is open. */
  open: boolean
  /** Called when the drawer should close. */
  onClose: () => void
  /** Called when a source is clicked — jumps to the quoted passage. */
  onSelect?: (citation: Citation) => void
}

/**
 * Drawer listing every source referenced by the current answer.
 */
export function SourcesDrawer({ citations, open, onClose, onSelect }: SourcesDrawerProps) {
  if (!open) {
    return null
  }

  return (
    <div className="sources-drawer" role="dialog" aria-label="来源">
      <div className="sources-header">
        <span className="sources-title">来源 ({citations.length})</span>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="关闭来源抽屉">
          ×
        </button>
      </div>
      {citations.length === 0 ? (
        <p className="empty-hint">本次回答没有引用任何文档。</p>
      ) : (
        <ol className="sources-list">
          {citations.map((citation, index) => (
            <li className="source-item" key={`${citation.chunk_id}-${index}`}>
              <div className="source-item-head">
                <span className="source-index">[{index + 1}]</span>
                <span
                  className={`source-path${onSelect ? ' is-clickable' : ''}`}
                  title={citation.file_path}
                  onClick={onSelect ? () => onSelect(citation) : undefined}
                  onKeyDown={
                    onSelect
                      ? (event) => {
                          if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault()
                            onSelect(citation)
                          }
                        }
                      : undefined
                  }
                  role={onSelect ? 'button' : undefined}
                  tabIndex={onSelect ? 0 : undefined}
                >
                  {citation.file_path}
                </span>
              </div>
              {citation.heading ? (
                <div className="source-heading">{citation.heading}</div>
              ) : null}
              <blockquote className="source-text">{citation.text}</blockquote>
              <div className="source-meta">
                score {citation.score.toFixed(2)} · 字符 {citation.start_offset}–
                {citation.end_offset}
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
