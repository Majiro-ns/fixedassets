import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    // @ts-expect-error: environmentMatchGlobs は vitest 4.x の型定義から削除されたが、
    // ランタイムでは動作する。lib/agents の better-sqlite3 テストは node 環境が必要。
    environmentMatchGlobs: [
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
