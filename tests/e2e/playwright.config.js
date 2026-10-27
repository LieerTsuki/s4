import { defineConfig } from 'playwright/test';

export default defineConfig({
  testDir: '.',
  testMatch: '**/*.spec.js',
  timeout: 120_000,
  expect: { timeout: 15_000 },
  workers: 1,
  use: {
    baseURL: process.env.S4_E2E_URL || 'http://localhost:5174',
    browserName: 'chromium',
    channel: process.env.S4_E2E_BROWSER === 'chromium' ? undefined : process.env.S4_E2E_BROWSER || 'msedge',
    headless: true,
    actionTimeout: 15000,
    navigationTimeout: 20000,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    viewport: {width: 1440, height: 1000},
  },
  reporter: [['list'], ['json', {outputFile: '../../var/evidence/e2e-results.json'}]],
  outputDir: '../../var/evidence/browser',
});
