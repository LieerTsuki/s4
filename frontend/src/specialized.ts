import type { ContextDocument, ReviewPayload } from "./types";
import { validLocator } from "./locators";
export const specializedFields: Record<string, string[]> = {
  "QA-D2": ["cross_domain", "joint_evidence"],
  "QA-D3": ["hop_chain", "missing_links"],
  "QA-D4": ["unanswerable_scope"],
  "QA-D5": ["key_fact_anchors"],
  "QA-D6": ["embedding_consistency", "completeness", "expiry"],
  "QA-D7": [
    "source_case_resolution",
    "source_composition",
    "evidence_union",
    "k_rule",
  ],
  "SEC-D1": ["acl_scope", "refusal_redaction"],
  "SEC-D2": ["direct_injection", "indirect_injection", "blocking"],
  "SEC-D3": ["implant", "query_verification", "rollback", "residual"],
  "SEC-D4": ["inside_outside_pair", "language", "length", "style", "topic"],
  "SEC-D5": ["synthetic_pii_provenance", "leakage"],
};
export const labels: Record<string, string> = {
  cross_domain: "双域材料标识",
  joint_evidence: "联合依据",
  hop_chain: "按跳序证据链",
  missing_links: "缺环检查",
  unanswerable_scope: "不可答范围与时效",
  key_fact_anchors: "逐事实原文锚点",
  embedding_consistency: "Embedding一致性",
  completeness: "完整率观察",
  expiry: "过期率观察",
  source_case_resolution: "源题引用解析",
  source_composition: "源集组成",
  evidence_union: "证据并集",
  k_rule: "K规则引用（未确认仍阻塞）",
  acl_scope: "ACL角色与范围",
  refusal_redaction: "拒答或脱敏行为",
  direct_injection: "直接注入载荷",
  indirect_injection: "间接注入载荷",
  blocking: "拦截行为",
  implant: "植入步骤",
  query_verification: "查询验证",
  rollback: "Rollback步骤",
  residual: "Residual=0证据",
  inside_outside_pair: "库内外配对",
  language: "语言对照",
  length: "长度对照",
  style: "文体对照",
  topic: "主题对照",
  synthetic_pii_provenance: "合成PII来源证明",
  leakage: "泄露行为观察",
};
export type Observations = NonNullable<ReviewPayload["specialized_review"]>;
export function completeSpecialized(
  dataset: string,
  value: Observations | undefined,
  contexts: ContextDocument[],
) {
  return (specializedFields[dataset] ?? []).every(
    (key) =>
      value?.[key]?.observation?.trim() &&
      value[key].reason?.trim() &&
      value[key].evidence?.length &&
      value[key].evidence.every((l) => validLocator(l, contexts)),
  );
}
