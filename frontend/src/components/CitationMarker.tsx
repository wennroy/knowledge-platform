import { useRef, useState } from 'react'

import type { Citation } from '../api/types'

export interface CitationMarkerProps {
  /** The reference this marker points at. */
  citation: Citation
  /** 1-based index of the reference in the message. */
  index: number
  /** Called when the marker is clicked. */
  onClick: (citation: Citation) => void
}

/** Rough height of the hover card — used to decide where to open it. */
const CARD_HEIGHT = 190

/** Width of the hover card (see `.citation-card` in the stylesheet). */
const CARD_WIDTH = 300

/** Distance to the right edge of the chat panel. */
const CARD_GAP = 8

/**
 * Inline citation marker (`[1]`) with a hover card showing the quoted
 * passage from the source document.
 */
export function CitationMarker({ citation, index, onClick }: CitationMarkerProps) {
  const [open, setOpen] = useState(false)
  const [below, setBelow] = useState(false)
  const [shift, setShift] = useState(0)
  const markerRef = useRef<HTMLSpanElement>(null)

  /**
   * Open the card.
   *
   * The card opens downwards when there is not enough room above, and it is
   * shifted to the left when it would stick out of the chat panel.
   */
  const show = () => {
    const element = markerRef.current
    if (element) {
      const rect = element.getBoundingClientRect()
      setBelow(rect.top < CARD_HEIGHT)
      const container = element.closest('.chat-messages')
      if (container instanceof HTMLElement) {
        const bounds = container.getBoundingClientRect()
        const maxLeft = bounds.right - CARD_WIDTH - CARD_GAP
        setShift(rect.left > maxLeft ? rect.left - maxLeft : 0)
      }
    }
    setOpen(true)
  }

  return (
    <span
      ref={markerRef}
      className={`citation-marker${below ? ' is-below' : ''}`}
      role="button"
      tabIndex={0}
      title={`${citation.file_path}${citation.heading ? ` › ${citation.heading}` : ''}`}
      onMouseEnter={show}
      onMouseLeave={() => setOpen(false)}
      onFocus={show}
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
        <span
          className="citation-card"
          role="tooltip"
          style={shift ? { transform: `translateX(-${shift}px)` } : undefined}
        >
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
