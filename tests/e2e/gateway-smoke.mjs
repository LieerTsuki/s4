// Read-only check of the built deployment; never creates accounts or material.
import { chromium, request, expect } from 'playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const evidence = resolve(import.meta.dirname, '../../var/evidence');
mkdirSync(evidence, {recursive: true});
const baseURL = process.env.S4_GATEWAY_URL || 'http://localhost:8084';
const api = await request.newContext({baseURL, timeout: 15_000});
const response = await api.get('/api/s4/v1/health/ready');
expect(response.status()).toBe(200);
const health = await response.json();
expect(health).toMatchObject({status: 'ready', database: true, migration: '0003_s4', worker: true, external_alignment: 'NOT_ALIGNED'});
const browser = await chromium.launch({headless: true, ...(process.env.S4_E2E_BROWSER === 'chromium' ? {} : {channel: process.env.S4_E2E_BROWSER || 'msedge'})});
try {
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const unexpected = [];
  page.on('request', value => { if (!value.url().startsWith(baseURL) && !value.url().startsWith('data:')) unexpected.push(new URL(value.url()).origin); });
  await page.goto(baseURL, {waitUntil: 'load', timeout: 20_000});
  await expect(page.getByLabel('账号', {exact: true})).toBeVisible();
  await expect(page.getByRole('button', {name: '登录工作台', exact: true})).toBeEnabled();
  expect(unexpected).toEqual([]);
  await page.screenshot({path: resolve(evidence, 'container-login.png'), fullPage: true});
  writeFileSync(resolve(evidence, 'gateway-smoke.json'), JSON.stringify({url: baseURL, health, login_page: 'passed', external_requests: unexpected, mode: 'read-only'}, null, 2));
  console.log(JSON.stringify({url: baseURL, migration: health.migration, readiness: health.status, login_page: 'passed', external_requests: unexpected.length}));
} finally {
  await browser.close();
  await api.dispose();
}
