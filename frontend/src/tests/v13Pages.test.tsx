import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { V13Imports, V13Tasks, V13ImportDetail, V13BatchDetail, V13Profiles } from "../v13/Pages";
import { V13Workspace } from "../v13/Workspace";
import { apiV2, listV2 } from "../v13/api";
import { setCsrfToken } from "../api";
import type { V13Task } from "../v13/types";

afterEach(()=>{vi.unstubAllGlobals();setCsrfToken(null);});
function mount(node:React.ReactNode,path="/",route="/") {
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter initialEntries={[path]}><Routes><Route path={route} element={node}/></Routes></MemoryRouter></QueryClientProvider>);
}
function server(rows:Record<string,unknown>={}) {
  const calls:{path:string;method:string;body:Record<string,unknown>}[]=[];
  vi.stubGlobal("fetch",vi.fn((url:string,init:RequestInit={})=>{
    const path=url.split("?")[0],method=init.method??"GET",body=init.body?JSON.parse(String(init.body)) as Record<string,unknown>:{};
    calls.push({path,method,body});
    return Promise.resolve(new Response(JSON.stringify(method==="GET"?(rows[path]??{items:[],total:0}):{id:"created",version:1}),{status:200}));
  }));return calls;
}
const task:V13Task={id:"assign-1",batch_id:"batch-1",unit_id:"QA-D1-0001",dataset:"QA-D1",workflow_kind:"VERIFICATION",phase:"BLIND",status:"PENDING",content_revision:"a".repeat(64),profile_version:"s4-v1.3",manual_version:"manual-v1.3",material:{question:"合成问题",contexts:[{doc_id:"doc-1",text:"合成原文"}]},draft:null};

describe("v1.3 真实页面操作",()=>{
  it("v2客户端共享会话CSRF，但明确使用新版本路由",async()=>{
    const fetcher=vi.fn().mockResolvedValue(new Response("{}",{status:200}));vi.stubGlobal("fetch",fetcher);setCsrfToken("session-csrf");
    await apiV2("/imports",{method:"POST",body:{contract_version:"openkb.s3-s4.v2"}});
    expect(fetcher.mock.calls[0][0]).toBe("/api/s4/v2/imports");
    expect(new Headers(fetcher.mock.calls[0][1].headers).get("X-CSRF-Token")).toBe("session-csrf");
  });
  it("分页结果变化时拒绝假装展示完整记录",async()=>{
    vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response(JSON.stringify({items:[],total:12}),{status:200})));
    await expect(listV2("/me/tasks")).rejects.toThrow("尚不完整");
  });
  it("导入明确提交v2包，不自动改写旧等级",async()=>{
    const calls=server();mount(<V13Imports canWrite/>);
    fireEvent.change(screen.getByLabelText("v1.3 候选包 JSON"),{target:{value:'{"contract_version":"openkb.s3-s4.v2","units":[]}'}});
    await userEvent.click(screen.getByRole("button",{name:"校验并接入候选"}));
    await waitFor(()=>expect(calls.some(c=>c.method==="POST"&&c.path==="/api/s4/v2/imports")).toBe(true));
    expect(calls.find(c=>c.method==="POST")?.body).toEqual({contract_version:"openkb.s3-s4.v2",units:[]});
  });
  it("我的任务把workflow_kind放到服务端过滤请求",async()=>{
    const fetcher=vi.fn().mockImplementation(()=>Promise.resolve(new Response(JSON.stringify({items:[],total:0}),{status:200})));vi.stubGlobal("fetch",fetcher);mount(<V13Tasks/>);
    await userEvent.click(screen.getByRole("button",{name:"双人观测"}));
    await waitFor(()=>expect(fetcher.mock.calls.some(c=>String(c[0]).includes("workflow_kind=OBSERVATION"))).toBe(true));
    expect(await screen.findByText("当前没有本人任务")).toBeInTheDocument();
  });
  it("当前任务配置从v2读取D4C和新版配额，不使用历史12集配置",async()=>{
    const calls=server({"/api/s4/v2/profiles":[{dataset:"QA-D4C",quota:100,kind:"qa",version:"s4-v1.3",manual_version:"manual-v1.3",formal_enabled:false,blocked_reasons:["POLICY_J1_C1_PENDING"]}]});
    mount(<V13Profiles/>);
    expect(await screen.findByText("QA-D4C")).toBeInTheDocument();
    expect(screen.getByText("POLICY_J1_C1_PENDING")).toBeInTheDocument();
    expect(calls.some(call=>call.path==="/api/s4/v1/profiles")).toBe(false);
  });
  it("主核实独立封存不声称等待全量A/B，提交绑定服务端冻结版本",async()=>{
    const calls=server();mount(<V13Workspace task={task}/>);
    expect(screen.getByText(/主核实：本人本单元/)).toBeInTheDocument();
    expect(screen.queryByLabelText("预期拒答")).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("新版独立判断"),"根据合成原文独立判断");
    await userEvent.type(screen.getByLabelText("新版独立理由"),"查阅授权原文");
    await userEvent.click(screen.getByRole("button",{name:"提交并封存独立判断"}));
    await waitFor(()=>expect(calls.some(c=>c.path.endsWith("/submit"))).toBe(true));
    expect(calls.find(c=>c.path.endsWith("/submit"))?.body).toEqual({phase:"BLIND",content_revision:task.content_revision,profile_version:task.profile_version,payload:{answer:"根据合成原文独立判断",reason:"查阅授权原文"}});
  });
  it("观测页面保留全批固定A/B屏障说明",()=>{
    mount(<V13Workspace task={{...task,workflow_kind:"OBSERVATION"}}/>);
    expect(screen.getByText(/固定A\/B完成本统计批全部独立判断后/)).toBeInTheDocument();
  });
  it("D6独立阶段使用片段实体编辑器，提交本人标注而非预标",async()=>{
    const calls=server();mount(<V13Workspace task={{...task,dataset:"QA-D6",material:{text:"甲😀乙",contexts:[]},vocabulary:{entity_types:["PERSON","OTHER"],relation_types:["OTHER_REL"],version:"fixture-v1",sha256:"a".repeat(64)}}}/>);
    const source=screen.getByLabelText("抽取片段原文");
    fireEvent.select(source,{target:{selectionStart:0,selectionEnd:1}});
    await userEvent.click(screen.getByRole("button",{name:"添加选中实体"}));
    await userEvent.type(screen.getByLabelText("新版独立判断"),"片段包含人物甲");
    await userEvent.type(screen.getByLabelText("新版独立理由"),"按原文跨度核查");
    await userEvent.click(screen.getByRole("button",{name:"提交并封存独立判断"}));
    await waitFor(()=>expect(calls.some(c=>c.path.endsWith("/submit"))).toBe(true));
    const payload=calls.find(c=>c.path.endsWith("/submit"))?.body.payload as {extraction:{gold_entities:unknown[]}};
    expect(payload.extraction.gold_entities).toEqual([expect.objectContaining({name:"甲",span:[0,1],type:"PERSON"})]);
  });
  it("QA-D5核实阶段可查冻结关键事实，独立阶段不显示草案关联材料",()=>{
    server();const {unmount}=render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><V13Workspace task={{...task,dataset:"QA-D5",phase:"REVIEW",material:{...task.material,key_facts:["锚点事实一","锚点事实二","锚点事实三"]},gold:{answer_points:[]}}}/></MemoryRouter></QueryClientProvider>);
    expect(screen.getByText(/锚点事实一/)).toBeInTheDocument();
    unmount();mount(<V13Workspace task={task}/>);
    expect(screen.queryByText("草案关联材料（核实阶段）")).not.toBeInTheDocument();
  });
  it("D6核实阶段分别显示本人独立结果与冻结预标，不把预标自动当本人标注",()=>{
    server();mount(<V13Workspace task={{...task,dataset:"QA-D6",phase:"REVIEW",material:{text:"甲乙",contexts:[]},own_blind:{answer:"本人独立判断",extraction:{gold_entities:[{entity_id:"own-e1",name:"甲",type:"OTHER",span:[0,1]}],gold_relations:[]}},gold:{gold_entities:[{entity_id:"model-e1",name:"模型预标乙",type:"OTHER",span:[1,2]}],gold_relations:[]}}}/>);
    expect(screen.getByText("冻结模型预标（仅核实阶段）")).toBeInTheDocument();
    expect(screen.getByText(/模型预标乙/)).toBeInTheDocument();
    expect(screen.getByRole("button",{name:"删除实体 own-e1"})).toBeDisabled();
    expect(screen.queryByRole("button",{name:"删除实体 model-e1"})).not.toBeInTheDocument();
  });
  it("D6缺词表不能签通过，但能按专项字段封存需要修订的真实问题",async()=>{
    const calls=server();mount(<V13Workspace task={{...task,dataset:"QA-D6",phase:"REVIEW",material:{text:"甲乙",contexts:[]},gold:{gold_entities:[],gold_relations:[]}}}/>);
    await userEvent.selectOptions(screen.getByLabelText("专项核实结论"),"VERIFIED");
    fireEvent.change(screen.getByLabelText("专项核实说明"),{target:{value:"材料缺少已登记词表"}});
    await userEvent.click(screen.getByRole("button",{name:"提交并封存专项核实"}));
    expect(calls.some(call=>call.path.endsWith("/submit"))).toBe(false);
    expect(screen.getByText(/D6完整词表未登记时不能提交核实通过/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("专项核实结论"),"NEEDS_REVISION");
    for(const name of ["entity_spans","entity_types","relation_links"]){
      await userEvent.selectOptions(screen.getByLabelText(`${name} 判断`),"issue");
      fireEvent.change(screen.getByLabelText(`${name} 理由`),{target:{value:"等待规范词表与坐标复核"}});
    }
    await userEvent.click(screen.getByRole("button",{name:"保存专项草稿"}));
    expect(await screen.findByText("专项草稿已保存。")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button",{name:"提交并封存专项核实"}));
    await waitFor(()=>expect(calls.some(call=>call.path.endsWith("/submit"))).toBe(true));
    expect(calls.find(call=>call.path.endsWith("/submit"))?.body.payload).toEqual(expect.objectContaining({verdict:"NEEDS_REVISION",extraction:{gold_entities:[],gold_relations:[]},specialized_review:{entity_spans:expect.objectContaining({observation:"issue"}),entity_types:expect.objectContaining({observation:"issue"}),relation_links:expect.objectContaining({observation:"issue"})}}));
  });
  it("创建主核实计划传多人员与N范围而不是A/B观测参数",async()=>{
    const calls=server({"/api/s4/v2/imports/import-1":{id:"import-1",batch_id:"B1",units:[{unit_id:"QA-D1-0001",dataset:"QA-D1",difficulty:"easy"}]},"/api/s4/v2/imports/import-1/report":{N:12,verified_count:8,n:8},"/api/s4/v1/users":{items:[{id:"one",person_id:"real-one",display_name:"核实甲",roles:["annotator"],active:true}],total:1}});
    mount(<V13ImportDetail canWrite/>,"/v13/imports/import-1","/v13/imports/:id");
    await userEvent.click(await screen.findByRole("checkbox"));
    await userEvent.click(screen.getByRole("button",{name:"创建全量核实计划"}));
    await waitFor(()=>expect(calls.some(c=>c.method==="POST")).toBe(true));
    expect(calls.find(c=>c.method==="POST")?.body).toEqual({import_id:"import-1",dataset:"QA-D1",assignee_ids:["one"],manual_version:"manual-v1.3",profile_version:"s4-v1.3"});
  });
  it("观测开放与复算走两个独立端点，原κ不作为自动通过",async()=>{
    const calls=server({"/api/s4/v2/batches/batch-1":{id:"batch-1",import_id:"import-1",dataset:"QA-D1",workflow_kind:"OBSERVATION",state:"BLIND_OPEN",selected_ids:["QA-D1-0001"],blind_submitted:1,review_submitted:0,verification_completed:0,blocked_reasons:[],quality:{kappa:null,status:"UNDEFINED"}}});
    mount(<V13BatchDetail canWrite/>,"/v13/batches/batch-1","/v13/batches/:id");
    await userEvent.click(await screen.findByRole("button",{name:"核对全批独立封存并开放复核"}));
    await waitFor(()=>expect(calls.some(c=>c.path.endsWith("/release-review"))).toBe(true));
    await userEvent.click(screen.getByRole("button",{name:"复算原始观测"}));
    await waitFor(()=>expect(calls.some(c=>c.path.endsWith("/observe"))).toBe(true));
    expect(screen.getByText("原κ：未定义")).toBeInTheDocument();
  });
});
