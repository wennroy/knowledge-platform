import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import { AppRoutes } from './routes'
import './styles.css'

const container = document.getElementById('root')
if (!container) {
  throw new Error('root container #root is missing from index.html')
}

// The SPA is served by FastAPI under /app/, so the router uses that base.
ReactDOM.createRoot(container).render(
  <React.StrictMode>
    <BrowserRouter basename="/app">
      <AppRoutes />
    </BrowserRouter>
  </React.StrictMode>,
)
