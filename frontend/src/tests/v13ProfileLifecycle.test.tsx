import {QueryClient,QueryClientProvider} from "@tanstack/react-query";
import {render,screen,waitFor,within} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {afterEach,describe,expect,it,vi} from "vitest";
import {ProfileLifecycle} from "../v13/ProfileLifecycle";
import type {User} from "../types";
import {MemoryRouter,Route,Routes} from "react-router-dom";
import {V13ImportDetail} from "../v13/Pages";
import {V13Workspace} from "../v13/Workspace";

afterEach(()=>vi.unstubAllGlobals());
const lead:User={id:"lead",username:"lead",display_name:"运营",person_id:"P-L",roles:["lead"],active:true};
const auditor:User={...lead,id:"audit",person_id:"P-A",roles:["auditor"]};
const snapshot={dataset:"QA-D1",version:"draft-1",manual_version:"manual-1",title:"核实配置",instructions:"原操作说明",manual_text:"指南正文",formal_enabled:false};
const revision={id:"profile-1",dataset:"QA-D1",version:"draft-1",manual_version:"manual-1",state:"DRAFT",revision:3,canonical_hash:"a".repeat(64),creator_id:"lead",snapshot};
function mount(user:User){render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><ProfileLifecycle user={user}/></QueryClientProvider>);}
function server(rows:unknown[]=[revision],conflict=false){
 const calls:{path:string;method:string;body:Record<string,unknown>}[]=[];
 vi.stubGlobal("fetch",vi.fn(async(url:string,init:RequestInit={})=>{
  const path=url.split("?")[0],method=init.method??"GET",body=init.body?JSON.parse(String(init.body)) as Record<string,unknown>:{};calls.push({path,method,body});
  const failed=conflict&&method==="PATCH";
  return new Response(JSON.stringify(failed?{error_code:"VERSION_CONFLICT",message:"版本已变化，请刷新后确认"}:method==="GET"?(path.endsWith("/template")?snapshot:{items:rows,total:rows.length}):{...revision,revision:4}),{status:failed?409:200});
 }));return calls;
}
describe("新版配置生命周期",()=>{
 it("审计员可核对待批版本和完整配置正文，只读展示后再独立批准",async()=>{
  const review={...revision,state:"REVIEW",snapshot:{...snapshot,instructions:"审核前逐项核对冻结配置",manual_text:"<script>这是待签名的指南正文</script>",review_schema:{required:["point_labels","expected_refusal"]}}};
  const calls=server([review]);mount(auditor);
  await userEvent.click(await screen.findByText("查看配置内容 · QA-D1 · draft-1"));
  const detail=within(screen.getByRole("region",{name:"配置只读详情 QA-D1 draft-1"}));
  expect(detail.getByText("审核前逐项核对冻结配置")).toBeVisible();
  expect(detail.getByText("<script>这是待签名的指南正文</script>")).toBeVisible();
  expect(detail.getByLabelText("完整配置快照")).toHaveTextContent('"point_labels"');
  expect(detail.getByText("a".repeat(64))).toBeVisible();
  expect(detail.getByText("记录版本 3 · 手册 manual-1")).toBeVisible();
  expect(screen.queryByLabelText("核实指南正文")).not.toBeInTheDocument();
  expect(document.querySelector("script")).toBeNull();
  await userEvent.type(screen.getByLabelText("审批或停用理由"),"逐项核对所示版本");
  await userEvent.type(screen.getByLabelText("批准署名"),"独立审核人");
  await userEvent.type(screen.getByLabelText("审批依据"),"已核对当前只读快照");
  await userEvent.click(screen.getByRole("button",{name:"独立批准"}));
  await waitFor(()=>expect(calls.find(c=>c.path.endsWith("/approve"))?.body.expected_revision).toBe(3));
 });
 it("运营用有限模板创建草稿，正式启用状态不由浏览器修改",async()=>{
  const calls=server([]);mount(lead);
  await userEvent.type(screen.getByLabelText("配置版本"),"v13-team-1");
  await userEvent.type(screen.getByLabelText("手册版本"),"manual-team-1");
  await userEvent.type(screen.getByLabelText("配置变更理由"),"补充已复核的操作指南");
  await userEvent.click(screen.getByRole("button",{name:"创建配置草稿"}));
  await waitFor(()=>expect(calls.some(c=>c.method==="POST")).toBe(true));
  const body=calls.find(c=>c.method==="POST")!.body;
  expect(body.version).toBe("v13-team-1");expect(body.manual_version).toBe("manual-team-1");expect((body.snapshot as typeof snapshot).formal_enabled).toBe(false);
 });
 it("保存草稿携带读取的版本，冲突后保留编辑内容",async()=>{
  const calls=server([revision],true);mount(lead);
  await userEvent.click(await screen.findByRole("button",{name:"编辑配置草稿"}));
  await userEvent.clear(screen.getByLabelText("操作说明"));await userEvent.type(screen.getByLabelText("操作说明"),"修改后说明");
  await userEvent.type(screen.getByLabelText("配置变更理由"),"修订说明");await userEvent.click(screen.getByRole("button",{name:"保存配置草稿"}));
  expect(await screen.findByText("版本已变化，请刷新后确认")).toBeVisible();
  expect(screen.getByLabelText("操作说明")).toHaveValue("修改后说明");expect(calls.find(c=>c.method==="PATCH")!.body.expected_revision).toBe(3);
 });
 it("独立审计员批准时提交实际签名和依据，保留版本保护",async()=>{
  const calls=server([{...revision,state:"REVIEW"}]);mount(auditor);
  await userEvent.type(screen.getByLabelText("审批或停用理由"),"已核对指南与量表");await userEvent.type(screen.getByLabelText("批准署名"),"测试审计员");await userEvent.type(screen.getByLabelText("审批依据"),"真实评审记录编号");
  await userEvent.click(await screen.findByRole("button",{name:"独立批准"}));
  await waitFor(()=>expect(calls.some(c=>c.path.endsWith("/approve"))).toBe(true));
  const action=calls.find(c=>c.path.endsWith("/approve"))!.body;expect(action.expected_revision).toBe(3);expect(action.signature).toBe("测试审计员");expect(action.evidence).toEqual({basis:"真实评审记录编号"});
  expect(screen.queryByRole("button",{name:"创建配置草稿"})).not.toBeInTheDocument();
 });
 it("创建者兼审计员也不能在页面自批，批准后仅提供停用",async()=>{
  server([{...revision,state:"REVIEW"},{...revision,id:"approved",state:"APPROVED"}]);mount({...lead,roles:["lead","auditor"]});
  expect(await screen.findByRole("button",{name:"独立批准"})).toBeDisabled();
  expect(screen.getByRole("button",{name:"停用于新分发"})).toBeDisabled();
  expect(screen.queryByRole("button",{name:"编辑配置草稿"})).not.toBeInTheDocument();
 });
 it("提交和停用记录实际理由且不自动批准",async()=>{
  const calls=server([revision,{...revision,id:"approved",state:"APPROVED"}]);mount(lead);
  await userEvent.type(screen.getByLabelText("审批或停用理由"),"确认进入下一状态");
  await userEvent.click(await screen.findByRole("button",{name:"提交配置评审"}));await userEvent.click(screen.getByRole("button",{name:"停用于新分发"}));
  await waitFor(()=>expect(calls.some(c=>c.path.endsWith("/retire"))).toBe(true));
  expect(calls.filter(c=>c.method==="POST").map(c=>c.path.split("/").at(-1))).toEqual(["submit","retire"]);
 });
 it("建队只列出本数据集已批准配置，并冻结选择的版本标识",async()=>{
  const calls:Record<string,unknown>[]=[];
  const worker={...lead,id:"worker",display_name:"主核实员",roles:["annotator"]};
  vi.stubGlobal("fetch",vi.fn(async(url:string,init:RequestInit={})=>{
   const path=url.split("?")[0];let data:unknown={items:[],total:0};
   if(path.endsWith("/users"))data={items:[worker],total:1};
   if(path.endsWith("/profile-revisions"))data={items:[{...revision,state:"APPROVED"},{...revision,id:"draft",version:"未批准版本"},{...revision,id:"other",dataset:"QA-D6",state:"APPROVED",version:"其他数据集版本"}],total:3};
   if(path.endsWith("/imports/source-1"))data={id:"source-1",batch_id:"test",units:[{dataset:"QA-D1"}]};
   if(init.method==="POST"){calls.push(JSON.parse(String(init.body)));data={id:"created"};}
   return new Response(JSON.stringify(data),{status:200});
  }));
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter initialEntries={["/v13/imports/source-1"]}><Routes><Route path="/v13/imports/:id" element={<V13ImportDetail canWrite/>}/><Route path="/v13/batches/:id" element={<p>计划已创建</p>}/></Routes></MemoryRouter></QueryClientProvider>);
  await screen.findByRole("option",{name:"draft-1 · manual-1"});
  await userEvent.selectOptions(screen.getByLabelText("冻结配置"),"profile-1");
  expect(screen.queryByRole("option",{name:/未批准版本|其他数据集版本/})).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("checkbox"));await userEvent.click(screen.getByRole("button",{name:"创建全量核实计划"}));
  await screen.findByText("计划已创建");expect(calls[0]).toMatchObject({profile_revision_id:"profile-1",import_id:"source-1"});expect(calls[0]).not.toHaveProperty("profile_version");
 });
 it("本人作业显示冻结指南正文和摘要，按文本展示",async()=>{
  server([]);
  render(<QueryClientProvider client={new QueryClient()}><V13Workspace task={{id:"task-1",batch_id:"batch",unit_id:"QA-D1-1",dataset:"QA-D1",workflow_kind:"VERIFICATION",phase:"BLIND",status:"OPEN",content_revision:"a".repeat(64),profile_version:"team-1",manual_version:"manual-1",material:{question:"合成题",contexts:[]},profile_guidance:{title:"核实指南",instructions:"按冻结原文核实",manual_version:"manual-1",manual_text:"<script>只作为受控文本显示</script>",snapshot_sha256:"b".repeat(64)}}}/></QueryClientProvider>);
  await userEvent.click(screen.getByText("本批冻结操作指南 · manual-1"));
  expect(screen.getByText("<script>只作为受控文本显示</script>")).toBeVisible();expect(screen.getByText("按冻结原文核实")).toBeVisible();
  expect(document.querySelector("script")).toBeNull();
 });
});
