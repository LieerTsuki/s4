import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useList } from "../hooks";
import type { User } from "../types";
import { ErrorNotice, PageHeader, Panel, QueryState, RefreshButton, Empty } from "../components/Common";
import { safeText } from "../format";
import { apiV2, listV2 } from "./api";
import { BatchMaintenance } from "./Governance";
import { V13Ingress } from "./Ingress";
import type { V13Batch, V13Import, V13Report, V13Task, WorkflowKind } from "./types";

const datasets=["QA-D1","QA-D2","QA-D3","QA-D4","QA-D4C","QA-D5","QA-D6","QA-D7","SEC-D1","SEC-D2","SEC-D3","SEC-D4","SEC-D5"];
const kinds={VERIFICATION:"全量核实",OBSERVATION:"双人观测"};

export function V13Profiles() {
  const query=useQuery({queryKey:["v13","profiles"],queryFn:({signal})=>apiV2<{dataset:string;quota:number;kind:string;version:string;manual_version:string;formal_enabled:boolean;blocked_reasons:string[]}[]>("/profiles",{signal})});
  return <><PageHeader title="当前任务配置" description="13类有限表单与冻结版本；本地基线不等同正式协议、专业词表或审批已经对齐。"/><Panel title="v1.3 配置与待确认项"><QueryState pending={query.isPending} error={query.error}><div className="table-scroll"><table><thead><tr><th>数据集</th><th>配额 / 单位</th><th>版本</th><th>正式状态与限制</th></tr></thead><tbody>{query.data?.map(profile=><tr key={profile.dataset}><td>{profile.dataset}</td><td>{profile.quota} {profile.dataset==="QA-D6"?"片段":profile.dataset==="SEC-D3"?"组":profile.dataset==="SEC-D4"?"对":"单元"}</td><td>{profile.version}<p>{profile.manual_version}</p></td><td>{profile.formal_enabled?"以实际批准记录为准":"待外部规则确认"}{profile.blocked_reasons.map(reason=><p key={reason}>{reason}</p>)}</td></tr>)}</tbody></table></div></QueryState></Panel></>;
}

export function ProgressSummary({report}:{report:V13Report}) {
  const total=Number(report.N??0),verified=Number(report.verified_count??report.verification_completed??0);
  return <div className="v13-progress"><div><strong>全量 N = {total}</strong><p>已核实 {verified} 条</p><p>待核实 {Math.max(0,total-verified)} 条</p></div><div><strong>观测单元 n = {Number(report.n??0)}</strong><p>有效配对 {Number(report.observation_completed??report.observation_pairs??0)} 对</p><p>观测记录不替代全量核实</p></div><div><strong>{report.readiness??report.state??"按服务端状态对账"}</strong>{(report.blockers??report.blocked_reasons)?.map(reason=><p key={reason}>{reason}</p>)}</div></div>;
}

export function V13Overview({user}:{user:User}) {
  const manager=user.roles.some(r=>["lead","auditor"].includes(r));
  const query=useQuery({queryKey:["v13",manager?"imports":"tasks"],queryFn:({signal})=>listV2<V13Import|V13Task>(manager?"/imports":"/me/tasks",signal)});
  return <><PageHeader title="人工核实与质量观测" eyebrow="S4 · V1.3" description="S3有效数据全部逐条人工核实；另按数据集与难度抽样，安排两名真实人员独立复核。" action={<RefreshButton onClick={()=>void query.refetch()}/>}/><Panel title="当前流程"><div className="v13-workflow"><span>S3 有效数据</span><span>全量 N 条人工核实</span><span>抽样 n 条双人观测</span><span>S5 独立七层验收</span></div><p className="notice warm">κ用于质量观测：低于0.6整批退S2；灰区及未定义统计的正式出口等待适用规则确认。外部协议、D6完整词表和主仓映射的状态以实际证据为准。</p></Panel><Panel title={manager?"当前接入批次":"本人任务"}><QueryState pending={query.isPending} error={query.error}><p>当前可见 {query.data?.total??0} 条记录。</p><Link className="button primary" to={manager?"/v13/imports":"/v13/tasks"}>{manager?"进入候选接入与计划":"进入我的核实任务"}</Link></QueryState></Panel><Panel title="历史基线"><p>0003 / REVIEW v2 记录保留原始字段与封存。其观测记录不会自动变成新版全量核实记录。</p><Link to="/legacy">查看旧版工作概览</Link></Panel></>;
}

export function V13Imports({canWrite}:{canWrite:boolean}) {
  const client=useQueryClient();
  const query=useQuery({queryKey:["v13","imports"],queryFn:({signal})=>listV2<V13Import>("/imports",signal)});
  return <><PageHeader title="v1.3 候选接入" description="接收 openkb.s3-s4.v2。保留S3原始分母、失败归档与递补血缘；每个当前有效单元均须有PASS证据。"/>{canWrite&&<V13Ingress onImported={async()=>{await client.invalidateQueries({queryKey:["v13"]});}}/>}<Panel title="接入记录"><QueryState pending={query.isPending} error={query.error}>{query.data?.items.length?<div className="table-scroll"><table><thead><tr><th>生产批次</th><th>版本 / 模式</th><th>全量单元</th><th>状态</th><th>操作</th></tr></thead><tbody>{query.data.items.map(item=><tr key={item.id}><td>{item.batch_id}</td><td>{item.source_revision} · {item.mode}</td><td>{item.unit_count}</td><td>{item.status}<p>{item.blocked_reasons?.join("；")}</p></td><td><Link to={`/v13/imports/${item.id}`}>核对全量账 / 创建计划</Link></td></tr>)}</tbody></table></div>:<Empty title="尚无新版候选"/>}</QueryState></Panel></>;
}

export function V13ImportDetail({canWrite}:{canWrite:boolean}) {
  const {id}=useParams();const client=useQueryClient();const navigate=useNavigate();
  const detail=useQuery({queryKey:["v13","import",id],queryFn:({signal})=>apiV2<V13Import&{units?:{unit_id:string;dataset:string;difficulty:string}[]}>(`/imports/${id}`,{signal})});
  const report=useQuery({queryKey:["v13","report",id],queryFn:({signal})=>apiV2<V13Report>(`/imports/${id}/report`,{signal})});
  const users=useList<User>("/users",canWrite);
  const [kind,setKind]=useState<WorkflowKind>("VERIFICATION"),[dataset,setDataset]=useState("QA-D1"),[assignees,setAssignees]=useState<string[]>([]),[a,setA]=useState(""),[b,setB]=useState(""),[seed,setSeed]=useState(20261030),[error,setError]=useState<Error|null>(null),[pending,setPending]=useState(false);
  async function create() {
    setError(null);setPending(true);try{const result=await apiV2<V13Batch>(kind==="VERIFICATION"?"/verification-batches":"/observation-batches",{method:"POST",body:{import_id:id,dataset,manual_version:"manual-v1.3",profile_version:"s4-v1.3",...(kind==="VERIFICATION"?{assignee_ids:assignees}:{annotator_a:a,annotator_b:b,seed})}});await client.invalidateQueries({queryKey:["v13"]});navigate(`/v13/batches/${result.id}`);}catch(e){setError(e instanceof Error?e:new Error("建队失败"));}finally{setPending(false);}
  }
  const eligible=(users.data?.items??[]).filter(u=>u.active&&u.roles.includes("annotator")&&!u.roles.includes("admin"));
  const available=Array.from(new Set(detail.data?.units?.map(unit=>unit.dataset)??detail.data?.datasets??datasets));
  return <><PageHeader title="全量与观测对账" description="全量N与观测n分账；每条最终单元必须对应当前有效核实结论，草稿和独立作答不计完成。"/><QueryState pending={detail.isPending} error={detail.error}><Panel title={detail.data?.batch_id}><ProgressSummary report={report.data??{}}/><ErrorNotice error={report.error}/></Panel></QueryState>{canWrite&&<Panel title="创建核实 / 观测计划"><div className="v13-plan-grid"><label>任务类型<select aria-label="计划类型" value={kind} onChange={e=>setKind(e.target.value as WorkflowKind)}><option value="VERIFICATION">全量核实：每条分配一人</option><option value="OBSERVATION">双人观测：固定A/B分层抽样</option></select></label><label>数据集<select aria-label="计划数据集" value={dataset} onChange={e=>setDataset(e.target.value)}>{available.map(d=><option key={d}>{d}</option>)}</select></label></div>{kind==="VERIFICATION"?<fieldset><legend>全量核实人员（按单元分担）</legend>{eligible.map(u=><label key={u.id}><input type="checkbox" checked={assignees.includes(u.id)} onChange={e=>setAssignees(e.target.checked?[...assignees,u.id]:assignees.filter(id=>id!==u.id))}/>{u.display_name} · {u.person_id}</label>)}</fieldset>:<div className="v13-plan-grid">{([["A",a,setA],["B",b,setB]] as const).map(([seat,value,set])=><label key={seat}>观测员{seat}<select aria-label={`观测员${seat}`} value={value} onChange={e=>set(e.target.value)}><option value="">选择未暴露人员</option>{eligible.map(u=><option key={u.id} value={u.id}>{u.display_name} · {u.person_id}</option>)}</select></label>)}<label>冻结随机种子<input aria-label="观测随机种子" type="number" value={seed} onChange={e=>setSeed(Number(e.target.value))}/></label></div>}<p className="muted">每数据集抽max(8,ceil(10%×N))，不足8时全抽并登记缺口。服务端检查资格、真实人员、暴露与版本。</p><ErrorNotice error={users.error??error}/><button className="button primary" disabled={pending||(kind==="VERIFICATION"?!assignees.length:!a||!b||a===b)} onClick={()=>void create()}>创建{kinds[kind]}计划</button></Panel>}<Link to="/v13/batches">查看全部计划</Link></>;
}

export function V13Batches() {
  const verification=useQuery({queryKey:["v13","batches","VERIFICATION"],queryFn:({signal})=>listV2<V13Batch>("/verification-batches",signal)});
  const observation=useQuery({queryKey:["v13","batches","OBSERVATION"],queryFn:({signal})=>listV2<V13Batch>("/observation-batches",signal)});
  return <><PageHeader title="核实与观测计划" description="全量核实按单元闭环，观测按固定人员对、冻结版本和样本范围复算。"/>{[verification,observation].map((query,index)=><Panel key={index} title={index?"双人观测计划":"全量核实计划"}><QueryState pending={query.isPending} error={query.error}>{query.data?.items.length?<div className="table-scroll"><table><thead><tr><th>数据集</th><th>范围</th><th>独立 / 比对封存</th><th>状态</th><th>操作</th></tr></thead><tbody>{query.data.items.map(item=><tr key={item.id}><td>{item.dataset}</td><td>{item.selected_ids?.length??item.sample_count} 单元</td><td>{item.blind_submitted} / {item.review_submitted}</td><td>{item.state}</td><td><Link to={`/v13/batches/${item.id}`}>查看计划</Link></td></tr>)}</tbody></table></div>:<Empty/>}</QueryState></Panel>)}</>;
}

export function V13BatchDetail({canWrite}:{canWrite:boolean}) {
  const {id}=useParams();const client=useQueryClient();
  const query=useQuery({queryKey:["v13","batch",id],queryFn:({signal})=>apiV2<V13Batch>(`/batches/${id}`,{signal})});
  const [error,setError]=useState<Error|null>(null),[pending,setPending]=useState(false),[kind,setKind]=useState("CALIBRATION"),[reason,setReason]=useState(""),[evidence,setEvidence]=useState("{}");
  async function command(path:string,body:unknown={}) {setError(null);setPending(true);try{await apiV2(path,{method:"POST",body});await client.invalidateQueries({queryKey:["v13"]});}catch(e){setError(e instanceof Error?e:new Error("操作失败"));}finally{setPending(false);}}
  const batch=query.data;
  return <><PageHeader title="计划进度与质量动作" description="原始独立记录、核实记录和观测范围保持冻结。关闭问题不等于失败批通过。"/><QueryState pending={query.isPending} error={query.error}>{batch&&<><Panel title={`${batch.dataset} · ${kinds[batch.workflow_kind]}`}><dl className="v13-key-values"><dt>状态</dt><dd>{batch.state}</dd><dt>冻结单元</dt><dd>{batch.selected_ids.length}</dd><dt>独立封存</dt><dd>{batch.blind_submitted}</dd><dt>比对封存</dt><dd>{batch.review_submitted}</dd><dt>全量核实完成</dt><dd>{batch.verification_completed??0}</dd></dl>{batch.blocked_reasons?.map(reason=><p className="notice warm" key={reason}>{reason}</p>)}{canWrite&&batch.workflow_kind==="OBSERVATION"&&<div className="form-actions"><button className="button" disabled={pending} onClick={()=>void command(`/observation-batches/${id}/release-review`)}>核对全批独立封存并开放复核</button><button className="button" disabled={pending} onClick={()=>void command(`/observation-batches/${id}/observe`)}>复算原始观测</button></div>}{batch.quality&&<div className="notice info"><p>原κ：{batch.quality.kappa===null?"未定义":batch.quality.kappa}</p><pre>{safeText(batch.quality)}</pre></div>}</Panel>{canWrite&&<Panel title="登记质量动作"><label>动作<select value={kind} onChange={e=>setKind(e.target.value)}><option value="CALIBRATION">口径校准会</option><option value="EXPAND">扩样记录</option><option value="RETURN_TO_S2">整批退S2</option><option value="S2_ACK">登记S2真实接收</option><option value="DISAGREEMENT_REVIEW">内容分歧独立核对</option></select></label><label>动作理由<textarea value={reason} onChange={e=>setReason(e.target.value)}/></label>{kind==="DISAGREEMENT_REVIEW"&&<p className="notice info">证据需绑定unit_index_id、content_revision和resolution（KEEP_SOURCE或REVISION_REQUIRED）。保留原始观测，不用高κ消除内容问题。</p>}<label>受控证据 JSON<textarea value={evidence} onChange={e=>setEvidence(e.target.value)} rows={4}/></label><button className="button" disabled={pending||!reason.trim()} onClick={()=>{try{void command("/quality-actions",{batch_id:id,kind,reason,evidence:JSON.parse(evidence) as unknown});}catch(e){setError(e instanceof Error?e:new Error("证据JSON无效"));}}}>登记实际质量动作</button></Panel>}{canWrite&&<BatchMaintenance batch={batch}/>}<Link to={`/v13/imports/${batch.import_id}`}>返回全量与观测总账</Link></>}</QueryState><ErrorNotice error={error}/></>;
}

export function V13Tasks() {
  const [filter,setFilter]=useState<WorkflowKind|"ALL">("ALL");
  const query=useQuery({queryKey:["v13","tasks",filter],queryFn:({signal})=>listV2<V13Task>(`/me/tasks${filter==="ALL"?"":`?workflow_kind=${filter}`}`,signal)});
  return <><PageHeader title="我的核实任务" description="仅展示本人任务。主核实完成本人独立封存后按单元释放；观测等待固定A/B全批封存后统一释放。" action={<RefreshButton onClick={()=>void query.refetch()}/>}/><div className="filter-tabs">{(["ALL","VERIFICATION","OBSERVATION"] as const).map(kind=><button key={kind} className={filter===kind?"active":""} onClick={()=>setFilter(kind)}>{kind==="ALL"?"全部任务":kinds[kind]}</button>)}</div><Panel><QueryState pending={query.isPending} error={query.error}>{query.data?.items.length?<div className="table-scroll"><table><thead><tr><th>评测单元</th><th>任务类型</th><th>阶段</th><th>状态</th><th>操作</th></tr></thead><tbody>{query.data.items.map(task=><tr key={task.id}><td>{task.unit_id}<p>{task.dataset}</p></td><td>{kinds[task.workflow_kind]}</td><td>{task.phase==="BLIND"?"独立判断":"草案比对"}</td><td>{task.status}</td><td><Link to={`/v13/tasks/${task.id}`}>{task.status==="SEALED"?"查看本人封存":"进入作业"}</Link></td></tr>)}</tbody></table></div>:<Empty title="当前没有本人任务"/>}</QueryState></Panel></>;
}
