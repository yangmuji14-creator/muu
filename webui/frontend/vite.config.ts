import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

const BACKEND = 'http://127.0.0.1:8000';

export default defineConfig({
  base: '/static/',
  plugins: [react(), tailwindcss()],
  build: {
    outDir: '../static',
    emptyOutDir: true,
    assetsDir: 'assets',
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true },
      '/avatars': { target: BACKEND, changeOrigin: true },
      '/attachments': { target: BACKEND, changeOrigin: true },
      '/stickers': { target: BACKEND, changeOrigin: true },
    },
  },
});
