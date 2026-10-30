import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ErrorNotice, PageHeader, Panel, QueryState, RefreshButton } from "../components/Common";
import { SourceDocument } from "../components/SourceDocument";
import { safeText } from "../format";
import { SpecializedObservations } from "./SpecializedObservations";
import { apiV2 } from "./api";
import { ReviewV3Form } from "./ReviewV3Form";
import { ExtractionEditor } from "./ExtractionEditor";
import { TaskIssue } from "./Governance";
import type { ReviewV3, V13Task, Verdict } from "./types";

function AssociatedMaterials({material}:{material:V13Task["material"]}) {
  const names:Record<string,string>={key_facts:"关键事实与锚点",reasoning_chain:"多跳链",domain:"业务域",domains:"跨域范围",source_case_ids:"源题标识",resolved_sources:"冻结源题",evaluation_k:"评测K",same_intent_confirmation:"同意图人工确认",source_composition:"源题构成",pair_id:"成对单元组",paired_unit_id:"对应单元"};
  const items=Object.entries(material??{}).filter(([key,value])=>key in names&&value!==null&&value!==undefined);
  if(!items.length)return null;
  return <details><summary>草案关联材料（核实阶段）</summary>{items.map(([key,value])=><div key={key}><strong>{names[key]}</strong><pre className="v13-safe-material">{safeText(value)}</pre></div>)}</details>;
}

function IndependentForm({task,onSave,onSubmit,disabled}:{task:V13Task;onSave:(data:Record<string,unknown>)=>Promise<void>;onSubmit:(data:Record<string,unknown>)=>Promise<void>;disabled:boolean}) {
  const initial=task.own_submission??task.draft?.payload??{};
  const [answer,setAnswer]=useState(typeof initial.answer==="string"?initial.answer:"");
  const [reason,setReason]=useState(typeof initial.reason==="string"?initial.reason:"");
  const [extraction,setExtraction]=useState<ReviewV3["extraction"]>(typeof initial.extraction==="object"&&initial.extraction!==null?initial.extraction as ReviewV3["extraction"]:{gold_entities:[],gold_relations:[]});
  const [pending,setPending]=useState(false),[error,setError]=useState<Error|null>(null),[saved,setSaved]=useState(false);
  async function perform(seal:boolean) {
    setError(null);setSaved(false);if(seal&&(!answer.trim()||!reason.trim())){setError(new Error("请填写独立判断及原文依据。"));return;}
    setPending(true);try{await(seal?onSubmit:onSave)({answer,reason,...(task.dataset==="QA-D6"?{extraction}:{})});if(!seal)setSaved(true);}catch(e){setError(e instanceof Error?e:new Error("提交失败"));}finally{setPending(false);}
  }
  return <form className="form-stack" onSubmit={e=>{e.preventDefault();void perform(true);}}><h2>独立判断并封存</h2><p className="notice info">{task.workflow_kind==="VERIFICATION"?"主核实：本人本单元独立判断封存后，按同源族屏障释放草案比对。":"观测：固定A/B完成本统计批全部独立判断后，由运营统一开放草案复核。"}</p>{task.dataset==="QA-D6"&&<ExtractionEditor text={task.material?.text??task.material?.chunk??""} vocabulary={task.vocabulary} value={extraction??{gold_entities:[],gold_relations:[]}} onChange={setExtraction} disabled={disabled}/>}<label>独立答案 / 专项判断<textarea aria-label="新版独立判断" rows={8} value={answer} disabled={disabled} onChange={e=>setAnswer(e.target.value)}/></label><label>所据原文与理由<textarea aria-label="新版独立理由" rows={5} value={reason} disabled={disabled} onChange={e=>setReason(e.target.value)}/></label><ErrorNotice error={error}/>{saved&&<p role="status">独立草稿已保存，尚未封存。</p>}<div className="form-actions"><button className="button" type="button" disabled={disabled||pending} onClick={()=>void perform(false)}>保存独立草稿</button><button className="button primary" type="submit" disabled={disabled||pending}>提交并封存独立判断</button></div></form>;
}

function SpecializedFormV3({task,onSave,onSubmit,disabled}:{task:V13Task;onSave:(data:ReviewV3)=>Promise<void>;onSubmit:(data:ReviewV3)=>Promise<void>;disabled:boolean}) {
  const initial=(task.own_submission??task.draft?.payload??{}) as Partial<ReviewV3>;
  const [data,setData]=useState<ReviewV3>({review_version:"openkb.s4-review.v3",workflow_kind:task.workflow_kind,verdict:initial.verdict??(task.dataset==="QA-D6"&&!task.vocabulary?"NEEDS_REVISION":"VERIFIED"),point_labels:{},point_reasons:{},point_evidence:{},point_search_scope:{},evidence_assessments:{},absence_reason:null,expected_refusal_reason:"",reason:initial.reason??"",specialized_review:initial.specialized_review??{},...(task.dataset==="QA-D6"?{extraction:initial.extraction??(task.own_blind?.extraction as ReviewV3["extraction"]|undefined)??{gold_entities:[],gold_relations:[]}}:{})});
  const [error,setError]=useState<Error|null>(null),[pending,setPending]=useState(false),[saved,setSaved]=useState(false);
  async function perform(seal:boolean) {
    setError(null);setSaved(false);
    if(seal&&(!data.reason.trim()||(task.dataset==="QA-D6"&&!task.vocabulary&&data.verdict==="VERIFIED"))){setError(new Error("请记录核实理由；D6完整词表未登记时不能提交核实通过。"));return;}
    setPending(true);try{await(seal?onSubmit:onSave)(data);if(!seal)setSaved(true);}catch(e){setError(e instanceof Error?e:new Error("提交失败"));}finally{setPending(false);}
  }
  return <form className="form-stack" onSubmit={e=>{e.preventDefault();void perform(true);}}>
    <h2>{task.dataset==="QA-D6"?"实体关系核实":"安全专项核实"}</h2>
    <p className="notice info">材料按文本展示。核实操作不执行注入、投毒、查询或回滚。</p><details><summary>本人封存的独立专项判断</summary><pre className="v13-safe-material">{safeText(task.own_blind)}</pre></details>{task.dataset==="QA-D6"&&<details><summary>冻结模型预标（仅核实阶段）</summary><pre className="v13-safe-material">{safeText({gold_entities:task.gold?.gold_entities??[],gold_relations:task.gold?.gold_relations??[]})}</pre></details>}
    {task.dataset==="QA-D6"&&<ExtractionEditor text={task.material?.text??task.material?.chunk??""} vocabulary={task.vocabulary} disabled={disabled} value={data.extraction??{gold_entities:[],gold_relations:[]}} onChange={extraction=>setData({...data,extraction})}/>}
    <SpecializedObservations dataset={task.dataset} contexts={task.material?.contexts??[]} value={data.specialized_review} disabled={disabled} onChange={specialized_review=>setData({...data,specialized_review})}/>
    <label>本条核实结论<select aria-label="专项核实结论" value={data.verdict} disabled={disabled} onChange={e=>setData({...data,verdict:e.target.value as Verdict})}><option value="VERIFIED">核实通过</option><option value="NEEDS_REVISION">需要修订 / 材料不足</option><option value="RETURNED">退回</option></select></label><label>核实说明<textarea aria-label="专项核实说明" value={data.reason} disabled={disabled} onChange={e=>setData({...data,reason:e.target.value})}/></label><ErrorNotice error={error}/>{saved&&<p role="status">专项草稿已保存。</p>}<div className="form-actions"><button className="button" type="button" disabled={disabled||pending} onClick={()=>void perform(false)}>保存专项草稿</button><button className="button primary" type="submit" disabled={disabled||pending}>提交并封存专项核实</button></div>
  </form>;
}

export function V13Workspace({task}:{task:V13Task}) {
  const client=useQueryClient();const [version,setVersion]=useState(task.draft?.version??0);
  const [idempotencyKey]=useState(()=>crypto.randomUUID());
  const disabled=task.status==="SEALED"||task.status==="CANCELLED"||task.paused===true||task.active===false;
  async function save(payload:ReviewV3|Record<string,unknown>) {const result=await apiV2<{version:number}>(`/assignments/${task.id}/draft`,{method:"PATCH",body:{phase:task.phase,version,payload}});setVersion(result.version);}
  async function submit(payload:ReviewV3|Record<string,unknown>) {await apiV2(`/assignments/${task.id}/submit`,{method:"POST",headers:{"Idempotency-Key":idempotencyKey},body:{phase:task.phase,content_revision:task.content_revision,profile_version:task.profile_version,payload}});await client.invalidateQueries({queryKey:["v13"]});}
  const contexts=task.material?.contexts??[];
  const specialized=task.dataset==="QA-D6"||task.dataset.startsWith("SEC-");
  return <><div className="task-meta"><span className="dataset-chip">{task.dataset}</span><strong>{task.unit_id}</strong><span>{task.workflow_kind==="VERIFICATION"?"主核实":"双人观测"} · {task.phase==="BLIND"?"独立判断":"草案比对"} · {task.status}</span><span className="tiny mono">{task.manual_version} · {task.content_revision.slice(0,12)} · 草稿 {version}</span></div><Panel title="题目与授权材料范围"><p className="task-question">{task.material?.question??(task.dataset==="QA-D6"?"按片段进行实体和关系独立判断":"安全专项材料核实")}</p></Panel><div className={task.phase==="REVIEW"?"task-review-grid":"workspace-grid"}><details className="workspace-reference" open={task.phase==="BLIND"}><summary>授权原文与材料</summary><Panel><div className="context-panel">{contexts.map(doc=><SourceDocument key={doc.doc_id} document={doc} open/>)}{specialized&&<pre className="v13-safe-material">{safeText(task.material)}</pre>}</div></Panel></details><Panel className="review-workspace">{task.phase==="BLIND"?<IndependentForm task={task} onSave={save} onSubmit={submit} disabled={disabled}/>:specialized?<SpecializedFormV3 task={task} onSave={save} onSubmit={submit} disabled={disabled}/>:<><AssociatedMaterials material={task.material}/><details><summary>本人封存的独立判断</summary><pre>{safeText(task.own_blind)}</pre></details><ReviewV3Form key={`${task.id}-${task.phase}`} dataset={task.dataset} workflowKind={task.workflow_kind} points={task.points??(task.gold?.answer_points??[]).map((text,index)=>({point_key:`P${String(index+1).padStart(3,"0")}`,text}))} gold={task.gold??{}} contexts={contexts} initial={(task.own_submission??task.draft?.payload??{}) as Partial<ReviewV3>} onSave={save} onSubmit={submit} disabled={disabled}/></>}</Panel></div><TaskIssue unitIndexId={task.unit_index_id}/></>;
}

export function V13TaskPage() {
  const {id}=useParams();const query=useQuery({queryKey:["v13","assignment",id],queryFn:({signal})=>apiV2<V13Task>(`/assignments/${id}`,{signal})});
  return <><Link to="/v13/tasks">← 返回我的核实任务</Link><PageHeader title="核实工作台" description="仅展示当前阶段授权材料与本人记录。刷新将加载服务端最新草稿。" action={<RefreshButton onClick={()=>void query.refetch()}/>}/><QueryState pending={query.isPending} error={query.error}>{query.data&&<V13Workspace key={`${query.data.id}-${query.data.phase}-${query.data.status}-${query.data.draft?.version??0}`} task={query.data}/>}</QueryState></>;
}
