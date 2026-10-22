import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'

import { deleteFile, getHealth } from './api/client'
import type {
  ChatMessage,
  Citation,
  SearchMatch,
  SearchResult,
  TreeNode,
  UploadResponse,
} from './api/types'
import { useDocument } from './hooks/useDocument'
import { useSearch } from './hooks/useSearch'
import { useVaultTree } from './hooks/useVaultTree'
import type { LoadStatus } from './lib/load'
import type { DocTarget } from './lib/reader-target'
import { useChat } from './lib/use-chat'
import { useIndexStatus, mapIndexStatus, type IndexStatusMap } from './lib/use-index-status'
import { buildWikilinkIndex, type WikilinkIndex } from './lib/wikilink-index'
import type { GatewayStatus } from './components/TopBar'

export type MobileTab = 'tree' | 'reader' | 'chat'

export interface WorkspaceValue {
  tree: ReturnType<typeof useVaultTree>['tree']
  treeStatus: LoadStatus
  treeError: string | null
  reloadTree: () => void
  /** Re-loads the document tree and the index status (after an upload). */
  refreshTree: () => void
  /** Index status per vault-relative path. */
  indexStatus: IndexStatusMap
  currentPath: string | null
  doc: ReturnType<typeof useDocument>['doc']
  docStatus: LoadStatus
  docError: string | null
  reloadDoc: () => void
  target: DocTarget | null
  searchResults: SearchResult[]
  searchStatus: LoadStatus
  searchError: string | null
  messages: ChatMessage[]
  citations: Citation[]
  /** Error message per assistant message id. */
  messageErrors: Record<string, string>
  /** Maps a `[[wikilink]]` target onto a vault path. */
  wikilinkIndex: WikilinkIndex
  isStreaming: boolean
  uploadOpen: boolean
  chatOpen: boolean
  mobileTab: MobileTab
  gatewayStatus: GatewayStatus
  selectPath: (path: string) => void
  runSearch: (query: string) => void
  openSearchResult: (result: SearchResult, match?: SearchMatch) => void
  sendMessage: (text: string) => void
  /** Aborts the running answer. */
  stopStreaming: () => void
  jumpToCitation: (citation: Citation) => void
  setUploadOpen: (open: boolean) => void
  setChatOpen: (open: boolean) => void
  setMobileTab: (tab: MobileTab) => void
  /** Called after an upload finished — refreshes the tree and index status. */
  handleUploaded: (result: UploadResponse) => void
  /** Deletes a document from the vault and refreshes the tree. */
  deleteDocument: (path: string) => Promise<void>
}

const WorkspaceContext = createContext<WorkspaceValue | null>(null)

export function useWorkspace(): WorkspaceValue {
  const value = useContext(WorkspaceContext)
  if (!value) {
    throw new Error('useWorkspace must be used inside <WorkspaceContext.Provider>')
  }
  return value
}

/**
 * The shared workspace state: the document tree, the open document, the
 * global search and the (still static) chat panel.
 */
export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { tree, treeStatus, treeError, reloadTree, refresh } = useVaultTree()
  const {
    currentPath,
    doc,
    docStatus,
    docError,
    target,
    selectPath,
    reloadDoc,
    jumpToCitation,
    setTarget,
  } = useDocument()
  const { searchResults, searchStatus, searchError, runSearch, openSearchResult } =
    useSearch(selectPath, setTarget)
  const { rows: indexRows, refresh: refreshIndexStatus } = useIndexStatus()

  // ------------------------------------------------------------------ chat (F3)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)
  const [mobileTab, setMobileTab] = useState<MobileTab>('reader')
  const [gatewayStatus, setGatewayStatus] = useState<GatewayStatus>('unknown')

  /**
   * The vault-relative paths of every file in the tree.
   *
   * The index stores absolute paths, so the `references` event may carry an
   * absolute `file_path`; the chat maps it back onto the relative form.
   */
  const vaultPaths = useMemo(() => {
    const paths: string[] = []
    const walk = (nodes: TreeNode[]) => {
      for (const node of nodes ?? []) {
        if (node.type === 'file') {
          paths.push(node.path)
        }
        if (node.children) {
          walk(node.children)
        }
      }
    }
    walk(tree)
    return paths
  }, [tree])

  const { messages, messageErrors, isStreaming, sendMessage, stopStreaming } =
    useChat(vaultPaths)

  /** Maps a `[[wikilink]]` target onto a vault path. */
  const wikilinkIndex = useMemo(
    () => buildWikilinkIndex(vaultPaths),
    [vaultPaths],
  )

  /**
   * Index status per vault-relative path.
   *
   * Documents that are not indexed at all are simply absent from the map.
   */
  const indexStatus = useMemo<IndexStatusMap>(
    () => mapIndexStatus(indexRows, vaultPaths),
    [indexRows, vaultPaths],
  )

  /** Reload the tree *and* the index status (after an upload). */
  const refreshTree = useCallback(() => {
    refresh()
    refreshIndexStatus()
  }, [refresh, refreshIndexStatus])

  /** The upload finished — pick up the new document in the tree. */
  const handleUploaded = useCallback(
    (_result: UploadResponse) => {
      refreshTree()
    },
    [refreshTree],
  )

  /** Remove a document from the vault (and from the index). */
  const deleteDocument = useCallback(
    async (path: string) => {
      await deleteFile(path)
      refreshTree()
    },
    [refreshTree],
  )

  // Switching documents aborts a running answer.
  const firstPathRef = useRef(true)
  useEffect(() => {
    if (firstPathRef.current) {
      firstPathRef.current = false
      return
    }
    stopStreaming()
  }, [currentPath, stopStreaming])

  // Backend liveness for the status dot in the top bar.
  useEffect(() => {
    let alive = true
    const check = () => {
      getHealth()
        .then((ok) => {
          if (alive) {
            setGatewayStatus(ok ? 'online' : 'offline')
          }
        })
        .catch(() => {
          if (alive) {
            setGatewayStatus('offline')
          }
        })
    }
    check()
    const timer = window.setInterval(check, 30000)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [])

  const value = useMemo<WorkspaceValue>(
    () => ({
      tree,
      treeStatus,
      treeError,
      reloadTree,
      refreshTree,
      indexStatus,
      currentPath,
      doc,
      docStatus,
      docError,
      reloadDoc,
      target,
      searchResults,
      searchStatus,
      searchError,
      messages,
      citations: messages.flatMap((message) => message.citations ?? []),
      messageErrors,
      wikilinkIndex,
      isStreaming,
      uploadOpen,
      chatOpen,
      mobileTab,
      gatewayStatus,
      selectPath,
      runSearch,
      openSearchResult,
      sendMessage,
      stopStreaming,
      jumpToCitation,
      setUploadOpen,
      setChatOpen,
      setMobileTab,
      handleUploaded,
      deleteDocument,
    }),
    [
      tree,
      treeStatus,
      treeError,
      reloadTree,
      refreshTree,
      indexStatus,
      currentPath,
      doc,
      docStatus,
      docError,
      reloadDoc,
      target,
      searchResults,
      searchStatus,
      searchError,
      messages,
      messageErrors,
      wikilinkIndex,
      isStreaming,
      uploadOpen,
      chatOpen,
      mobileTab,
      gatewayStatus,
      selectPath,
      runSearch,
      openSearchResult,
      sendMessage,
      stopStreaming,
      jumpToCitation,
      handleUploaded,
      deleteDocument,
    ],
  )

  return (
    <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>
  )
}
