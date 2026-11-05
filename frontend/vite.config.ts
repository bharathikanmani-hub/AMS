// Plain Vite config for running AttendAI on your own PC (replaces the Figma Make one,
// which needs a ./.figma folder that is not part of the exported zip).
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  server: {
    port: 5173,
    // The browser talks to Vite; Vite forwards /api to Flask, so cookies + CSRF work (same origin).
    proxy: { '/api': { target: 'http://127.0.0.1:5000', changeOrigin: false } },
  },
  build: { outDir: 'dist' },
})
