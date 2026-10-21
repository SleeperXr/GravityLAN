/// <reference types="vitest/config" />
import path from 'node:path';
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import tailwindcss from '@tailwindcss/vite';

// Framework-free code (API client, types, locales, pure models) is shared with the React UI
// in ../frontend/src, so both UIs speak the same backend contract and show the same texts.
const sharedDir = path.resolve(__dirname, '../frontend/src');

export default defineConfig({
  base: '/frontend-vue/',
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      '@shared': sharedDir,
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5174,
    host: '0.0.0.0',
    fs: { allow: [path.resolve(__dirname), sharedDir] },
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: false,
    include: ['src/**/*.test.ts'],
    setupFiles: ['src/test/setup.ts'],
    css: false,
  },
});
