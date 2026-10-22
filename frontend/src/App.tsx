import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { Outlet } from 'react-router-dom'

import type {
  ChatMessage,
  Citation,
  FileDoc,
  HighlightRange,
  TreeNode,
} from './api/types'
import { ChatPanel } from './components/ChatPanel'
import { DocReader } from './components/DocReader'
import { DocTree } from './components/DocTree'
import { TopBar, type GatewayStatus } from './components/TopBar'
import { UploadDialog } from './components/UploadDialog'

export type MobileTab = 'tree' | 'reader' | 'chat'

export interface WorkspaceValue {
  tree: TreeNode[]
  currentPath: string | null
  doc: FileDoc | null
  highlight: HighlightRange | null
  messages: ChatMessage[]
  citations: Citation[]
  isStreaming: boolean
  uploadOpen: boolean
  chatOpen: boolean
  mobileTab: MobileTab
  gatewayStatus: GatewayStatus
  selectPath: (path: string) => void
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

// ------------------------------------------------------------------ fake data
// F1 ships static data so the three-column skeleton can be reviewed without a
// running backend. F2 replaces these with the `GET /v1/tree` /
// `GET /v1/files/{path}` calls.

const FAKE_TREE: TreeNode[] = [
  {
    name: 'team',
    type: 'dir',
    path: 'team',
    children: [
      {
        name: 'api-design.md',
        type: 'file',
        path: 'team/api-design.md',
        tags: ['api', 'design'],
        size_bytes: 1234,
        updated_at: '2026-10-22T09:00:00+00:00',
      },
      {
        name: 'auth-design.md',
        type: 'file',
        path: 'team/auth-design.md',
        tags: ['auth'],
        size_bytes: 980,
        updated_at: '2026-10-22T09:00:00+00:00',
      },
    ],
  },
  {
    name: 'notes',
    type: 'dir',
    path: 'notes',
    children: [
      {
        name: 'personal',
        type: 'dir',
        path: 'notes/personal',
        children: [
          {
            name: 'todo.md',
            type: 'file',
            path: 'notes/personal/todo.md',
            tags: ['misc'],
            size_bytes: 220,
            updated_at: '2026-10-21T09:00:00+00:00',
          },
        ],
      },
    ],
  },
]

const FAKE_DOC: FileDoc = {
  file_path: 'team/api-design.md',
  content: [
    '# API 设计原则',
    '',
    '## 鉴权',
    '所有接口使用 `Bearer token` 鉴权，网关在转发前校验 token 有效性。',
    '',
    '## 限流',
    '采用令牌桶算法，默认每分钟 600 次请求。',
    '',
    '## 版本',
    '路径前缀 `/v1`，破坏性变更会引入新的主版本号。',
  ].join('\n'),
  frontmatter: { tags: ['api', 'design'], parser: 'markitdown' },
  size_bytes: 1234,
  updated_at: '2026-10-22T09:00:00+00:00',
}

const FAKE_CITATION: Citation = {
  file_path: 'team/api-design.md',
  heading: 'API 设计原则 > 鉴权',
  chunk_id: 'chunk-1',
  score: 0.8732,
  start_offset: 42,
  end_offset: 96,
  text: '所有接口使用 `Bearer token` 鉴权，网关在转发前校验 token 有效性。',
}

const FAKE_MESSAGES: ChatMessage[] = [
  {
    id: 'm-1',
    role: 'user',
    content: '我们的接口鉴权是怎么设计的？',
  },
  {
    id: 'm-2',
    role: 'assistant',
    content:
      '按照《API 设计原则》的约定，所有接口都使用 Bearer token 鉴权，网关会在转发前校验 token 的有效性。',
    citations: [FAKE_CITATION],
  },
]

// ------------------------------------------------------------------ provider
export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [tree] = useState<TreeNode[]>(FAKE_TREE)
  const [currentPath, setCurrentPath] = useState<string | null>(FAKE_DOC.file_path)
  const [doc, setDoc] = useState<FileDoc | null>(FAKE_DOC)
  const [highlight, setHighlight] = useState<HighlightRange | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>(FAKE_MESSAGES)
  const [isStreaming] = useState(false)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)
  const [mobileTab, setMobileTab] = useState<MobileTab>('reader')
  const [gatewayStatus] = useState<GatewayStatus>('unknown')

  const selectPath = useCallback((path: string) => {
    setCurrentPath(path)
    setHighlight(null)
    // On narrow screens the reader is its own tab — show it after a pick.
    setMobileTab('reader')
    // F2: fetch the document with `getFile(path)`.
    setDoc((previous) =>
      previous && previous.file_path === path
        ? previous
        : {
            ...FAKE_DOC,
            file_path: path,
            content: `# ${path}\n\n（占位内容：F2 阶段接入 \`GET /v1/files/{path}\`）`,
          },
    )
  }, [])

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
        citations: [FAKE_CITATION],
      },
    ])
  }, [])

  const jumpToCitation = useCallback((citation: Citation) => {
    setCurrentPath(citation.file_path)
    setHighlight({ start: citation.start_offset, end: citation.end_offset })
    setMobileTab('reader')
  }, [])

  const value = useMemo<WorkspaceValue>(
    () => ({
      tree,
      currentPath,
      doc,
      highlight,
      messages,
      citations: messages.flatMap((message) => message.citations ?? []),
      isStreaming,
      uploadOpen,
      chatOpen,
      mobileTab,
      gatewayStatus,
      selectPath,
      sendMessage,
      jumpToCitation,
      setUploadOpen,
      setChatOpen,
      setMobileTab,
    }),
    [
      tree,
      currentPath,
      doc,
      highlight,
      messages,
      isStreaming,
      uploadOpen,
      chatOpen,
      mobileTab,
      gatewayStatus,
      selectPath,
      sendMessage,
      jumpToCitation,
    ],
  )

  return (
    <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>
  )
}

// ------------------------------------------------------------------ layout
/**
 * Application shell: top bar + routed content.
 *
 * The routed content is the document workspace (three columns) or the graph
 * view, depending on the route.
 */
export function Layout() {
  const workspace = useWorkspace()

  return (
    <div className="app-shell">
      <TopBar
        onSearch={() => {
          // F1: the search box is UI only — the backend endpoint
          // (`GET /v1/search`) is wired in F2.
        }}
        onUpload={() => workspace.setUploadOpen(true)}
        onToggleChat={() => workspace.setChatOpen(!workspace.chatOpen)}
        gatewayStatus={workspace.gatewayStatus}
      />

      <main className="app-main">
        <Outlet />
      </main>

      <UploadDialog
        open={workspace.uploadOpen}
        onClose={() => workspace.setUploadOpen(false)}
        onUploaded={() => {
          // F4: refresh the tree so the new document shows up.
        }}
      />
    </div>
  )
}

/**
 * The document workspace: document tree | reader | chat.
 *
 * Layout: 260px | 1fr | 380px on wide screens. Below 1100px the chat
 * column collapses into a drawer, below 820px the three columns become
 * tabs.
 */
export function DocumentRoute() {
  const workspace = useWorkspace()

  return (
    <div className="app-grid" data-mobile-tab={workspace.mobileTab}>
      <aside className="pane pane-left">
        <DocTree
          tree={workspace.tree}
          currentPath={workspace.currentPath}
          onSelect={workspace.selectPath}
        />
      </aside>

      <section className="pane pane-center">
        <DocReader
          doc={workspace.doc}
          highlight={workspace.highlight}
          onCitationJump={workspace.jumpToCitation}
        />
      </section>

      <aside className={`pane pane-right${workspace.chatOpen ? ' is-open' : ''}`}>
        <ChatPanel
          messages={workspace.messages}
          onSend={workspace.sendMessage}
          isStreaming={workspace.isStreaming}
          onCitationJump={workspace.jumpToCitation}
        />
      </aside>

      <nav className="mobile-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={workspace.mobileTab === 'tree'}
          className={workspace.mobileTab === 'tree' ? 'is-active' : ''}
          onClick={() => workspace.setMobileTab('tree')}
        >
          目录
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={workspace.mobileTab === 'reader'}
          className={workspace.mobileTab === 'reader' ? 'is-active' : ''}
          onClick={() => workspace.setMobileTab('reader')}
        >
          阅读
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={workspace.mobileTab === 'chat'}
          className={workspace.mobileTab === 'chat' ? 'is-active' : ''}
          onClick={() => workspace.setMobileTab('chat')}
        >
          问答
        </button>
      </nav>
    </div>
  )
}
