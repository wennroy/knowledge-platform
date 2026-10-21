import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // The built SPA is served by FastAPI at /static/graph/, so asset URLs must
  // be prefixed with that path. Without this, index.html references
  // /assets/xxx.js which 404s and the page renders blank.
  base: '/static/graph/',
  build: {
    outDir: '../backend/app/static/graph',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/graph': 'http://localhost:8000',
    },
  },
});
