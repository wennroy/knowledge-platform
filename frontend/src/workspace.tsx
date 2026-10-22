import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { getHealth } from './api/client'
import type { ChatMessage, Citation, SearchMatch, SearchResult } from './api/types'
import { useDocument } from './hooks/useDocument'
import { useSearch } from './hooks/useSearch'
import { useVaultTree } from './hooks/useVaultTree'
import type { LoadStatus } from './lib/load'
import type { DocTarget } from './lib/reader-target'
import type { GatewayStatus } from './components/TopBar'

export type MobileTab = 'tree' | 'reader' | 'chat'

export interface WorkspaceValue {
  tree: ReturnType<typeof useVaultTree>['tree']
  treeStatus: LoadStatus
  treeError: string | null
  reloadTree: () => void
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
  isStreaming: boolean
  uploadOpen: boolean
  chatOpen: boolean
  mobileTab: MobileTab
  gatewayStatus: GatewayStatus
  selectPath: (path: string) => void
  runSearch: (query: string) => void
  openSearchResult: (result: SearchResult, match?: SearchMatch) => void
  sendMessage: (text: string) => void
  jumpToCitation: (citation: Citation) => void
  setUploadOpen: (open: boolean) => void
  setChatOpen: (open: boolean) => void
  setMobileTab: (tab: MobileTab) => void
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
  const { tree, treeStatus, treeError, reloadTree } = useVaultTree()
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

  // ------------------------------------------------------------------ chat (F3)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isStreaming] = useState(false)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)
  const [mobileTab, setMobileTab] = useState<MobileTab>('reader')
  const [gatewayStatus, setGatewayStatus] = useState<GatewayStatus>('unknown')

  const sendMessage = useCallback((text: string) => {
    // F3: stream the answer via `fetchEventSource` and collect the
    // `references` event into `citations`.
    setMessages((previous) => [
      ...previous,
      { id: `m-${previous.length + 1}`, role: 'user', content: text },
      {
        id: `m-${previous.length + 2}`,
        role: 'assistant',
        content: '（占位回答：F3 阶段接入 SSE 流式输出与行内引用。）',
      },
    ])
  }, [])

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
      isStreaming,
      uploadOpen,
      chatOpen,
      mobileTab,
      gatewayStatus,
      selectPath,
      runSearch,
      openSearchResult,
      sendMessage,
      jumpToCitation,
      setUploadOpen,
      setChatOpen,
      setMobileTab,
    }),
    [
      tree,
      treeStatus,
      treeError,
      reloadTree,
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
      isStreaming,
      uploadOpen,
      chatOpen,
      mobileTab,
      gatewayStatus,
      selectPath,
      runSearch,
      openSearchResult,
      sendMessage,
      jumpToCitation,
    ],
  )

  return (
    <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>
  )
}
