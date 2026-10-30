import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TaskIssue, V13Governance, BatchMaintenance } from "../v13/Governance";
import type { User } from "../types";
import type { V13Batch } from "../v13/types";

afterEach(()=>vi.unstubAllGlobals());
function mount(node:React.ReactNode) {
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter>{node}</MemoryRouter></QueryClientProvider>);
}
function server(rows:Record<string,unknown>={}) {
  const calls:{path:string;method:string;body:Record<string,unknown>}[]=[];
  vi.stubGlobal("fetch",vi.fn((url:string,init:RequestInit={})=>{
    const path=url.split("?")[0],method=init.method??"GET",body=init.body?JSON.parse(String(init.body)) as Record<string,unknown>:{};
    calls.push({path,method,body});
    return Promise.resolve(new Response(JSON.stringify(method==="GET"?(rows[path]??{items:[],total:0}):{id:"created",status:"RESOLVED"}),{status:200}));
  }));return calls;
}
const user:User={id:"lead",username:"lead",display_name:"核实运营",person_id:"real-lead",roles:["lead"],active:true};
const batch:V13Batch={id:"b1",import_id:"i1",dataset:"QA-D1",workflow_kind:"OBSERVATION",state:"REVIEW_OPEN",selected_ids:["u1"],sample_count:1,blind_submitted:2,review_submitted:0,verification_completed:0,blocked_reasons:[],assignments:[{id:"a1",unit_index_id:"ix1",user_id:"a",seat:"A",phase:"REVIEW",status:"OPEN"}]};

describe("v1.3 材料、补派与独立复验",()=>{
  it("任务问题绑定当前单元，不提交他人的身份",async()=>{
    const calls=server();mount(<TaskIssue unitIndexId="ix1"/>);
    await userEvent.type(screen.getByLabelText("材料问题说明"),"原文摘要与材料不一致");
    await userEvent.click(screen.getByRole("button",{name:"提交材料问题并暂停相关任务"}));
    await waitFor(()=>expect(calls.find(c=>c.method==="POST")?.body).toEqual({unit_index_id:"ix1",reason:"原文摘要与材料不一致"}));
  });
  it("解决问题需要实际说明和证据，不能自动把原批标记通过",async()=>{
    const calls=server({"/api/s4/v2/issues":{items:[{id:"issue1",unit_index_id:"ix1",import_id:"i1",status:"OPEN",reason:"缺原文"}],total:1}});
    mount(<V13Governance user={user}/>);
    fireEvent.change(await screen.findByLabelText("issue1 解决说明"),{target:{value:"核对相同版本文件恢复成功"}});
    fireEvent.change(screen.getByLabelText("issue1 解决证据"),{target:{value:'{"file_sha256":"approved-copy"}'}});
    await userEvent.click(screen.getByRole("button",{name:"封存材料问题处理"}));
    await waitFor(()=>expect(calls.some(c=>c.path==="/api/s4/v2/issues/issue1/resolve")).toBe(true));
    expect(calls.find(c=>c.path.endsWith("/resolve"))?.body).toEqual({reason:"核对相同版本文件恢复成功",evidence:{file_sha256:"approved-copy"}});
  });
  it("独立复验须人工提交结果与实际证据",async()=>{
    const calls=server({"/api/s4/v2/revisions":{items:[{id:"rev1",unit_index_id:"ix1",verifier_id:"lead",status:"PENDING",candidate:{unit_id:"u1"},proposal:{reason:"修正证据等级"}}],total:1}});
    mount(<V13Governance user={{...user,roles:["verifier"]}}/>);
    fireEvent.change(await screen.findByLabelText("rev1 复验说明"),{target:{value:"独立核查最终候选"}});
    fireEvent.change(screen.getByLabelText("rev1 复验证据"),{target:{value:'{"validation_id":"real-evidence"}'}});
    await userEvent.click(screen.getByRole("button",{name:"封存独立复验结果"}));
    await waitFor(()=>expect(calls.find(c=>c.path.endsWith("/verify"))?.body).toEqual({outcome:"PASS",reason:"独立核查最终候选",evidence:{validation_id:"real-evidence"}}));
  });
  it("运营从授权单元载入冻结候选，再提出新版修订与独立复验",async()=>{
    const calls=server({"/api/s4/v2/imports":{items:[{id:"i1",batch_id:"B1"}],total:1},"/api/s4/v2/imports/i1":{units:[{unit_id:"u1",unit_index_id:"ix1"}]},"/api/s4/v2/units/ix1":{candidate:{unit_id:"u1",gold:{expected_refusal:false}}},"/api/s4/v1/users":{items:[{...user,id:"verifier1",display_name:"复验员",roles:["verifier"]}],total:1}});
    mount(<V13Governance user={user}/>);
    await screen.findByRole("option",{name:"B1"});
    await userEvent.selectOptions(screen.getByLabelText("修订来源"),"i1");
    await screen.findByRole("option",{name:"u1"});
    await userEvent.selectOptions(screen.getByLabelText("修订单元"),"ix1");
    await userEvent.selectOptions(screen.getByLabelText("指定独立复验员"),"verifier1");
    await userEvent.click(screen.getByRole("button",{name:"载入当前授权候选"}));
    await waitFor(()=>expect((screen.getByLabelText("完整修订候选") as HTMLTextAreaElement).value).toContain('"u1"'));
    fireEvent.change(screen.getByLabelText("修订理由"),{target:{value:"核实指出需要修正条件"}});
    await userEvent.click(screen.getByRole("button",{name:"提交候选并等待独立复验"}));
    await waitFor(()=>expect(calls.find(c=>c.method==="POST")?.body).toEqual({unit_index_id:"ix1",verifier_id:"verifier1",candidate:{unit_id:"u1",gold:{expected_refusal:false}},reason:"核实指出需要修正条件"}));
  });
  it("REVIEW换人创建完整新轮，不能补派单条冒认原独立结果",async()=>{
    const calls=server({"/api/s4/v1/users":{items:[{...user,id:"c",display_name:"替补丙",roles:["annotator"]},{...user,id:"d",display_name:"替补丁",roles:["annotator"]}],total:2}});
    mount(<BatchMaintenance batch={batch}/>);
    await screen.findAllByRole("option",{name:/替补丙/});
    await userEvent.selectOptions(await screen.findByLabelText("新轮观测员A"),"c");
    await userEvent.selectOptions(screen.getByLabelText("新轮观测员B"),"d");
    fireEvent.change(screen.getByLabelText("新轮原因"),{target:{value:"原观测员离场，按完整范围重新独立作答"}});
    await userEvent.click(screen.getByRole("button",{name:"保留原轮并启动完整新轮"}));
    await waitFor(()=>expect(calls.find(c=>c.path.endsWith("/new-round"))?.body).toEqual({reason:"原观测员离场，按完整范围重新独立作答",annotator_a:"c",annotator_b:"d"}));
    expect(calls.some(c=>c.path.endsWith("/replace"))).toBe(false);
  });
  it("质量扩样创建关联原报告的新观测计划，不只写一条扩样日志",async()=>{
    const calls=server({"/api/s4/v1/users":{items:[{...user,id:"c",display_name:"扩样丙",roles:["annotator"]},{...user,id:"d",display_name:"扩样丁",roles:["annotator"]}],total:2}});
    mount(<BatchMaintenance batch={{...batch,state:"OBSERVED",quality:{kappa:0.65,action:"EXPAND_CALIBRATE"},selected_ids:Array.from({length:8},(_,i)=>`u${i}`)}}/>);
    await screen.findAllByRole("option",{name:/扩样丙/});
    await userEvent.selectOptions(screen.getByLabelText("扩样观测员A"),"c");
    await userEvent.selectOptions(screen.getByLabelText("扩样观测员B"),"d");
    fireEvent.change(screen.getByLabelText("扩样单元数量"),{target:{value:"10"}});
    await userEvent.click(screen.getByRole("button",{name:"冻结扩样范围并分配独立人员"}));
    await waitFor(()=>expect(calls.find(c=>c.method==="POST")?.body).toEqual({import_id:"i1",dataset:"QA-D1",annotator_a:"c",annotator_b:"d",parent_id:"b1",expanded_count:10,seed:20261030,manual_version:"manual-v1.3",profile_version:"s4-v1.3"}));
  });
});
