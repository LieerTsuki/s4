import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { V13Handoffs } from "../v13/Handoffs";

afterEach(()=>vi.unstubAllGlobals());
it("下载候选包不伪造发送或接收，只列服务端已封存文件",async()=>{
  const calls:string[]=[];
  vi.stubGlobal("fetch",vi.fn((url:string,init:RequestInit={})=>{
    calls.push(`${init.method??"GET"} ${url}`);
    return Promise.resolve(new Response(JSON.stringify(url.includes("/imports")?{items:[],total:0}:{items:[{id:"handoff-1",import_id:"import-1",mode:"demo",status:"DEMO_READY",external_status:"NOT_ALIGNED",manifest:{files:{"verified_annotations.jsonl":{sha256:"a".repeat(64),rows:12},"iaa_records.jsonl":{sha256:"b".repeat(64),rows:8}}},blocked_reasons:[]}],total:1}),{status:200}));
  }));
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter><V13Handoffs canWrite/></MemoryRouter></QueryClientProvider>);
  expect(await screen.findByRole("link",{name:"verified_annotations.jsonl"})).toHaveAttribute("href","/api/s4/v2/handoffs/handoff-1/files/verified_annotations.jsonl");
  expect(screen.getByRole("link",{name:"下载交接清单"})).toHaveAttribute("href","/api/s4/v2/handoffs/handoff-1/files/s4_handoff_manifest.json");
  expect(screen.getByText("N条核实记录与n条IAA分别保存；下载不代表已发送或S5已接收。")).toBeInTheDocument();
  expect(calls.every(c=>c.startsWith("GET"))).toBe(true);
});

it("生成交接包进入持久job等待，不把202当READY",async()=>{
  const requests:{path:string;body:unknown}[]=[];
  vi.stubGlobal("fetch",vi.fn((url:string,init:RequestInit={})=>{
    if(init.method==="POST")requests.push({path:url,body:JSON.parse(String(init.body)) as unknown});
    const value=init.method==="POST"?{job_id:"job-1"}:url.includes("/jobs/")?{id:"job-1",state:"PENDING"}:url.includes("/imports")?{items:[{id:"import-1",batch_id:"生产批1"}],total:1}:{items:[],total:0};
    return Promise.resolve(new Response(JSON.stringify(value),{status:init.method==="POST"?202:200}));
  }));
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter><V13Handoffs canWrite/></MemoryRouter></QueryClientProvider>);
  await screen.findByRole("option",{name:/生产批1/});
  await userEvent.selectOptions(screen.getByLabelText("交接来源批次"),"import-1");
  fireEvent.click(screen.getByRole("button",{name:"生成新版过程交接包"}));
  await waitFor(()=>expect(requests).toEqual([{path:"/api/s4/v2/handoffs",body:{import_id:"import-1"}}]));
  expect(await screen.findByText("后台任务：PENDING")).toBeInTheDocument();
});
