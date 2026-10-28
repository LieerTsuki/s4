import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: { "/api": "http://127.0.0.1:8004" },
    watch: { ignored: ["**/coverage/**", "**/dist/**"] },
  },
  test: {
    maxWorkers: 1,
    environment: "jsdom",
    setupFiles: ["./src/tests/setup.ts"],
    css: true,
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/tests/**", "src/**/*.d.ts", "src/types.ts"],
      reporter: ["text", "json-summary", "lcov"],
      thresholds: { lines: 80 },
    },
  },
});
