import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { Job } from "../types";
import { Empty, ErrorNotice, PageHeader, Panel, QueryState } from "../components/Common";
import { safeText } from "../format";
import { apiV2, listV2 } from "./api";
import type { V13Import } from "./types";

interface FileRecord {sha256: string; rows?: number; line_count?: number}
interface V13Handoff {
  id: string; import_id: string; mode: string; status: string; external_status: string;
  snapshot_hash?: string; external_alignment?: string;
  blocked_reasons?: string[];
  manifest?: {files?: Record<string,FileRecord>; [key:string]:unknown} | null;
}

function HandoffFiles({handoff,canWrite}:{handoff:V13Handoff;canWrite:boolean}) {
  const client=useQueryClient();
  const detail=useQuery({queryKey:["v13","handoff",handoff.id],queryFn:({signal})=>apiV2<V13Handoff>(`/handoffs/${handoff.id}`,{signal}),enabled:!handoff.manifest});
  const [destination,setDestination]=useState(""),[evidence,setEvidence]=useState(""),[digest,setDigest]=useState("");
  const [error,setError]=useState<Error|null>(null),[pending,setPending]=useState(false);
  const [idempotencyKey]=useState(()=>crypto.randomUUID());
  const record=detail.data??handoff;
  const files=record.manifest?.files??{};
  async function sent() {
    setPending(true);setError(null);
    try {await apiV2(`/handoffs/${record.id}/sent`,{method:"POST",body:{idempotency_key:idempotencyKey,snapshot_hash:record.snapshot_hash,destination_ref:destination,evidence_ref:evidence,evidence_sha256:digest}});await client.invalidateQueries({queryKey:["v13","handoffs"]});}catch(e){setError(e instanceof Error?e:new Error("发送证据登记失败"));}finally{setPending(false);}
  }
  return <Panel title={`${record.mode} · ${record.status}`}><p className="mono tiny">交接 {record.id} · 来源 {record.import_id}</p><p>接收方状态：{record.external_status??record.external_alignment??"尚无真实回执"}</p>{record.blocked_reasons?.map(reason=><p key={reason} className="notice warm">{reason}</p>)}<ErrorNotice error={detail.error}/>{Object.keys(files).length?<div className="table-scroll"><table><thead><tr><th>已封存文件</th><th>行数</th><th>SHA256</th></tr></thead><tbody>{Object.entries(files).map(([name,file])=><tr key={name}><td><a href={`/api/s4/v2/handoffs/${encodeURIComponent(record.id)}/files/${encodeURIComponent(name)}`} download>{name}</a></td><td>{file.rows??file.line_count??"—"}</td><td className="tiny mono">{file.sha256}</td></tr>)}</tbody></table></div>:<p className="muted">文件尚未发布；后台任务完成并校验摘要后才出现下载入口。</p>}{record.manifest&&<p><a href={`/api/s4/v2/handoffs/${encodeURIComponent(record.id)}/files/s4_handoff_manifest.json`} download>下载交接清单</a></p>}<details><summary>查看交接清单与限制</summary><pre className="v13-safe-material">{safeText(record.manifest)}</pre></details>{canWrite&&record.snapshot_hash&&<details><summary>登记已经发生的发送证据</summary><p>请在实际发送后填写受控接收方与证据引用。本操作仅登记证据，S5接收仍需真实回执。</p><label>接收方引用<input aria-label="接收方引用" value={destination} placeholder="receiver:受控编号" onChange={e=>setDestination(e.target.value)}/></label><label>发送证据引用<input aria-label="发送证据引用" value={evidence} placeholder="evidence:受控编号" onChange={e=>setEvidence(e.target.value)}/></label><label>发送证据SHA256<input aria-label="发送证据SHA256" value={digest} onChange={e=>setDigest(e.target.value)}/></label><button className="button" disabled={pending||!destination.trim()||!evidence.trim()||! /^[0-9a-f]{64}$/.test(digest)} onClick={()=>void sent()}>登记实际发送证据</button><ErrorNotice error={error}/></details>}</Panel>;
}

export function V13Handoffs({canWrite}:{canWrite:boolean}) {
  const client=useQueryClient();
  const handoffs=useQuery({queryKey:["v13","handoffs"],queryFn:({signal})=>listV2<V13Handoff>("/handoffs",signal)});
  const imports=useQuery({queryKey:["v13","imports"],queryFn:({signal})=>listV2<V13Import>("/imports",signal),enabled:canWrite});
  const [importId,setImportId]=useState("");const [jobId,setJobId]=useState("");const [pending,setPending]=useState(false);const [error,setError]=useState<Error|null>(null);
  const job=useQuery({queryKey:["v13","job",jobId],queryFn:({signal})=>apiV2<Job>(`/jobs/${jobId}`,{signal}),enabled:!!jobId,refetchInterval:query=>query.state.data&&["SUCCEEDED","DONE","FAILED"].includes(query.state.data.state)?false:2000});
  useEffect(()=>{if(job.data&&["SUCCEEDED","DONE"].includes(job.data.state))void client.invalidateQueries({queryKey:["v13","handoffs"]});},[client,job.data]);
  async function create() {
    setPending(true);setError(null);
    try{const result=await apiV2<{job_id:string}>("/handoffs",{method:"POST",body:{import_id:importId}});setJobId(result.job_id);await client.invalidateQueries({queryKey:["v13","handoffs"]});}catch(e){setError(e instanceof Error?e:new Error("交接包生成失败"));}finally{setPending(false);}
  }
  return <><PageHeader title="新版过程交接包" description="N条核实记录与n条IAA分别保存；下载不代表已发送或S5已接收。"/><Panel title="交接边界"><p className="notice warm">正式交接需有真实S3/S5协议、适用规则确认及完整核实/观测证据。当前未对齐项仍会阻塞；演示包明确标记demo，不签正式凭据。</p><p>过程包不替代S5最终六文件，也不执行HF发布。</p></Panel>{canWrite&&<Panel title="生成受控快照"><label>来源批次<select aria-label="交接来源批次" value={importId} onChange={e=>setImportId(e.target.value)}><option value="">请选择生产批次</option>{imports.data?.items.map(item=><option key={item.id} value={item.id}>{item.batch_id} · {item.mode}</option>)}</select></label><button className="button primary" disabled={pending||!importId} onClick={()=>void create()}>生成新版过程交接包</button><ErrorNotice error={imports.error??error}/>{jobId&&<div className="notice info"><p>后台任务：{job.data?.state??"等待查询"}</p><p className="mono tiny">{jobId}</p>{job.data?.error_message&&<p>{job.data.error_message}</p>}<ErrorNotice error={job.error}/></div>}</Panel>}<QueryState pending={handoffs.isPending} error={handoffs.error}>{handoffs.data?.items.length?handoffs.data.items.map(item=><HandoffFiles key={item.id} handoff={item} canWrite={canWrite}/>):<Panel><Empty title="尚无新版交接快照"/></Panel>}</QueryState></>;
}
