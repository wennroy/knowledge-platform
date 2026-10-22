import type { TreeNode } from '../api/types'

/** One rendered row of the flattened tree. */
export interface FlatRow {
  node: TreeNode
  depth: number
}

/** Flatten the tree into the rows that are actually visible. */
export function flattenTree(
  tree: TreeNode[],
  expanded: Set<string>,
  depth = 0,
): FlatRow[] {
  const rows: FlatRow[] = []
  for (const node of tree) {
    rows.push({ node, depth })
    if (node.type === 'dir' && expanded.has(node.path) && node.children?.length) {
      rows.push(...flattenTree(node.children, expanded, depth + 1))
    }
  }
  return rows
}

/** The directories that contain `path` — used to reveal a deep-linked file. */
export function ancestorsOf(tree: TreeNode[], path: string): string[] {
  const found: string[] = []
  const walk = (nodes: TreeNode[]): boolean => {
    for (const node of nodes) {
      if (node.type === 'file') {
        if (node.path === path) {
          return true
        }
        continue
      }
      found.push(node.path)
      if (walk(node.children ?? [])) {
        return true
      }
      found.pop()
    }
    return false
  }
  walk(tree)
  return found
}
