import { useEffect } from 'react'
import { Outlet, useParams } from 'react-router-dom'

import { ChatPanel } from './components/ChatPanel'
import { DocReader } from './components/DocReader'
import { DocTree } from './components/DocTree'
import { TopBar } from './components/TopBar'
import { UploadDialog } from './components/UploadDialog'
import { useWorkspace } from './workspace'

// ------------------------------------------------------------------ routing
/**
 * Keeps the document pane in sync with the `/doc/*` URL.
 *
 * The splat parameter carries the vault-relative path, so a deep link such
 * as `/app/doc/team/api-design.md` opens that document — also after a full
 * page reload. The tree is fetched in parallel, so we wait for it to settle
 * before selecting, which keeps the tree expansion in sync with the reader.
 */
function DocRouteSync() {
  const params = useParams()
  const workspace = useWorkspace()
  const path = params['*'] ?? ''

  useEffect(() => {
    if (!path) {
      return
    }
    if (workspace.treeStatus === 'loading') {
      return
    }
    if (path === workspace.currentPath) {
      return
    }
    workspace.selectPath(path)
  }, [
    path,
    workspace.treeStatus,
    workspace.currentPath,
    workspace.selectPath,
  ])

  return null
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
        onSearch={workspace.runSearch}
        results={workspace.searchResults}
        searchStatus={workspace.searchStatus}
        searchError={workspace.searchError}
        onSelectResult={workspace.openSearchResult}
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
        onUploaded={workspace.handleUploaded}
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
          status={workspace.treeStatus}
          error={workspace.treeError}
          onRetry={workspace.reloadTree}
          onSelect={workspace.selectPath}
          indexStatus={workspace.indexStatus}
          onDelete={workspace.deleteDocument}
        />
      </aside>

      <section className="pane pane-center">
        <DocReader
          doc={workspace.doc}
          status={workspace.docStatus}
          error={workspace.docError}
          onRetry={workspace.reloadDoc}
          target={workspace.target}
          onCitationJump={workspace.jumpToCitation}
          onOpenPath={workspace.selectPath}
          wikilinkIndex={workspace.wikilinkIndex}
        />
      </section>

      <aside className={`pane pane-right${workspace.chatOpen ? ' is-open' : ''}`}>
        <ChatPanel
          messages={workspace.messages}
          onSend={workspace.sendMessage}
          isStreaming={workspace.isStreaming}
          onStop={workspace.stopStreaming}
          onCitationJump={workspace.jumpToCitation}
          messageErrors={workspace.messageErrors}
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

      <DocRouteSync />
    </div>
  )
}
