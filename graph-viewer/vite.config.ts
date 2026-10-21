import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
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
