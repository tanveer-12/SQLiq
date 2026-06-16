import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/ui/',
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/v1':  'http://localhost:8000',
    },
  },
  build: {
    outDir: 'dist',
  },
})