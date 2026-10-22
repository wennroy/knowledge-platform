import { Route, Routes } from 'react-router-dom'

import { DocumentRoute, Layout, WorkspaceProvider } from './App'
import { GraphView } from './components/GraphView'

/**
 * Route table.
 *
 * The router is mounted with `basename="/app"` (see main.tsx), so the
 * document workspace lives at `/app/` and the graph at `/app/graph`.
 */
export function AppRoutes() {
  return (
    <WorkspaceProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<DocumentRoute />} />
          <Route path="graph" element={<GraphView />} />
        </Route>
      </Routes>
    </WorkspaceProvider>
  )
}

export default AppRoutes
