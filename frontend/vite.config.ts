/// <reference types="vitest/config" />
import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The SPA always calls the API at the same origin (/api/...). In dev, Vite proxies to FastAPI;
// in production a Cloudflare Pages Function does the same. Same-origin => first-party
// HttpOnly cookies that browsers won't block (see docs/PHASE-1-ARCHITECTURE.md §C).
const API_TARGET = process.env.DOCUMIND_API_URL ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: false },
    },
  },
  test: {
    environment: 'jsdom',
    globals: false,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    restoreMocks: true,
    testTimeout: 20_000, // end-to-end UI tests (lazy pages + streaming) exceed vitest's 5s default
  },
})
