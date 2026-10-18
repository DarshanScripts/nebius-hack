import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '..', 'VITE_')
  return {
    envDir: '..',
    base: env.VITE_BASE_PATH || '/',
    plugins: [react()],
    define: { 'import.meta.env.VITE_API_BASE_URL': JSON.stringify(env.VITE_API_BASE_URL || '') },
    server: { port: 5173 },
    preview: { allowedHosts: env.VITE_PREVIEW_HOST ? [env.VITE_PREVIEW_HOST] : [] },
  }
})
