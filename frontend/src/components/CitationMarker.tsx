import { useState } from 'react'

import type { Citation } from '../api/types'

export interface CitationMarkerProps {
  /** The reference this marker points at. */
  citation: Citation
  /** 1-based index of the reference in the message. */
  index: number
  /** Called when the marker is clicked. */
  onClick: (citation: Citation) => void
}

/**
 * Inline citation marker (`[1]`) with a hover card showing the quoted
 * passage from the source document.
 */
export function CitationMarker({ citation, index, onClick }: CitationMarkerProps) {
  const [open, setOpen] = useState(false)

  return (
    <span
      className="citation-marker"
      role="button"
      tabIndex={0}
      title={`${citation.file_path}${citation.heading ? ` › ${citation.heading}` : ''}`}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      onClick={() => onClick(citation)}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onClick(citation)
        }
      }}
    >
      [{index}]
      {open ? (
        <span className="citation-card" role="tooltip">
          <span className="citation-card-path">{citation.file_path}</span>
          {citation.heading ? (
            <span className="citation-card-heading">{citation.heading}</span>
          ) : null}
          <span className="citation-card-text">{citation.text}</span>
          <span className="citation-card-meta">
            score {citation.score.toFixed(2)}
          </span>
        </span>
      ) : null}
    </span>
  )
}
