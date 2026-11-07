import {useState} from "react";
import {useQuery,useQueryClient} from "@tanstack/react-query";
import {ErrorNotice,Panel,QueryState} from "../components/Common";
import type {User} from "../types";
import {apiV2,listV2} from "./api";

export interface CurrentProfileRevision {
 id:string;dataset:string;version:string;manual_version:string;
 state:"DRAFT"|"REVIEW"|"APPROVED"|"RETIRED";revision:number;canonical_hash:string;
 creator_id:string;approver_id?:string|null;snapshot:Record<string,unknown>;
}
const datasets=["QA-D1","QA-D2","QA-D3","QA-D4","QA-D4C","QA-D5","QA-D6","QA-D7","SEC-D1","SEC-D2","SEC-D3","SEC-D4","SEC-D5"];
const stateNames={DRAFT:"草稿",REVIEW:"待独立评审",APPROVED:"本地配置已批准",RETIRED:"已停止新分发"};

export function ProfileLifecycle({user}:{user:User}) {
 const canDraft=user.roles.includes("lead"),canApprove=user.roles.includes("auditor");
 const client=useQueryClient();
 const query=useQuery({queryKey:["v13","profile-revisions"],queryFn:({signal})=>listV2<CurrentProfileRevision>("/profile-revisions",signal)});
 const [editing,setEditing]=useState<CurrentProfileRevision|null>(null);
 const [dataset,setDataset]=useState("QA-D1"),[version,setVersion]=useState(""),[manual,setManual]=useState("");
 const [instructions,setInstructions]=useState(""),[manualText,setManualText]=useState(""),[reason,setReason]=useState("");
 const [actionReason,setActionReason]=useState(""),[signature,setSignature]=useState(""),[basis,setBasis]=useState("");
 const [pending,setPending]=useState(false),[error,setError]=useState<Error|null>(null),[notice,setNotice]=useState("");
 function edit(row:CurrentProfileRevision) {
  setEditing(row);setDataset(row.dataset);setVersion(row.version);setManual(row.manual_version);
  setInstructions(String(row.snapshot.instructions??""));setManualText(String(row.snapshot.manual_text??""));setReason("");setError(null);setNotice("");
 }
 function clear(){setEditing(null);setVersion("");setManual("");setInstructions("");setManualText("");setReason("");}
 async function save() {
  setPending(true);setError(null);setNotice("");
  try {
   const reference=editing?.snapshot??await apiV2<Record<string,unknown>>(`/profile-revisions/template?dataset=${encodeURIComponent(dataset)}`);
   const snapshot={...reference,version:version.trim(),manual_version:manual.trim(),
    instructions:instructions.trim()||reference.instructions,manual_text:manualText.trim()||reference.manual_text};
   await apiV2(editing?`/profile-revisions/${editing.id}`:"/profile-revisions",{method:editing?"PATCH":"POST",body:{dataset,version:version.trim(),manual_version:manual.trim(),snapshot,reason:reason.trim(),...(editing?{expected_revision:editing.revision}:{})}});
   clear();setNotice("配置草稿已保存，尚未批准或用于新分发。");await client.invalidateQueries({queryKey:["v13"]});
  }catch(e){setError(e instanceof Error?e:new Error("配置保存失败"));}finally{setPending(false);}
 }
 async function transition(row:CurrentProfileRevision,action:"submit"|"approve"|"retire") {
  setPending(true);setError(null);setNotice("");
  try {
   await apiV2(`/profile-revisions/${row.id}/${action}`,{method:"POST",body:{expected_revision:row.revision,reason:actionReason.trim(),...(action==="approve"?{signature:signature.trim(),evidence:{basis:basis.trim()}}:{})}});
   setNotice(action==="approve"?"本地配置已批准。外部协议、专业词表和正式交接仍按实际证据确认。":action==="retire"?"已停用于新分发，历史冻结快照保留。":"已提交独立评审，尚未批准。");
   await client.invalidateQueries({queryKey:["v13"]});
  }catch(e){setError(e instanceof Error?e:new Error("配置状态更新失败"));}finally{setPending(false);}
 }
 return <Panel title="新版配置评审与冻结">
  <p className="notice info">草稿经独立评审批准后，可在新建计划时选择。量表、阶段规则和专业词表受限；本地批准不代表外部验收通过。停止新分发后，原批次的快照和记录继续保留。</p>
  <QueryState pending={query.isPending} error={query.error}>
   {query.data?.items.length?<div className="table-scroll"><table><thead><tr><th>数据集 / 版本</th><th>手册与状态</th><th>冻结摘要</th><th>操作</th></tr></thead><tbody>{query.data.items.map(row=><tr key={row.id}>
    <td>{row.dataset}<p>{row.version}</p></td><td>{row.manual_version}<p>{stateNames[row.state]}</p></td><td className="tiny mono">{row.canonical_hash}<p>记录版本 {row.revision}</p></td>
    <td><details><summary>查看配置内容 · {row.dataset} · {row.version}</summary><section aria-label={`配置只读详情 ${row.dataset} ${row.version}`}>
      <p>记录版本 {row.revision} · 手册 {row.manual_version}</p><p className="tiny mono">{row.canonical_hash}</p>
      <h3>操作说明</h3><pre className="v13-safe-material">{String(row.snapshot.instructions??"")}</pre>
      <h3>核实指南正文</h3><pre className="v13-safe-material">{String(row.snapshot.manual_text??"")}</pre>
      <h3>完整配置快照（只读）</h3><pre aria-label="完整配置快照" className="v13-safe-material">{JSON.stringify(row.snapshot,null,2)}</pre>
     </section></details>{canDraft&&row.state==="DRAFT"&&<><button className="button" disabled={pending} onClick={()=>edit(row)}>编辑配置草稿</button><button className="button" disabled={pending||!actionReason.trim()} onClick={()=>void transition(row,"submit")}>提交配置评审</button></>}
     {canApprove&&row.state==="REVIEW"&&<button className="button" disabled={pending||row.creator_id===user.id||!actionReason.trim()||!signature.trim()||!basis.trim()} onClick={()=>void transition(row,"approve")}>独立批准</button>}
     {(canDraft||canApprove)&&row.state==="APPROVED"&&<button className="button" disabled={pending||!actionReason.trim()} onClick={()=>void transition(row,"retire")}>停用于新分发</button>}
    </td></tr>)}</tbody></table></div>:<p>尚无新版配置草稿。现有本地演示基线保留原语义。</p>}
  </QueryState>
  <div className="form-stack"><label>审批或停用理由<textarea aria-label="审批或停用理由" value={actionReason} onChange={e=>setActionReason(e.target.value)}/></label>
   {canApprove&&<><label>批准署名<input aria-label="批准署名" value={signature} onChange={e=>setSignature(e.target.value)}/></label><label>审批依据<textarea aria-label="审批依据" value={basis} onChange={e=>setBasis(e.target.value)}/></label><p className="muted">填写实际评审依据和署名；服务端核对人员身份与独立性。</p></>}
  </div>
  {canDraft&&<form className="form-stack" onSubmit={e=>{e.preventDefault();void save();}}>
   <h3>{editing?"编辑已有草稿":"创建新版配置草稿"}</h3><div className="v13-plan-grid">
    <label>配置数据集<select aria-label="配置数据集" disabled={!!editing||pending} value={dataset} onChange={e=>setDataset(e.target.value)}>{datasets.map(d=><option key={d}>{d}</option>)}</select></label>
    <label>配置版本<input aria-label="配置版本" disabled={!!editing||pending} value={version} onChange={e=>setVersion(e.target.value)} required/></label>
    <label>手册版本<input aria-label="手册版本" disabled={pending} value={manual} onChange={e=>setManual(e.target.value)} required/></label>
   </div><label>操作说明<textarea aria-label="操作说明" disabled={pending} value={instructions} onChange={e=>setInstructions(e.target.value)}/></label><label>核实指南正文<textarea aria-label="核实指南正文" rows={5} disabled={pending} value={manualText} onChange={e=>setManualText(e.target.value)}/></label>
   <label>配置变更理由<textarea aria-label="配置变更理由" disabled={pending} value={reason} onChange={e=>setReason(e.target.value)} required/></label>
   <div className="form-actions"><button className="button primary" disabled={pending||!version.trim()||!manual.trim()||!reason.trim()} type="submit">{editing?"保存配置草稿":"创建配置草稿"}</button>{editing&&<button className="button" type="button" disabled={pending} onClick={clear}>取消编辑</button>}</div>
  </form>}
  {notice&&<p role="status" className="notice info">{notice}</p>}<ErrorNotice error={error}/>
 </Panel>;
}
