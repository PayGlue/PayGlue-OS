import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig as defineVitestConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineVitestConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    port: 5173,
    allowedHosts: ['dev.payglue.io', 'dev2.payglue.io'],
    proxy: {
      '/api': {
        target: process.env.VITE_DEV_PROXY_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
      },
      '/t': {
        target: process.env.VITE_DEV_PROXY_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
  },
})
