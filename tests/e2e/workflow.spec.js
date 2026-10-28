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
  for (const [seat, roles] of [['lead', ['lead']], ['a', ['annotator']], ['b', ['annotator']], ['auditor', ['auditor']], ['verifier', ['verifier']]]) {
    const user = await mutate(admin, '/users', {username: `browser-${run}-${seat}`, display_name: `演练${seat.toUpperCase()}`,
      person_id: `synthetic-${run}-${seat}`, password, roles}, 201);
    actors[seat] = await signedIn(user.username, password);
  }
  const candidate = JSON.parse(readFileSync(resolve(root, 'contracts/examples/demo-import.json'), 'utf8'));
  candidate.batch_id = `BROWSER-SYNTHETIC-${run}`;
  candidate.source_revision = `browser-${run}`;
  for (const unit of candidate.units) unit.unit_id += `-${run}`;
  await uiLogin(page, `browser-${run}-lead`, password);
  await page.goto('/imports');
  const jsonl = candidate.units.map(unit => JSON.stringify(unit)).join('\n') + '\n';
  const envelope = Object.fromEntries(Object.entries(candidate).filter(([key]) => key !== 'units'));
  await page.getByLabel('选择单元JSONL文件', {exact: true}).setInputFiles({name: `synthetic-${run}.jsonl`, mimeType: 'application/x-ndjson', buffer: Buffer.from(jsonl, 'utf8')});
  await page.getByLabel('契约与S3报告JSON（不含units）', {exact: true}).fill(JSON.stringify(envelope));
  const imported = await uiPost(page, '/imports/upload', page.getByRole('button', {name: '提交JSONL受控上传', exact: true}), 202);
  expect(imported.raw_file_sha256).toBe(createHash('sha256').update(jsonl).digest('hex'));
  expect(imported.normalized_sha256).not.toBe(imported.raw_file_sha256);
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
        await expect(page.getByRole('heading', {name: '授权原文', exact: true})).toBeVisible();
        await expect(page.getByLabel('P001 正确性', {exact: true})).toHaveCount(0);
        await page.getByRole('button', {name: '报告材料问题', exact: true}).click();
        await page.getByRole('combobox', {name: '问题类型', exact: true}).selectOption('OTHER');
        await page.getByLabel('问题描述', {exact: true}).fill('合成演练：请独立核对材料可读性。');
        const issue = await uiPost(page, '/work-issues', page.getByRole('button', {name: '登记材料问题', exact: true}), 201);
        const paused = await json(await actors.lead.api.get(`${prefix}/annotation-batches/${batch.id}`));
        expect(paused.state).toBe('PAUSED');
        await mutate(actors.lead, `/work-issues/${issue.id}/resolve`, {version: issue.version,
          disposition: 'UNCHANGED', reason: '合成演练独立运营确认原文可读，材料没有改动。'});
        await page.reload();
        await expect(page.getByLabel('独立答案 / 拒答判断', {exact: true})).toBeEnabled();
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
        profile_version: detail.profile_version, profile_hash: detail.profile_hash, payload: {answer: '五个工作日内通过指定表单办理并保留凭证。', reason: '独立阅读合成原文形成判断。'}}, 200,
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
        await page.getByText('本人独立作答快照 · 展开参考', {exact: true}).click();
        await expect(page.getByRole('heading', {name: '本人独立作答快照', exact: true})).toBeVisible();
        await page.getByText('本人独立作答快照 · 展开参考', {exact: true}).click();
        const geometries = [];
        for (const width of [1366, 1440, 1920]) {
          await page.setViewportSize({width, height: 1000});
          const boxes = await page.locator('.review-columns > .review-column').evaluateAll(nodes => nodes.map(node => {
            const r = node.getBoundingClientRect(); return {x: r.x, y: r.y, width: r.width};
          }));
          expect(boxes).toHaveLength(3);
          expect(Math.max(...boxes.map(box => box.y)) - Math.min(...boxes.map(box => box.y))).toBeLessThan(2);
          expect(boxes.every(box => box.width > 200)).toBe(true);
          expect(boxes[0].x < boxes[1].x && boxes[1].x < boxes[2].x).toBe(true);
          geometries.push({viewport: width, columns: boxes});
        }
        await page.setViewportSize({width: 390, height: 844});
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2)).toBe(true);
        writeFileSync(resolve(evidence, 'three-column-layout.json'), JSON.stringify({desktop: geometries, mobile: {viewport: 390, no_horizontal_page_overflow: true}}, null, 2));
        await page.setViewportSize({width: 1440, height: 1000});
        for (const [key, value] of Object.entries(labels)) {
          await page.getByLabel(`${key} 正确性`, {exact: true}).selectOption(value);
          await page.getByLabel(`${key} 逐点理由`, {exact: true}).fill('按冻结授权原文逐点核对。');
          if (value === 'wrong') {
            await page.getByLabel(`${key} 已核查 ${detail.material.contexts[0].doc_id}`, {exact: true}).check();
          } else {
            await page.getByLabel(`${key} 原文依据 起点`, {exact: true}).fill('0');
            await page.getByLabel(`${key} 原文依据 终点`, {exact: true}).fill('20');
            await page.getByRole('button', {name: `加入${key} 原文依据`, exact: true}).click();
          }
        }
        for (const doc of detail.gold.gold_doc_ids) {
          await page.getByLabel(`${doc} 相关度`, {exact: true}).selectOption('2');
          await page.getByLabel(`${doc} 逐文档理由`, {exact: true}).fill('该授权文档含题目所需信息。');
        }
        await page.getByLabel('可答性', {exact: true}).selectOption('answerable');
        await page.getByLabel('题级可答理由', {exact: true}).fill('原文覆盖题目问法及阅读范围。');
        await page.getByLabel('复核理由', {exact: true}).fill('合成测试按原文逐项复核。');
        await page.screenshot({path: resolve(evidence, 'review-workspace.png'), fullPage: true});
        await page.locator('.review-columns').scrollIntoViewIfNeeded();
        await page.screenshot({path: resolve(evidence, 'review-three-columns.png')});
        await page.getByRole('button', {name: '提交并封存复核', exact: true}).click();
        await expect(page.getByText('本阶段记录已封存', {exact: true})).toBeVisible();
        continue;
      }
      await mutate(actor, `/assignments/${task.id}/submit`, {phase: 'REVIEW', content_revision: detail.content_revision,
        profile_version: detail.profile_version, profile_hash: detail.profile_hash, payload: {
          review_version: 'openkb.s4-review.v2', point_labels: labels,
          point_reasons: Object.fromEntries(detail.points.map(point => [point.point_key, '按冻结原文逐点核对。'])),
          point_evidence: Object.fromEntries(detail.points.map(point => [point.point_key, labels[point.point_key] === 'wrong' ? [] : [{doc_id: detail.material.contexts[0].doc_id, start: 0, end: 20}]])),
          point_search_scope: Object.fromEntries(detail.points.filter(point => labels[point.point_key] === 'wrong').map(point => [point.point_key, [detail.material.contexts[0].doc_id]])),
          evidence_reasons: Object.fromEntries(detail.gold.gold_doc_ids.map(id => [id, '原文含题目所需信息。'])),
          evidence_labels: Object.fromEntries(detail.gold.gold_doc_ids.map(id => [id, 2])), answerable: 'answerable',
          answerable_reason: '授权原文足以回答本题。', reason: '合成测试按原文逐项复核。'}}, 200,
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
  const decisions = candidate.units.filter(unit => selected.has(unit.unit_id)).map(unit => ({unit_id: unit.unit_id,
    final_gold: {...unit.gold, answer_points: ['须在五个工作日内办理。', '申请仅能通过指定表单提交，不接受邮件。', '办理后必须保留凭证。']},
    reason: '合成演练运营依据原文逐题确认最终修订。'}));
  const premature = await actors.lead.api.post(`${prefix}/annotation-batches/${batch.id}/finalize`, {headers: actors.lead.headers, data: {decisions}});
  expect(premature.status()).toBe(409);
  expect((await premature.json()).error_code).toBe('VALIDATION_REQUIRED');
  for (const decision of decisions) {
    const proposed = await mutate(actors.lead, '/validation-candidates', {...decision, batch_id: batch.id, verifier_id: actors.verifier.user.id}, 201);
    const authorized = await json(await actors.verifier.api.get(`${prefix}/validation-candidates?batch_id=${batch.id}&unit_id=${decision.unit_id}`));
    expect(authorized.content_hash).toBe(proposed.content_hash);
    expect((await actors.a.api.get(`${prefix}/validation-candidates?batch_id=${batch.id}&unit_id=${decision.unit_id}`)).status()).toBe(403);
    await mutate(actors.verifier, '/validation-revisions', {...decision, batch_id: batch.id, content_hash: authorized.content_hash,
      profile_hash: authorized.profile_hash, evidence: {kind: 'synthetic', revision: `browser-independent-${run}-${decision.unit_id}`,
        content_hash: authorized.content_hash, profile_hash: authorized.profile_hash,
        point_results: decision.final_gold.answer_points.map((_, index) => ({point_key: `P${String(index + 1).padStart(3, '0')}`, status: 'PASS', reason: '独立核对合成原文。'})),
        locators: [{doc_id: authorized.contexts[0].doc_id, start: 0, end: 20}]}}, 201);
  }
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
  const rawEvidence = await json(await actors.auditor.api.get(`${prefix}/handoffs/${handoffId}/evidence`));
  expect(rawEvidence.assignments).toHaveLength(16);
  expect(rawEvidence.submissions).toHaveLength(32);
  expect(rawEvidence.agreements[0].result.kappa).toBe(1);
  expect(rawEvidence.validations.filter(item => item.status === 'PASS')).toHaveLength(8);
  expect((await actors.a.api.get(`${prefix}/handoffs/${handoffId}/files/units_for_s5.jsonl`)).status()).toBe(403);
  await page.goto(`/handoffs/${handoffId}`);
  await expect(page.getByRole('heading', {name: '交接清单与受控文件', exact: true})).toBeVisible();
  const delivery = resolve(evidence, 'deliveries', run); mkdirSync(delivery, {recursive: true});
  for (const [name, content] of Object.entries(files)) writeFileSync(resolve(delivery, name), content);
  const deliveryHash = createHash('sha256').update(files['s4_handoff_manifest.json']).digest('hex');
  await page.getByLabel('接收方引用', {exact: true}).fill(`manual:local-demo-${run}`);
  await page.getByLabel('实际交付证据引用', {exact: true}).fill(`evidence:local-demo-${run}`);
  await page.getByLabel('交付证据SHA-256', {exact: true}).fill(deliveryHash);
  const sent = await uiPost(page, `/handoffs/${handoffId}/sent`, page.getByRole('button', {name: '登记已发送证据', exact: true}));
  expect(sent.status).toBe('HANDOFF_SENT');
  expect(sent.external_status).toBe('NOT_ALIGNED');
  const repeated = await uiPost(page, `/handoffs/${handoffId}/sent`, page.getByRole('button', {name: '登记已发送证据', exact: true}));
  expect(repeated.sent_event_id).toBe(sent.sent_event_id);
  await page.screenshot({path: resolve(evidence, 'handoff-workbench.png'), fullPage: true});
  await page.goto('/health');
  const reconcileJob = await uiPost(page, '/reconciliations', page.getByRole('button', {name: '运行对账', exact: true}), 202);
  await jobDone(actors.lead, reconcileJob.job_id);
  const operations = await json(await actors.lead.api.get(`${prefix}/operations`));
  expect(operations).toHaveProperty('queue');
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
