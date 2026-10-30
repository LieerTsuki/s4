import { useState } from "react";
import type { Entity, Extraction, Relation, Vocabulary } from "./types";
import { codePointRange } from "./unicode";

export function ExtractionEditor({text, vocabulary, value, onChange, disabled=false}: {
  text: string; vocabulary?: Vocabulary | null; value: Extraction; onChange: (value: Extraction) => void; disabled?: boolean;
}) {
  const [range, setRange] = useState<[number,number]>([0,0]);
  const [entityType,setEntityType]=useState(vocabulary?.entity_types[0] ?? "");
  const [head,setHead]=useState("");
  const [tail,setTail]=useState("");
  const [relationType,setRelationType]=useState(vocabulary?.relation_types[0] ?? "");
  const [error,setError]=useState("");
  const entities=value.gold_entities;
  function addEntity() {
    if (!vocabulary || !vocabulary.entity_types.includes(entityType) || range[0]>=range[1]) {
      setError("请先选择片段原文并使用已登记词表中的类型。"); return;
    }
    const entity: Entity={entity_id:crypto.randomUUID(),name:Array.from(text).slice(...range).join(""),type:entityType,span:range};
    onChange({...value,gold_entities:[...entities,entity]}); setError("");
  }
  function addRelation() {
    if (!vocabulary || !vocabulary.relation_types.includes(relationType) || !entities.some(e=>e.entity_id===head) || !entities.some(e=>e.entity_id===tail)) {
      setError("关系头尾必须指向本条已有实体，类型必须属于已登记词表。"); return;
    }
    const relation: Relation={head,tail,type:relationType};
    onChange({...value,gold_relations:[...value.gold_relations,relation]}); setError("");
  }
  return <section className="v13-extraction">
    <h3>实体与关系标注</h3>
    {!vocabulary && <p className="notice warm">当前未提供已登记的完整词表，实体类型与关系类型不可自由填写。可保存问题，不能核实通过。</p>}
    {vocabulary && <p className="tiny mono">词表 {vocabulary.version} · {vocabulary.sha256}</p>}
    <label>片段原文：选中文字建立跨度<textarea aria-label="抽取片段原文" readOnly value={text} rows={6} onSelect={event=>setRange(codePointRange(text,event.currentTarget.selectionStart,event.currentTarget.selectionEnd))}/></label>
    <p className="tiny muted">已选 Unicode 码点 [{range[0]}, {range[1]})；😀按一个字符计数。</p>
    <fieldset disabled={disabled || !vocabulary}>
      <label>实体类型<select aria-label="实体类型" value={entityType} onChange={e=>setEntityType(e.target.value)}>{vocabulary?.entity_types.map(t=><option key={t}>{t}</option>)}</select></label>
      <button type="button" className="button" onClick={addEntity}>添加选中实体</button>
      {entities.map(entity=><div className="label-card" key={entity.entity_id}>
        <strong>{entity.name}</strong> · {entity.type} [{entity.span.join(", ")})
        <button type="button" className="text-button" aria-label={`删除实体 ${entity.entity_id}`} onClick={()=>onChange({gold_entities:entities.filter(e=>e.entity_id!==entity.entity_id),gold_relations:value.gold_relations.filter(r=>r.head!==entity.entity_id && r.tail!==entity.entity_id)})}>删除实体及其关系</button>
      </div>)}
      <label>关系起点<select aria-label="关系起点" value={head} onChange={e=>setHead(e.target.value)}><option value="">请选择实体</option>{entities.map(e=><option key={e.entity_id} value={e.entity_id}>{e.name} · {e.entity_id}</option>)}</select></label>
      <label>关系终点<select aria-label="关系终点" value={tail} onChange={e=>setTail(e.target.value)}><option value="">请选择实体</option>{entities.map(e=><option key={e.entity_id} value={e.entity_id}>{e.name} · {e.entity_id}</option>)}</select></label>
      <label>关系类型<select aria-label="关系类型" value={relationType} onChange={e=>setRelationType(e.target.value)}>{vocabulary?.relation_types.map(t=><option key={t}>{t}</option>)}</select></label>
      <button type="button" className="button" onClick={addRelation}>添加关系</button>
      {value.gold_relations.map((relation,index)=><div className="label-card" key={index}>{relation.head} → {relation.tail} · {relation.type}<button type="button" className="text-button" onClick={()=>onChange({...value,gold_relations:value.gold_relations.filter((_,i)=>i!==index)})}>删除关系 {index+1}</button></div>)}
    </fieldset>
    {error && <p role="alert">{error}</p>}
  </section>;
}
