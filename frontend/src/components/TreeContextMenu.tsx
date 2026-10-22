import { useEffect, useRef } from 'react'

/** The position and target of the right-click menu. */
export interface ContextMenu {
  x: number
  y: number
  path: string
  name: string
}

export interface TreeContextMenuProps {
  /** The open menu, or `null` when it is closed. */
  menu: ContextMenu | null
  /** Called when the menu should close. */
  onClose: () => void
  /** Called with the path and name of the document to delete. */
  onDelete: (path: string, name: string) => void
}

/**
 * The right-click menu of the document tree.
 *
 * Closes on a click outside of it or on Escape.
 */
export function TreeContextMenu({ menu, onClose, onDelete }: TreeContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menu) {
      return
    }
    const onPointerDown = (event: PointerEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        onClose()
      }
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose()
      }
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [menu, onClose])

  if (!menu) {
    return null
  }

  return (
    <div
      className="ctx-menu"
      ref={menuRef}
      style={{ left: menu.x, top: menu.y }}
      role="menu"
    >
      <button
        type="button"
        role="menuitem"
        className="ctx-menu-item"
        onClick={() => onDelete(menu.path, menu.name)}
      >
        删除文档
      </button>
    </div>
  )
}
