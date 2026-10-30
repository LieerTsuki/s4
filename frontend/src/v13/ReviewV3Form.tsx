import { useState } from "react";
import type { ContextDocument, Point, PointLabel } from "../types";
import { LocatorEditor } from "../components/LocatorEditor";
import { validLocator } from "../locators";
import { SpecializedObservations } from "./SpecializedObservations";
import { PointSuggestions, EvidenceSuggestions } from "./ReviewSuggestions";
import type { AbsenceReason, EvidenceAssessment, EvidenceIntent, ReviewV3, V13Gold, Verdict, WorkflowKind } from "./types";

export function ReviewV3Form({dataset,workflowKind="VERIFICATION",points,gold,contexts,initial={},onSave,onSubmit,disabled=false}: {
  dataset: string; workflowKind?: WorkflowKind; points: Point[]; gold: V13Gold; contexts: ContextDocument[];
  initial?: Partial<ReviewV3>; onSave: (value: ReviewV3)=>Promise<void>; onSubmit: (value: ReviewV3)=>Promise<void>; disabled?: boolean;
}) {
  const [value,setValue]=useState<ReviewV3>({
    review_version:"openkb.s4-review.v3",workflow_kind:workflowKind,verdict:initial.verdict??"VERIFIED",
    point_labels:initial.point_labels??{},point_reasons:initial.point_reasons??{},point_evidence:initial.point_evidence??Object.fromEntries(points.map(point=>[point.point_key,[]])),point_search_scope:initial.point_search_scope??{},
    evidence_assessments:initial.evidence_assessments??{},expected_refusal:dataset==="QA-D4"?true:dataset==="QA-D4C"?false:initial.expected_refusal,
    absence_reason:initial.absence_reason??null,expected_refusal_reason:initial.expected_refusal_reason??"",reason:initial.reason??"",specialized_review:initial.specialized_review??{},
    suggested_points:initial.suggested_points??[],evidence_changes:initial.evidence_changes??[],
  });
  const [pending,setPending]=useState(false);
  const [error,setError]=useState("");
  const [saved,setSaved]=useState(false);
  const evidenceIds=Array.from(new Set([...(gold.gold_doc_ids??[]),...Object.keys(gold.ranking_annotations??{})]));
  const patch=(partial:Partial<ReviewV3>)=>setValue({...value,...partial});
  function assessment(id:string):EvidenceAssessment {
    return value.evidence_assessments[id]??{grade:gold.relevance_grades?.[id]??gold.ranking_annotations?.[id]??3,reason:"",locators:[],intent:(gold.gold_doc_ids??[]).includes(id)?"KEEP_GOLD":"KEEP_RANKING"};
  }
  function updateAssessment(id:string,partial:Partial<EvidenceAssessment>) { patch({evidence_assessments:{...value.evidence_assessments,[id]:{...assessment(id),...partial}}}); }
  async function perform(seal:boolean) {
    setError("");setSaved(false);
    const payload={...value,absence_reason:value.expected_refusal?value.absence_reason:null};
    if(seal&&(!(value.suggested_points??[]).every(item=>item.text.trim()&&item.reason.trim()&&item.evidence.length&&item.evidence.every(locator=>validLocator(locator,contexts)))||!(value.evidence_changes??[]).every(item=>item.doc_id&&item.reason.trim()&&(item.action==="remove"||item.locators.length)&&item.locators.every(locator=>validLocator(locator,contexts))))) {
      setError("请完成建议内容、理由和对应授权原文定位；不完整建议可先保存草稿。");return;
    }
    if (seal && (!points.every(p=>value.point_labels[p.point_key] && value.point_reasons[p.point_key]?.trim() && (
      (value.point_evidence[p.point_key]?.length && value.point_evidence[p.point_key].every(l=>validLocator(l,contexts))) ||
      (value.point_labels[p.point_key]==="wrong" && value.point_search_scope[p.point_key]?.length && value.point_search_scope[p.point_key].every(id=>contexts.some(c=>c.doc_id===id)))
    )) || !evidenceIds.every(id=>value.evidence_assessments[id]?.reason.trim()) || typeof value.expected_refusal!=="boolean" || !value.expected_refusal_reason.trim() || (value.expected_refusal && !value.absence_reason))) {
      setError("请完成逐点判断、理由与定位、逐文档判断，以及预期拒答和对应原因。");return;
    }
    setPending(true);
    try {await (seal?onSubmit:onSave)(payload);if(!seal)setSaved(true);} catch(e){setError(e instanceof Error?e.message:"保存失败");} finally {setPending(false);}
  }
  return <form className="review-form v13-review" noValidate onSubmit={e=>{e.preventDefault();void perform(true);}}>
    <div className="review-columns">
      <section className="review-column"><div className="section-eyebrow">01 · 答案要点</div><h3>逐点核实</h3>
        {!points.length && <p className="muted">此单元无原始答案要点；保留其专项语义。</p>}
        {points.map(point=><div className="label-card" key={point.point_key}><strong>{point.point_key}</strong><p>{point.text}</p>
          <label>正确性<select aria-label={`${point.point_key} 正确性`} disabled={disabled} value={value.point_labels[point.point_key]??""} onChange={e=>patch({point_labels:{...value.point_labels,[point.point_key]:e.target.value as PointLabel}})}><option value="">请选择</option><option value="correct">正确</option><option value="partial">部分正确</option><option value="wrong">错误</option></select></label>
          <label>判断理由<textarea aria-label={`${point.point_key} 理由`} disabled={disabled} value={value.point_reasons[point.point_key]??""} onChange={e=>patch({point_reasons:{...value.point_reasons,[point.point_key]:e.target.value}})}/></label>
          <LocatorEditor label={`${point.point_key} 定位`} contexts={contexts} value={value.point_evidence[point.point_key]??[]} disabled={disabled} onChange={locators=>patch({point_evidence:{...value.point_evidence,[point.point_key]:locators}})}/>
          {value.point_labels[point.point_key]==="wrong" && <fieldset disabled={disabled}><legend>确无支持时登记已查范围</legend>{contexts.map(doc=><label key={doc.doc_id}><input type="checkbox" checked={(value.point_search_scope[point.point_key]??[]).includes(doc.doc_id)} onChange={e=>patch({point_search_scope:{...value.point_search_scope,[point.point_key]:e.target.checked?[...(value.point_search_scope[point.point_key]??[]),doc.doc_id]:(value.point_search_scope[point.point_key]??[]).filter(id=>id!==doc.doc_id)}})}/>{doc.doc_id}</label>)}</fieldset>}
        </div>)}
        <PointSuggestions value={value.suggested_points??[]} contexts={contexts} disabled={disabled} onChange={suggested_points=>patch({suggested_points,verdict:suggested_points.length?"NEEDS_REVISION":value.verdict})}/>
      </section>
      <section className="review-column"><div className="section-eyebrow">02 · 证据链与排序辅助</div><h3>gold 与 ranking 分开核对</h3><p className="muted">最终 gold 仅 3/2，ranking 仅 1/0。同文档不能同时属于两集合；以下判断保留原对象，移动建议另记。</p>
        {evidenceIds.map(id=><div className="label-card" key={id}><strong>{id}</strong><p className="tiny muted">原集合：{(gold.gold_doc_ids??[]).includes(id)?"gold":"ranking"} · 原等级 {gold.relevance_grades?.[id]??gold.ranking_annotations?.[id]}</p>
          <label>相关度<select aria-label={`${id} 相关度`} value={assessment(id).grade} disabled={disabled} onChange={e=>updateAssessment(id,{grade:Number(e.target.value)})}><option value={3}>3 · 直接含答案</option><option value={2}>2 · 必要配套</option><option value={1}>1 · 背景相关</option><option value={0}>0 · 易混淆弱相关</option></select></label>
          <label>处理建议<select aria-label={`${id} 处理建议`} value={assessment(id).intent} disabled={disabled} onChange={e=>updateAssessment(id,{intent:e.target.value as EvidenceIntent})}><option value="KEEP_GOLD">保留 gold</option><option value="KEEP_RANKING">保留 ranking</option><option value="MOVE_TO_GOLD">移入 gold</option><option value="MOVE_TO_RANKING">移入 ranking</option><option value="REMOVE">移除</option></select></label>
          <label>证据理由<textarea aria-label={`${id} 理由`} value={assessment(id).reason} disabled={disabled} onChange={e=>updateAssessment(id,{reason:e.target.value})}/></label>
          <LocatorEditor label={`${id} 证据定位`} contexts={contexts} value={assessment(id).locators??[]} disabled={disabled} onChange={locators=>updateAssessment(id,{locators})}/>
        </div>)}
        <EvidenceSuggestions value={value.evidence_changes??[]} contexts={contexts} goldIds={gold.gold_doc_ids??[]} disabled={disabled} onChange={evidence_changes=>patch({evidence_changes,verdict:evidence_changes.length?"NEEDS_REVISION":value.verdict})}/>
      </section>
      <section className="review-column"><div className="section-eyebrow">03 · 预期拒答</div><h3>预期拒答与原因</h3><p className="muted">QA-D4 固定拒答；QA-D4C 固定可答。使用布尔值保存。</p>
        <label>预期拒答<select aria-label="预期拒答" value={value.expected_refusal===undefined?"":String(value.expected_refusal)} disabled={disabled || dataset==="QA-D4" || dataset==="QA-D4C"} onChange={e=>patch({expected_refusal:e.target.value===""?undefined:e.target.value==="true",absence_reason:null})}><option value="">请选择</option><option value="false">false · 应正常作答</option><option value="true">true · 应拒答</option></select></label>
        {value.expected_refusal && <label>拒答原因<select aria-label="拒答原因" disabled={disabled} value={value.absence_reason??""} onChange={e=>patch({absence_reason:e.target.value as AbsenceReason || null})}><option value="">请选择原因</option><option>库内无答案</option><option>答案已过期</option><option>答案在权限外</option></select></label>}
        <label>预期拒答判断理由<textarea aria-label="预期拒答判断理由" value={value.expected_refusal_reason} disabled={disabled} onChange={e=>patch({expected_refusal_reason:e.target.value})}/></label>
      </section>
    </div>
    <SpecializedObservations dataset={dataset} contexts={contexts} value={value.specialized_review} disabled={disabled} onChange={specialized_review=>patch({specialized_review})}/>
    <div className="v13-conclusion"><label>本条核实结论<select aria-label="核实结论" disabled={disabled} value={value.verdict} onChange={e=>patch({verdict:e.target.value as Verdict})}><option value="VERIFIED">核实通过</option><option value="NEEDS_REVISION">需要修订</option><option value="RETURNED">退回</option></select></label><label>核实说明<textarea aria-label="核实说明" value={value.reason} disabled={disabled} onChange={e=>patch({reason:e.target.value})}/></label></div>
    {error && <p role="alert" className="notice danger">{error}</p>}{saved && <p role="status">草稿已保存，尚未计入核实完成。</p>}
    <div className="form-actions"><button type="button" className="button" disabled={disabled||pending} onClick={()=>void perform(false)}>保存核实草稿</button><button type="submit" className="button primary" disabled={disabled||pending}>提交并封存核实</button></div>
  </form>;
}
