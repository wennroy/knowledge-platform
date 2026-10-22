import { useCallback, useEffect, useRef, useState } from 'react'

import { getTree } from '../api/client'
import type { TreeNode } from '../api/types'
import { errorMessage, type LoadStatus } from '../lib/load'

export interface VaultTree {
  tree: TreeNode[]
  treeStatus: LoadStatus
  treeError: string | null
  /** Re-runs the tree request. */
  reloadTree: () => void
  /** Alias of `reloadTree` — the name the upload flow uses. */
  refresh: () => void
}

/**
 * Loads the vault document tree (`GET /v1/tree`).
 *
 * The tree is fetched once when the workspace mounts; `reloadTree` (also
 * exposed as `refresh`) re-runs the request — used after an upload.
 */
export function useVaultTree(): VaultTree {
  const [tree, setTree] = useState<TreeNode[]>([])
  const [treeStatus, setTreeStatus] = useState<LoadStatus>('loading')
  const [treeError, setTreeError] = useState<string | null>(null)
  const requestedRef = useRef(false)

  const reloadTree = useCallback(() => {
    setTreeStatus('loading')
    setTreeError(null)
    getTree()
      .then((nodes) => {
        setTree(nodes)
        setTreeStatus('ready')
      })
      .catch((error: unknown) => {
        setTree([])
        setTreeStatus('error')
        setTreeError(errorMessage(error, '读取文档树失败'))
      })
  }, [])

  useEffect(() => {
    // React's StrictMode mounts effects twice in development — the ref keeps
    // that from firing two identical requests.
    if (requestedRef.current) {
      return
    }
    requestedRef.current = true
    reloadTree()
  }, [reloadTree])

  return { tree, treeStatus, treeError, reloadTree, refresh: reloadTree }
}
