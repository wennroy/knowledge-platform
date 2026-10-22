import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The SPA is served by FastAPI under /app/ (see backend/app/main.py), and it
// talks to the API on the same origin via absolute /v1 paths, so no runtime
// base URL is required.
export default defineConfig({
  base: '/app/',
  plugins: [react()],
  build: {
    outDir: '../backend/app/static/app',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/v1': 'http://localhost:8000',
      '/graph': 'http://localhost:8000',
      '/healthz': 'http://localhost:8000',
      '/admin': 'http://localhost:8000',
    },
  },
})
