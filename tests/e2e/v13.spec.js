import {test, expect, request} from 'playwright/test';
import {readFileSync, writeFileSync, mkdirSync} from 'node:fs';
import {resolve} from 'node:path';
import {randomUUID, createHash} from 'node:crypto';

const root=resolve(import.meta.dirname,'../..');
const env=Object.fromEntries(readFileSync(resolve(root,'.env.v13-e2e'),'utf8').trim().split(/\r?\n/).map(line=>{const i=line.indexOf('=');return[line.slice(0,i),line.slice(i+1)];}));
const P='/api/s4/v2';
async function value(response,status=200){expect(response.status(),await response.text()).toBe(status);return response.json();}
async function actor(name){const api=await request.newContext({baseURL:'http://127.0.0.1:8004'});const session=await value(await api.post('/api/s4/v1/auth/login',{data:{username:'v13-e2e-'+name,password:env.S4_V13_E2E_PASSWORD}}));return{api,user:session.user,headers:{'X-CSRF-Token':session.csrf_token}};}
async function post(who,path,data,status=200,headers={}){return value(await who.api.post(P+path,{data,headers:{...who.headers,...headers}}),status);}
async function tasks(who){return(await value(await who.api.get(P+'/me/tasks?limit=500'))).items;}
async function seal(who,task,payload){return post(who,`/assignments/${task.id}/submit`,{phase:task.phase,content_revision:task.content_revision,profile_version:task.profile_version,payload},200,{'Idempotency-Key':task.id+'-'+task.phase});}
function review(detail){const doc=detail.material.contexts[0],loc={doc_id:doc.doc_id,context_sha256:createHash('sha256').update(doc.text).digest('hex'),start:0,end:7,quote:Array.from(doc.text).slice(0,7).join('')};return{review_version:'openkb.s4-review.v3',workflow_kind:detail.workflow_kind,verdict:'VERIFIED',point_labels:{P001:'correct',P002:'correct'},point_reasons:{P001:'原文期限核对',P002:'原文渠道核对'},point_evidence:{P001:[loc],P002:[loc]},point_search_scope:{},evidence_assessments:{[doc.doc_id]:{grade:3,reason:'直接支持答案',locators:[loc],intent:'KEEP_GOLD'}},expected_refusal:false,absence_reason:null,expected_refusal_reason:'授权原文可答',reason:'逐条人工核实的合成自动化演练',specialized_review:{}};}

test('v1.3 full N verification and separate n observation preserve three columns and handoff counts',async({page})=>{
 const actors={};for(const name of ['lead','v','a','b'])actors[name]=await actor(name);
 const run=randomUUID().slice(0,8),text='服务须五日办理。渠道须指定表单。';
 const source={contract_version:'openkb.s3-s4.v2',mode:'demo',batch_id:'V13-BROWSER-'+run,source_revision:'r1',units:Array.from({length:12},(_,i)=>({unit_id:`QA-D1-browser-${run}-${i}`,dataset:'QA-D1',difficulty:['easy','medium','hard'][i%3],question:`合成服务${i}的期限和渠道是什么？`,contexts:[{doc_id:`doc-${run}-${i}`,text}],gold:{answer_points:['五日办理','指定表单'],gold_doc_ids:[`doc-${run}-${i}`],relevance_grades:{[`doc-${run}-${i}`]:3},ranking_annotations:{},expected_refusal:false,absence_reason:null},metadata:{generation_model:'synthetic-browser-only'}}))};
 const {units,...envelope}=source;const raw=Buffer.from('\ufeff'+units.map(unit=>JSON.stringify(unit)).join('\r\n')+'\r\n','utf8');const imported=await post(actors.lead,'/imports/upload',{envelope,file_base64:raw.toString('base64')},201);expect(imported.raw_file_sha256).toBe(createHash('sha256').update(raw).digest('hex'));
 const main=await post(actors.lead,'/verification-batches',{import_id:imported.id,dataset:'QA-D1',assignee_ids:[actors.v.user.id]},201);
 const obs=await post(actors.lead,'/observation-batches',{import_id:imported.id,dataset:'QA-D1',annotator_a:actors.a.user.id,annotator_b:actors.b.user.id,seed:42},201);
 const own=(await tasks(actors.v)).filter(t=>t.batch_id===main.id),target=own[0];
 await page.goto('/');await page.getByLabel('账号',{exact:true}).fill('v13-e2e-v');await page.getByLabel('密码',{exact:true}).fill(env.S4_V13_E2E_PASSWORD);await page.getByRole('button',{name:'登录工作台',exact:true}).click();await expect(page.getByRole('button',{name:'退出登录',exact:true})).toBeVisible();
 await page.goto(`/v13/tasks/${target.id}`);await expect(page.getByLabel('新版独立判断')).toBeVisible();await expect(page.locator('.review-columns')).toHaveCount(0);
 await page.getByLabel('新版独立判断').fill('我根据原文独立判断五日办理、指定表单。');await page.getByLabel('新版独立理由').fill('原文同时包含期限和渠道，未看模型草案。');
 await page.getByRole('button',{name:'提交并封存独立判断',exact:true}).click();await expect(page.getByLabel('P001 正确性')).toBeVisible();
 const geometry=[];for(const width of [1366,1440,1920]){await page.setViewportSize({width,height:1000});const boxes=await page.locator('.v13-review .review-column').evaluateAll(nodes=>nodes.map(n=>{const r=n.getBoundingClientRect();return{x:r.x,y:r.y,width:r.width};}));expect(boxes).toHaveLength(3);expect(Math.max(...boxes.map(r=>r.y))-Math.min(...boxes.map(r=>r.y))).toBeLessThan(2);expect(boxes[0].x).toBeLessThan(boxes[1].x);expect(boxes[1].x).toBeLessThan(boxes[2].x);expect(Math.min(...boxes.map(r=>r.width))).toBeGreaterThan(200);geometry.push({width,boxes});}
 mkdirSync(resolve(root,'var/evidence'),{recursive:true});await page.screenshot({path:resolve(root,'var/evidence/v13-three-columns.png'),fullPage:true});
 await page.setViewportSize({width:390,height:1000});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);await page.setViewportSize({width:1440,height:1000});
 for(const key of ['P001','P002']){await page.getByLabel(`${key} 正确性`,{exact:true}).selectOption('correct');await page.getByLabel(`${key} 理由`,{exact:true}).fill('按授权原文核查');await page.getByLabel(`${key} 定位 起点`,{exact:true}).fill('0');await page.getByLabel(`${key} 定位 终点`,{exact:true}).fill('7');await page.getByRole('button',{name:`加入${key} 定位`,exact:true}).click();}
 const doc=source.units.find(u=>u.unit_id===target.unit_id).contexts[0].doc_id;
 await page.getByLabel(`${doc} 理由`,{exact:true}).fill('直接含答案');await page.getByLabel(`${doc} 证据定位 起点`,{exact:true}).fill('0');await page.getByLabel(`${doc} 证据定位 终点`,{exact:true}).fill('7');await page.getByRole('button',{name:`加入${doc} 证据定位`,exact:true}).click();await page.getByLabel('预期拒答',{exact:true}).selectOption('false');await page.getByLabel('预期拒答判断理由',{exact:true}).fill('原文可答');await page.getByLabel('核实说明',{exact:true}).fill('本条核对完成');
 await page.getByRole('button',{name:'提交并封存核实',exact:true}).click();await expect(page.getByRole('button',{name:'提交并封存核实',exact:true})).toBeDisabled();
 let report=await value(await actors.lead.api.get(P+`/imports/${imported.id}/report`));expect(report.verification_completed).toBe(1);expect(report.verification_remaining).toBe(11);
 for(const t of own.slice(1)){await seal(actors.v,t,{answer:'独立答案',reason:'核对原文'});const detail=await value(await actors.v.api.get(P+`/assignments/${t.id}`));await seal(actors.v,detail,review(detail));}
 for(const name of ['a','b'])for(const t of(await tasks(actors[name])).filter(t=>t.batch_id===obs.id))await seal(actors[name],t,{answer:'独立答案',reason:'原文核对'});
 await post(actors.lead,`/observation-batches/${obs.id}/release-review`,{});
 for(const name of ['a','b'])for(const t of(await tasks(actors[name])).filter(t=>t.batch_id===obs.id)){const d=await value(await actors[name].api.get(P+`/assignments/${t.id}`));await seal(actors[name],d,review(d));}
 const quality=await post(actors.lead,`/observation-batches/${obs.id}/observe`,{});expect(quality.pair_count).toBe(8);expect(quality.kappa).toBeNull();
 report=await value(await actors.lead.api.get(P+`/imports/${imported.id}/report`));expect(report.verification_completed).toBe(12);expect(report.n).toBe(8);expect(report.readiness).toBe('WAITING_POLICY');
 const queued=await post(actors.lead,'/handoffs',{import_id:imported.id},202);let job;await expect.poll(async()=>{job=await value(await actors.lead.api.get(P+`/jobs/${queued.job_id}`));return job.state;},{timeout:30000}).toBe('DONE');
 const handoff=await value(await actors.lead.api.get(P+`/handoffs/${job.result.handoff_id}`));expect(handoff.manifest.unit_count).toBe(12);expect(handoff.manifest.sample_count).toBe(8);expect(handoff.manifest.formal_credential).toBe(false);
 writeFileSync(resolve(root,'var/evidence/v13-browser-summary.json'),JSON.stringify({synthetic_only:true,human_acceptance:'NOT_PERFORMED',import_id:imported.id,verification_batch:main.id,observation_batch:obs.id,handoff_id:handoff.id,manifest:handoff.manifest,report,geometry},null,2));
 for(const who of Object.values(actors))await who.api.dispose();
});
