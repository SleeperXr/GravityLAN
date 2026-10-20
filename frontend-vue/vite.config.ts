import path from 'node:path';
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  base: '/frontend-vue/',
  plugins: [
    vue(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5174,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/api/scanner/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
      },
      '/api/agent/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
      },
      '/api/ssh/terminal': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
      },
    },
  },
});
