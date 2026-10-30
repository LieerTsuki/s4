import type { ContextDocument } from "../types";
import { LocatorEditor } from "../components/LocatorEditor";
import type { ReviewV3 } from "./types";

const fields:Record<string,[string,string][]>= {
  "QA-D2":[["domain_evidence","跨域联合证据"]],
  "QA-D3":[["reasoning_chain","多跳推理链与顺序"]],
  "QA-D5":[["key_facts","可核验事实与faithfulness锚点"]],
  "QA-D7":[["same_intent","同意图人工确认"],["source_lineage","源题血缘与题内去重"],["evaluation_k","K取源题最大值"]],
  "QA-D6":[["entity_spans","实体名称与码点跨度"],["entity_types","已登记实体词表"],["relation_links","关系头尾与词表"]],
  "SEC-D1":[["acl","ACL权限边界"],["forbidden_documents","禁看文档集合"]],
  "SEC-D2":[["expected_effect","效果判据"],["attack_type","攻击类型与材料"]],
  "SEC-D3":[["baseline","注入前基线与采集时间"],["target_claim","目标主张"],["rollback","回滚材料与零残留证明"]],
  "SEC-D4":[["pair_controls","同分布配对与top_n"],["ranking","retrieve排名；未入top-N=N+1"]],
  "SEC-D5":[["synthetic_pii","全合成PII证明"],["non_disclosure","预期不泄露行为"]],
};

export function SpecializedObservations({dataset,contexts,value,onChange,disabled=false}:{dataset:string;contexts:ContextDocument[];value:ReviewV3["specialized_review"];onChange:(value:ReviewV3["specialized_review"])=>void;disabled?:boolean}) {
  const items=fields[dataset]??[];
  if(!items.length)return null;
  return <section className="v13-specialized-observations"><h3>专项核实记录</h3><div className="v13-specialized-grid">{items.map(([key,label])=>{
    const item=value[key]??{observation:"",reason:"",evidence:[]};
    const change=(patch:Partial<typeof item>)=>onChange({...value,[key]:{...item,...patch}});
    return <fieldset disabled={disabled} className="label-card" key={key}><legend>{label}</legend><label>核实判断<select aria-label={`${key} 判断`} value={item.observation} onChange={e=>change({observation:e.target.value})}><option value="">请选择</option><option value="pass">材料支持</option><option value="issue">存在问题</option><option value="not_applicable">不适用（须说明）</option></select></label><label>判断理由<textarea aria-label={`${key} 理由`} value={item.reason} onChange={e=>change({reason:e.target.value})}/></label><LocatorEditor label={`${key} 依据`} contexts={contexts} value={item.evidence} disabled={disabled} onChange={evidence=>change({evidence})}/></fieldset>;
  })}</div></section>;
}
