import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    environmentMatchGlobs: [
      // better-sqlite3 はネイティブ Node.js モジュール → lib/agents テストは node 環境で実行
      ['src/lib/**', 'node'],
    ],
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
});
