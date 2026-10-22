/** One entry of the document outline. */
export interface TocItem {
  /** DOM id of the heading element. */
  id: string
  /** Heading text. */
  text: string
  /** Heading level (1 = h1). */
  level: number
}

export interface DocTocProps {
  items: TocItem[]
  /** Called with the id of the heading to scroll to. */
  onSelect: (id: string) => void
}

/**
 * The document outline, extracted from the rendered headings.
 */
export function DocToc({ items, onSelect }: DocTocProps) {
  if (items.length === 0) {
    return null
  }

  return (
    <nav className="reader-toc" aria-label="文档大纲">
      <div className="reader-toc-title">大纲</div>
      <ul>
        {items.map((item) => (
          <li className={`toc-level-${item.level}`} key={item.id}>
            <button type="button" onClick={() => onSelect(item.id)}>
              {item.text}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  )
}
