import {test,expect,request} from 'playwright/test';
import {readFileSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {randomUUID} from 'node:crypto';

const root=resolve(import.meta.dirname,'../..');
const values=Object.fromEntries(readFileSync(resolve(root,'.env.v13-e2e'),'utf8').trim().split(/\r?\n/).map(line=>{const n=line.indexOf('=');return[line.slice(0,n),line.slice(n+1)];}));
async function login(page,name){
 await page.goto('/');await page.getByLabel('账号',{exact:true}).fill('v13-e2e-'+name);await page.getByLabel('密码',{exact:true}).fill(values.S4_V13_E2E_PASSWORD);
 await page.getByRole('button',{name:'登录工作台',exact:true}).click();await expect(page.getByRole('button',{name:'退出登录',exact:true})).toBeVisible();
}
test('independent local profile approval binds a visible frozen manual without formal credentials',async({page})=>{
 const run=randomUUID().slice(0,8),version='profile-browser-'+run,manual='manual-browser-'+run;
 await login(page,'lead');await page.getByRole('link',{name:'当前任务配置',exact:true}).click();
 await page.getByLabel('配置版本',{exact:true}).fill(version);await page.getByLabel('手册版本',{exact:true}).fill(manual);
 await page.getByLabel('操作说明',{exact:true}).fill('按合成冻结原文核对，保持独立阶段。');
 await page.getByLabel('核实指南正文',{exact:true}).fill('这是合成浏览器演练指南，不代表真实批准或真人验收。');
 await page.getByLabel('配置变更理由',{exact:true}).fill('合成自动化：验证新版配置页面与服务端连接');
 await page.getByRole('button',{name:'创建配置草稿',exact:true}).click();
 let row=page.locator('tr').filter({hasText:version});await expect(row).toContainText('草稿');
 await page.getByLabel('审批或停用理由',{exact:true}).fill('合成演练提交独立测试身份评审');await row.getByRole('button',{name:'提交配置评审',exact:true}).click();await expect(row).toContainText('待独立评审');
 await page.getByRole('button',{name:'退出登录',exact:true}).click();await login(page,'auditor');await page.getByRole('link',{name:'当前任务配置',exact:true}).click();
 row=page.locator('tr').filter({hasText:version});await expect(row).toContainText('待独立评审');
 await page.getByLabel('审批或停用理由',{exact:true}).fill('仅合成自动化核对，不作真实评审');await page.getByLabel('批准署名',{exact:true}).fill('SYNTHETIC browser auditor');await page.getByLabel('审批依据',{exact:true}).fill('合成端到端测试，无外部批准效力');
 await row.getByRole('button',{name:'独立批准',exact:true}).click();await expect(row).toContainText('本地配置已批准');
 await page.screenshot({path:resolve(root,'var/evidence/backlog-20261105/profile-approved.png'),fullPage:true});
 const api=await request.newContext({baseURL:'http://127.0.0.1:8004'});
 try{
  const logged=await api.post('/api/s4/v1/auth/login',{data:{username:'v13-e2e-lead',password:values.S4_V13_E2E_PASSWORD}});expect(logged.status()).toBe(200);
  const auth=await logged.json(),headers={'X-CSRF-Token':auth.csrf_token};
  const profiles=await(await api.get('/api/s4/v2/profile-revisions')).json();const profile=profiles.items.find(p=>p.version===version);expect(profile.snapshot.formal_enabled).toBe(false);
  const who=await(await api.get('/api/s4/v1/users')).json();const worker=who.items.find(x=>x.username==='v13-e2e-v');
  const doc='profile-doc-'+run;
  const source={contract_version:'openkb.s3-s4.v2',mode:'demo',batch_id:'PROFILE-BROWSER-'+run,source_revision:'r1',units:[{unit_id:'QA-D1-profile-'+run,dataset:'QA-D1',difficulty:'easy',question:'合成服务办理要求是什么？',contexts:[{doc_id:doc,text:'合成服务须五日内办理。'}],gold:{answer_points:['五日内办理'],gold_doc_ids:[doc],relevance_grades:{[doc]:3},ranking_annotations:{},expected_refusal:false,absence_reason:null},metadata:{generation_model:'synthetic-profile-browser'}}]};
  const imported=await api.post('/api/s4/v2/imports',{headers,data:source});expect(imported.status()).toBe(201);const identity=(await imported.json()).id;
  await page.getByRole('button',{name:'退出登录',exact:true}).click();await login(page,'lead');await page.goto('/v13/imports/'+identity);
  await page.getByRole('option',{name:version+' · '+manual,exact:true}).waitFor({state:'attached'});await page.getByLabel('冻结配置',{exact:true}).selectOption(profile.id);
  await page.getByRole('checkbox',{name:new RegExp('合成演练v ·')}).check();await page.getByRole('button',{name:'创建全量核实计划',exact:true}).click();await expect(page.getByRole('heading',{name:'计划进度与质量动作',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'退出登录',exact:true}).click();await login(page,'v');
  const workerApi=await request.newContext({baseURL:'http://127.0.0.1:8004'});
  let task;
  try{await workerApi.post('/api/s4/v1/auth/login',{data:{username:worker.username,password:values.S4_V13_E2E_PASSWORD}});task=(await(await workerApi.get('/api/s4/v2/me/tasks?limit=500')).json()).items.find(x=>x.unit_id===source.units[0].unit_id);}finally{await workerApi.dispose();}
  expect(task).toBeTruthy();await page.goto('/v13/tasks/'+task.id);await expect(page.getByLabel('新版独立判断')).toBeVisible();await page.getByText('本批冻结操作指南 · '+manual,{exact:true}).click();
  await expect(page.getByText('这是合成浏览器演练指南，不代表真实批准或真人验收。',{exact:true})).toBeVisible();
  await page.screenshot({path:resolve(root,'var/evidence/backlog-20261105/profile-frozen-guidance.png'),fullPage:true});
  writeFileSync(resolve(root,'var/evidence/backlog-20261105/profile-browser-summary.json'),JSON.stringify({synthetic_only:true,human_acceptance:'NOT_PERFORMED',profile_revision_id:profile.id,profile_hash:profile.canonical_hash,import_id:identity,assignment_id:task.id,formal_enabled:false},null,2));
 }finally{await api.dispose();}
});
