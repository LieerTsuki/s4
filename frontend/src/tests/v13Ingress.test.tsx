import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { V13Imports } from "../v13/Pages";

afterEach(()=>vi.unstubAllGlobals());
function mount() {render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter><V13Imports canWrite/></MemoryRouter></QueryClientProvider>);}
function server(response:Record<string,unknown>,status=200) {
  const calls:{path:string;body:Record<string,unknown>}[]=[];
  vi.stubGlobal("fetch",vi.fn((path:string,init:RequestInit={})=>{
    const post=init.method==="POST";
    if(post)calls.push({path,body:JSON.parse(String(init.body)) as Record<string,unknown>});
    return Promise.resolve(new Response(JSON.stringify(post?response:{items:[],total:0}),{status:post?status:200}));
  }));return calls;
}

describe("v1.3 逐条校验与原始JSONL",()=>{
  it("预检查显示多行错误，且不会自动创建导入",async()=>{
    const calls=server({valid:false,total_rows:3,error_count:2,errors:[{row:1,unit_id:"u1",error_code:"GOLD_GRADE_INVALID",message:"gold不能含1"},{row:3,unit_id:"u3",error_code:"REFUSAL_INVALID",message:"拒答必须为boolean"}]});
    mount();fireEvent.change(screen.getByLabelText("v1.3 候选包 JSON"),{target:{value:'{"contract_version":"openkb.s3-s4.v2","units":[]}'}});
    await userEvent.click(screen.getByRole("button",{name:"仅检查候选包，不接入"}));
    expect(await screen.findByText("GOLD_GRADE_INVALID")).toBeInTheDocument();
    expect(screen.getByText("REFUSAL_INVALID")).toBeInTheDocument();
    expect(calls.map(call=>call.path)).toEqual(["/api/s4/v2/imports/validate"]);
  });
  it("原始JSONL按字节上传，BOM和换行保留，元信息不含units",async()=>{
    const calls=server({id:"import-1",raw_file_sha256:"a".repeat(64),validation_report:{valid:true,total_rows:1,error_count:0,errors:[]}},201);
    mount();
    fireEvent.change(screen.getByLabelText("v1.3 候选包 JSON"),{target:{value:'{"contract_version":"openkb.s3-s4.v2","mode":"demo","batch_id":"B1","source_revision":"r1","units":[{"unit_id":"u1"}]}'}});
    await userEvent.click(screen.getByRole("button",{name:"从完整候选包提取元信息"}));
    const raw=new Uint8Array([0xef,0xbb,0xbf,0x7b,0x7d,0x0d,0x0a]);
    const file=new File([raw],"synthetic.jsonl",{type:"application/x-ndjson"});
    Object.defineProperty(file,"arrayBuffer",{value:async()=>raw.buffer});
    fireEvent.change(screen.getByLabelText("v1.3 JSONL文件"),{target:{files:[file]}});
    await waitFor(()=>expect(screen.getByRole("button",{name:"校验并接入原始JSONL"})).toBeEnabled());
    await userEvent.click(screen.getByRole("button",{name:"校验并接入原始JSONL"}));
    await waitFor(()=>expect(calls).toHaveLength(1));
    expect(calls[0]).toEqual({path:"/api/s4/v2/imports/upload",body:{envelope:{contract_version:"openkb.s3-s4.v2",mode:"demo",batch_id:"B1",source_revision:"r1"},file_base64:"77u/e30NCg=="}});
    expect(await screen.findByText("a".repeat(64))).toBeInTheDocument();
  });
  it("422响应保留逐条报告并不显示成功接入",async()=>{
    server({error_code:"IMPORT_VALIDATION_FAILED",message:"候选校验失败",validation_report:{valid:false,total_rows:2,error_count:1,errors:[{row:2,unit_id:"u2",error_code:"DIFFICULTY_INVALID",message:"难度须存英文"}]}},422);
    mount();fireEvent.change(screen.getByLabelText("v1.3 候选包 JSON"),{target:{value:'{"units":[]}'}});
    await userEvent.click(screen.getByRole("button",{name:"校验并接入候选"}));
    expect(await screen.findByText("DIFFICULTY_INVALID")).toBeInTheDocument();
    expect(screen.queryByText("候选已接入")).not.toBeInTheDocument();
  });
});
