import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: { port: 5174, proxy: { '/api': 'http://127.0.0.1:8004' } },
  test: { maxWorkers: 1, environment: 'jsdom', setupFiles: ['./src/tests/setup.ts'], css: true },
});
