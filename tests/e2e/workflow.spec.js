import { test, expect, request } from 'playwright/test';
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { randomUUID, createHash } from 'node:crypto';

const root = resolve(import.meta.dirname, '../..');
const env = Object.fromEntries(readFileSync(resolve(root, '.env.e2e'), 'utf8').trim().split(/\r?\n/).map(line => {
  const split = line.indexOf('='); return [line.slice(0, split), line.slice(split + 1)];
}));
const apiUrl = process.env.S4_E2E_API || 'http://127.0.0.1:8004';
const prefix = '/api/s4/v1';

async function signedIn(username, password) {
  const api = await request.newContext({baseURL: apiUrl});
  const response = await api.post(`${prefix}/auth/login`, {data: {username, password}});
  expect(response.status(), `login ${username}`).toBe(200);
  const payload = await response.json();
  return {api, headers: {'X-CSRF-Token': payload.csrf_token}, user: payload.user};
}

async function json(response, status = 200) {
  expect(response.status(), await response.text()).toBe(status);
  return response.json();
}

async function jobDone(actor, id) {
  let job;
  await expect.poll(async () => {
    job = await json(await actor.api.get(`${prefix}/jobs/${id}`));
    return job.state;
  }, {timeout: 45_000, message: 'durable worker completes queued task'}).toBe('DONE');
  return job.result;
}

async function mutate(actor, path, data, status = 200, extra = {}) {
  return json(await actor.api.post(prefix + path, {data, headers: {...actor.headers, ...extra}}), status);
}

async function uiLogin(page, username, password) {
  await page.goto('/');
  const logout = page.getByRole('button', {name: '退出登录', exact: true});
  await expect.poll(async () => await logout.isVisible() || await page.getByLabel('账号', {exact: true}).isVisible()).toBe(true);
  if (await logout.isVisible()) await logout.click();
  await page.getByLabel('账号', {exact: true}).fill(username);
  await page.getByLabel('密码', {exact: true}).fill(password);
  await page.getByRole('button', {name: '登录工作台', exact: true}).click();
  await expect(logout).toBeVisible();
}

async function uiPost(page, path, button, expectedStatus = 200) {
  const response = page.waitForResponse(value => value.url().endsWith(prefix + path) && value.request().method() === 'POST');
  await button.click();
  return json(await response, expectedStatus);
}

test('synthetic complete two-person workflow preserves all N units and n review records', async ({page}) => {
  const run = randomUUID().slice(0, 8);
  const password = randomUUID() + '-synthetic';
  const admin = await signedIn(env.S4_E2E_ADMIN_USERNAME, env.S4_E2E_ADMIN_PASSWORD);
  const actors = {};
  for (const [seat, roles] of [['lead', ['lead']], ['a', ['annotator']], ['b', ['annotator']], ['auditor', ['auditor']]]) {
    const user = await mutate(admin, '/users', {username: `browser-${run}-${seat}`, display_name: `演练${seat.toUpperCase()}`,
      person_id: `synthetic-${run}-${seat}`, password, roles}, 201);
    actors[seat] = await signedIn(user.username, password);
  }
  const candidate = JSON.parse(readFileSync(resolve(root, 'contracts/examples/demo-import.json'), 'utf8'));
  candidate.batch_id = `BROWSER-SYNTHETIC-${run}`;
  candidate.source_revision = `browser-${run}`;
  for (const unit of candidate.units) unit.unit_id += `-${run}`;
  const imported = await mutate(actors.lead, '/imports', candidate, 202);
  const {import_id: importId} = await jobDone(actors.lead, imported.job_id);
  const batch = await mutate(actors.lead, '/annotation-batches', {import_id: importId, dataset: 'QA-D1',
    annotator_a: actors.a.user.id, annotator_b: actors.b.user.id, seed: 57}, 201);
  expect(batch.sample_count).toBe(8);
  expect((await actors.lead.api.post(`${prefix}/annotation-batches/${batch.id}/release-review`, {headers: actors.lead.headers})).status()).toBe(409);
  const queues = {};
  const evidence = resolve(root, 'var/evidence'); mkdirSync(evidence, {recursive: true});
  await uiLogin(page, `browser-${run}-a`, password);
  await expect(page.getByText('演练A', {exact: true})).toBeVisible();
  for (const seat of ['a', 'b']) {
    const actor = actors[seat];
    queues[seat] = (await json(await actor.api.get(`${prefix}/me/tasks`))).items.filter(task => task.batch_id === batch.id);
    expect(queues[seat]).toHaveLength(8);
    for (const task of queues[seat]) {
      const detail = await json(await actor.api.get(`${prefix}/assignments/${task.id}`));
      expect(detail.phase).toBe('BLIND');
      expect(detail).not.toHaveProperty('gold');
      expect(detail).not.toHaveProperty('points');
      expect(JSON.stringify(detail)).not.toContain('expected_behavior');
      if (seat === 'a' && task.id === queues.a[0].id) {
        await page.goto(`/tasks/${task.id}`);
        await expect(page.getByText('授权原文', {exact: true})).toBeVisible();
        await expect(page.getByLabel('P001 正确性', {exact: true})).toHaveCount(0);
        await page.getByLabel('独立答案 / 拒答判断', {exact: true}).fill('五个工作日内通过指定表单办理并保留凭证。');
        await page.getByLabel('所据原文与理由', {exact: true}).fill('独立阅读合成原文形成判断。');
        await page.getByRole('button', {name: '暂存草稿', exact: true}).click();
        await expect(page.getByRole('status')).toContainText('草稿已保存');
        await page.screenshot({path: resolve(evidence, 'blind-workspace.png'), fullPage: true});
        await page.getByRole('button', {name: '提交并封存盲答', exact: true}).click();
        await expect(page.getByText('本阶段记录已封存', {exact: true})).toBeVisible();
        continue;
      }
      await mutate(actor, `/assignments/${task.id}/submit`, {phase: 'BLIND', content_revision: detail.content_revision,
        profile_version: detail.profile_version, payload: {answer: '五个工作日内通过指定表单办理并保留凭证。', reason: '独立阅读合成原文形成判断。'}}, 200,
      {'Idempotency-Key': `blind-${task.id}`});
    }
  }
  expect((await actors.a.api.get(`${prefix}/assignments/${queues.b[0].id}`)).status()).toBe(404);
  await uiLogin(page, `browser-${run}-lead`, password);
  await page.goto(`/batches/${batch.id}`);
  await uiPost(page, `/annotation-batches/${batch.id}/release-review`, page.getByRole('button', {name: '统一开放复核', exact: true}));
  await uiLogin(page, `browser-${run}-a`, password);
  for (const seat of ['a', 'b']) {
    const actor = actors[seat];
    for (const task of queues[seat]) {
      const detail = await json(await actor.api.get(`${prefix}/assignments/${task.id}`));
      expect(detail.phase).toBe('REVIEW');
      expect(detail.own_blind.answer).toContain('五个工作日');
      expect(detail).not.toHaveProperty('grades_b');
      const labels = Object.fromEntries(detail.points.map((point, index) => [point.point_key, ['correct', 'partial', 'wrong'][index % 3]]));
      if (seat === 'a' && task.id === queues.a[0].id) {
        await page.goto(`/tasks/${task.id}`);
        await expect(page.getByText('本人独立作答快照', {exact: true})).toBeVisible();
        for (const [key, value] of Object.entries(labels)) await page.getByLabel(`${key} 正确性`, {exact: true}).selectOption(value);
        for (const doc of detail.gold.gold_doc_ids) await page.getByLabel(`${doc} 相关度`, {exact: true}).selectOption('2');
        await page.getByLabel('可答性', {exact: true}).selectOption('answerable');
        await page.getByLabel('复核理由', {exact: true}).fill('合成测试按原文逐项复核。');
        await page.screenshot({path: resolve(evidence, 'review-workspace.png'), fullPage: true});
        await page.getByRole('button', {name: '提交并封存复核', exact: true}).click();
        await expect(page.getByText('本阶段记录已封存', {exact: true})).toBeVisible();
        continue;
      }
      await mutate(actor, `/assignments/${task.id}/submit`, {phase: 'REVIEW', content_revision: detail.content_revision,
        profile_version: detail.profile_version, payload: {point_labels: labels,
          evidence_labels: Object.fromEntries(detail.gold.gold_doc_ids.map(id => [id, 2])), answerable: 'answerable', reason: '合成测试按原文逐项复核。'}}, 200,
      {'Idempotency-Key': `review-${task.id}`});
    }
  }
  await uiLogin(page, `browser-${run}-lead`, password);
  await page.goto(`/batches/${batch.id}`);
  const statistics = await uiPost(page, `/annotation-batches/${batch.id}/agreement`, page.getByRole('button', {name: '计算批次一致性', exact: true}), 202);
  const {agreement_id: agreementId} = await jobDone(actors.lead, statistics.job_id);
  const agreement = (await json(await actors.lead.api.get(`${prefix}/agreements`))).items.find(item => item.id === agreementId);
  expect(agreement.kappa).toBe(1);
  expect(agreement.verdict).toBe('ACCEPT');
  expect(agreement.n).toBe(24);
  const selected = new Set(queues.a.map(item => item.unit_id));
  await page.getByRole('button', {name: '打开逐单元定稿', exact: true}).click();
  for (const unit of candidate.units.filter(unit => selected.has(unit.unit_id))) {
    const points = page.locator(`[id="final-${unit.unit_id}-points"]`);
    const card = points.locator('xpath=ancestor::details');
    await card.locator(':scope > summary').click();
    await points.fill('须在五个工作日内办理。\n申请仅能通过指定表单提交，不接受邮件。\n办理后必须保留凭证。');
    await card.getByLabel('定稿理由', {exact: true}).fill('合成演练运营依据原文逐题确认最终修订。');
  }
  await uiPost(page, `/annotation-batches/${batch.id}/finalize`, page.getByRole('button', {name: '确认全部抽检单元并封存定稿', exact: true}));
  await expect(page.getByText('该轮最终内容已封存。', {exact: true})).toBeVisible();
  await page.goto('/handoffs');
  await page.getByRole('combobox', {name: '来源批次', exact: true}).selectOption(importId);
  const exportJob = await uiPost(page, '/handoffs', page.getByRole('button', {name: '创建交接快照', exact: true}), 202);
  const {handoff_id: handoffId} = await jobDone(actors.lead, exportJob.job_id);
  const handoff = await json(await actors.lead.api.get(`${prefix}/handoffs/${handoffId}`));
  expect(handoff.mode).toBe('demo');
  expect(handoff.external_status).not.toBe('S5_ACCEPTED');
  const files = {};
  for (const name of ['units_for_s5.jsonl', 'labeled.jsonl', 'iaa_records.jsonl', 's4_report.json', 'arbitration_log.jsonl', 's4_handoff_manifest.json']) {
    const response = await actors.lead.api.get(`${prefix}/handoffs/${handoffId}/files/${name}`);
    expect(response.status()).toBe(200);
    files[name] = await response.text();
  }
  const lines = name => files[name].trim().split(/\r?\n/).filter(Boolean).map(line => JSON.parse(line));
  expect(lines('units_for_s5.jsonl')).toHaveLength(12);
  expect(lines('labeled.jsonl')).toHaveLength(8);
  expect(lines('iaa_records.jsonl')).toHaveLength(8);
  expect(new Set(lines('labeled.jsonl').map(item => item.unit_id))).toEqual(new Set(lines('iaa_records.jsonl').map(item => item.unit_id)));
  expect((await actors.a.api.get(`${prefix}/handoffs/${handoffId}/files/units_for_s5.jsonl`)).status()).toBe(403);
  await page.goto(`/handoffs/${handoffId}`);
  await expect(page.getByRole('heading', {name: '交接清单与受控文件', exact: true})).toBeVisible();
  await page.screenshot({path: resolve(evidence, 'handoff-workbench.png'), fullPage: true});
  writeFileSync(resolve(evidence, 'workflow-summary.json'), JSON.stringify({mode: 'synthetic-demo', batch_id: batch.id,
    handoff_id: handoffId, total: 12, sampled: 8, raw_point_count: 24, kappa: agreement.kappa,
    manifest_sha256: createHash('sha256').update(files['s4_handoff_manifest.json']).digest('hex'),
    external_alignment: 'NOT_ALIGNED', human_acceptance: 'NOT_PERFORMED'}, null, 2));
  await uiLogin(page, `browser-${run}-a`, password);
  await page.goto('/tasks');
  await expect(page.getByText('演练A', {exact: true})).toBeVisible();
  await page.screenshot({path: resolve(evidence, 'annotator-workbench.png'), fullPage: true});
  for (const actor of [admin, ...Object.values(actors)]) await actor.api.dispose();
});
