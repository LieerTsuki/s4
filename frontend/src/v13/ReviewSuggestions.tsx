import type { ContextDocument, EvidenceChange, SuggestedPoint } from "../types";
import { LocatorEditor } from "../components/LocatorEditor";

export function PointSuggestions({value,contexts,onChange,disabled=false}:{
  value:SuggestedPoint[];contexts:ContextDocument[];onChange:(value:SuggestedPoint[])=>void;disabled?:boolean;
}) {
  function update(index:number,patch:Partial<SuggestedPoint>) {onChange(value.map((item,i)=>i===index?{...item,...patch}:item));}
  return <fieldset disabled={disabled}><legend>遗漏要点建议（与原始标签分开）</legend>
    {value.map((item,index)=><div className="label-card" key={item.suggestion_id}>
      <label>遗漏要点 {index+1}<textarea aria-label={`遗漏要点 ${index+1}`} value={item.text} onChange={event=>update(index,{text:event.target.value})}/></label>
      <label>遗漏理由 {index+1}<textarea aria-label={`遗漏理由 ${index+1}`} value={item.reason} onChange={event=>update(index,{reason:event.target.value})}/></label>
      <LocatorEditor label={`遗漏要点 ${index+1} 定位`} contexts={contexts} value={item.evidence} disabled={disabled} onChange={evidence=>update(index,{evidence})}/>
      <button type="button" className="text-button" onClick={()=>onChange(value.filter((_,i)=>i!==index))}>移除遗漏建议 {index+1}</button>
    </div>)}
    <button type="button" className="button" onClick={()=>onChange([...value,{suggestion_id:crypto.randomUUID(),text:"",reason:"",evidence:[]}])}>新增遗漏要点建议</button>
  </fieldset>;
}

export function EvidenceSuggestions({value,contexts,goldIds,onChange,disabled=false}:{
  value:EvidenceChange[];contexts:ContextDocument[];goldIds:string[];onChange:(value:EvidenceChange[])=>void;disabled?:boolean;
}) {
  function update(index:number,patch:Partial<EvidenceChange>) {onChange(value.map((item,i)=>i===index?{...item,...patch}:item));}
  return <fieldset disabled={disabled}><legend>增删证据建议（不改原始判断）</legend>
    {value.map((item,index)=><div className="label-card" key={item.change_id}>
      <label>变更动作<select aria-label={`证据变更动作 ${index+1}`} value={item.action} onChange={event=>update(index,{action:event.target.value as "add"|"remove",doc_id:"",locators:[]})}><option value="add">新增证据</option><option value="remove">移除证据</option></select></label>
      <label>变更文档<select aria-label={`证据变更文档 ${index+1}`} value={item.doc_id} onChange={event=>update(index,{doc_id:event.target.value,locators:[]})}><option value="">请选择授权原文</option>{contexts.filter(doc=>item.action==="add"?!goldIds.includes(doc.doc_id):goldIds.includes(doc.doc_id)).map(doc=><option key={doc.doc_id}>{doc.doc_id}</option>)}</select></label>
      <label>变更理由<textarea aria-label={`证据变更理由 ${index+1}`} value={item.reason} onChange={event=>update(index,{reason:event.target.value})}/></label>
      <LocatorEditor label={`证据变更 ${index+1} 定位`} contexts={contexts.filter(doc=>doc.doc_id===item.doc_id)} value={item.locators} disabled={disabled} onChange={locators=>update(index,{locators})}/>
      <button type="button" className="text-button" onClick={()=>onChange(value.filter((_,i)=>i!==index))}>移除证据建议 {index+1}</button>
    </div>)}
    <button type="button" className="button" onClick={()=>onChange([...value,{change_id:crypto.randomUUID(),action:"add",doc_id:"",reason:"",locators:[]}])}>新增证据变更建议</button>
  </fieldset>;
}
