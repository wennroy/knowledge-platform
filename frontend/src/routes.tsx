import { Route, Routes } from 'react-router-dom'

import { DocumentRoute, Layout } from './App'
import { GraphView } from './components/GraphView'
import { WorkspaceProvider } from './workspace'

/**
 * Route table.
 *
 * The router is mounted with `basename="/app"` (see main.tsx), so the
 * document workspace lives at `/app/` and the graph at `/app/graph`.
 *
 * `/app/doc/*` is the deep link to a single document — the splat carries the
 * vault-relative path (`/app/doc/team/api-design.md`). The reader picks it
 * up and opens that document, also after a full page reload.
 */
export function AppRoutes() {
  return (
    <WorkspaceProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<DocumentRoute />} />
          <Route path="doc/*" element={<DocumentRoute />} />
          <Route path="graph" element={<GraphView />} />
        </Route>
      </Routes>
    </WorkspaceProvider>
  )
}

export default AppRoutes
