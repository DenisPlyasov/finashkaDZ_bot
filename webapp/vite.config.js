import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const extraAllowedHosts = (process.env.VITE_ALLOWED_HOSTS || '')
  .split(',')
  .map((host) => host.trim())
  .filter(Boolean)

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
    allowedHosts: [
      'finunischedule.allspace.com.ru',
      ...extraAllowedHosts,
    ],
  },
})
