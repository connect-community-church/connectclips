import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Proxy /api and /files to the FastAPI backend so the frontend can use
// relative URLs in dev (avoids CORS confusion) and so the same paths work
// under Tailscale in production.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',  // expose on Tailscale
    port: 5173,
    proxy: {
      // API routes live under /api in both dev and prod — pass through unchanged.
      '/api': { target: 'http://127.0.0.1:8765', changeOrigin: true },
      '/files': { target: 'http://127.0.0.1:8765', changeOrigin: true },
    },
  },
})
