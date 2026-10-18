import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '..', 'VITE_')
  // Same-origin local development and preview: /api reaches the real FastAPI
  // process. Production deployments continue to use their nginx/Jupyter proxy.
  const proxy = { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } }
  return {
    envDir: '..',
    base: env.VITE_BASE_PATH || '/',
    plugins: [react()],
    define: { 'import.meta.env.VITE_API_BASE_URL': JSON.stringify(env.VITE_API_BASE_URL || '') },
    server: { port: 5173, proxy },
    preview: { proxy, allowedHosts: env.VITE_PREVIEW_HOST ? [env.VITE_PREVIEW_HOST] : [] },
  }
})
