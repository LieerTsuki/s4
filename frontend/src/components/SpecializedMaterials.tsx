import { safeText } from "../format";

const fields: Record<string, [string, string][]> = {
  "QA-D1": [
    ["domain", "同域说明"],
    ["same_domain", "同域材料标识"],
  ],
  "QA-D2": [
    ["domains", "双域标识"],
    ["joint_evidence", "联合依据说明"],
  ],
  "QA-D3": [
    ["reasoning_chain", "按跳序证据链"],
    ["missing_links", "缺环记录"],
  ],
  "QA-D4": [
    ["unanswerable_reason", "不可答原因"],
    ["validity_scope", "时效与授权范围"],
  ],
  "QA-D5": [["key_fact_anchors", "逐事实原文锚点"]],
  "QA-D6": [
    ["embedding_version", "Embedding版本"],
    ["embedding_metrics", "一致性原始指标"],
    ["completeness", "完整率原始指标"],
    ["expiry", "过期率原始指标"],
  ],
  "QA-D7": [
    ["source_composition", "源集组成"],
    ["k_rule_ref", "K规则确认引用"],
  ],
  "SEC-D1": [
    ["acl_roles", "ACL角色"],
    ["access_scope", "授权范围"],
  ],
  "SEC-D2": [
    ["direct_injection", "直接注入载荷"],
    ["indirect_injection", "间接注入载荷"],
  ],
  "SEC-D3": [
    ["rollback_evidence", "Rollback证据"],
    ["query_verification", "查询验证步骤"],
  ],
  "SEC-D4": [
    ["pair_controls", "库内外配对"],
    ["language", "语言对照"],
    ["length", "长度对照"],
    ["style", "文体对照"],
    ["topic", "主题对照"],
  ],
  "SEC-D5": [
    ["synthetic_pii", "合成PII来源声明"],
    ["synthetic_pii_provenance", "合成来源证明"],
  ],
};

export function SpecializedMaterials({
  dataset,
  metadata,
}: {
  dataset: string;
  metadata?: Record<string, unknown>;
}) {
  return (
    <details className="specialized-materials">
      <summary>{dataset} 专项材料核对</summary>
      {(fields[dataset] ?? []).map(([key, label]) => (
        <div className="context-meta" key={key}>
          <strong>{label}</strong>
          {metadata?.[key] === undefined ? (
            <p className="muted">
              源材料未提供，待补充；不据此虚构观察或规则。
            </p>
          ) : (
            <pre>{safeText(metadata[key])}</pre>
          )}
        </div>
      ))}
    </details>
  );
}
