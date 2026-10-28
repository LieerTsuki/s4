import type { components } from "../generated/openapi";
import { api } from "../api";
import { SourceDocument } from "../components/SourceDocument";
import type { ContextDocument } from "../types";
import { useState } from "react";
import { useCommand, useList } from "../hooks";
import { formatTime, safeText } from "../format";
import { Badge, ErrorNotice, Panel, QueryState } from "../components/Common";

export interface GovernanceRecord {
  id: string;
  version?: number | string;
  revision?: number;
  state?: string;
  status?: string;
  dataset?: string;
  snapshot?: Record<string, unknown>;
  manual_version?: string;
  [key: string]: unknown;
}
const datasets = [
  "QA-D1",
  "QA-D2",
  "QA-D3",
  "QA-D4",
  "QA-D5",
  "QA-D6",
  "QA-D7",
  "SEC-D1",
  "SEC-D2",
  "SEC-D3",
  "SEC-D4",
  "SEC-D5",
];
function object(text: string): Record<string, unknown> {
  const data: unknown = JSON.parse(text);
  if (!data || typeof data !== "object" || Array.isArray(data))
    throw new Error("必须填写JSON对象");
  return data as Record<string, unknown>;
}
export function ProfileRevisions() {
  const query = useList<GovernanceRecord>("/profile-revisions");
  const command = useCommand();
  const [open, setOpen] = useState(false);
  const [dataset, setDataset] = useState("QA-D1");
  const [version, setVersion] = useState("");
  const [manual, setManual] = useState("");
  const [snapshot, setSnapshot] = useState("{}");
  const [reason, setReason] = useState("");
  const [evidence, setEvidence] = useState("{}");
  const [editing, setEditing] = useState<GovernanceRecord | null>(null);
  const [error, setError] = useState<Error | null>(null);
  async function send() {
    setError(null);
    try {
      const body: components["schemas"]["ProfileInput"] = {
        dataset,
        version,
        manual_version: manual,
        snapshot: { ...object(snapshot), version, manual_version: manual },
        reason,
      };
      const mutation: components["schemas"]["ProfileInput"] | components["schemas"]["ProfilePatch"] = editing
        ? { ...body, expected_revision: editing.revision! }
        : body;
      const result = await command.run(
        editing ? `/profile-revisions/${editing.id}` : "/profile-revisions",
        mutation,
        editing ? "PATCH" : "POST",
      );
      if (result) {
        setOpen(false);
        setEditing(null);
      }
    } catch (e) {
      setError(e as Error);
    }
  }
  async function review(item: GovernanceRecord, action: string) {
    setError(null);
    try {
      await command.run(`/profile-revisions/${item.id}/${action}`, {
        version: item.revision!,
        reason,
        evidence: object(evidence),
      });
    } catch (e) {
      setError(e as Error);
    }
  }
  return (
    <Panel
      title="配置版本与独立审批"
      description="已批准快照不可覆盖；新版本冻结手册、表单、定位与统计策略。服务端验证自批和核心量表约束。"
      action={
        <button
          className="button"
          onClick={() => {
            setEditing(null);
            setOpen(!open);
          }}
        >
          创建配置草案
        </button>
      }
    >
      <ErrorNotice error={error ?? command.error} />
      {open && (
        <form
          className="form-grid"
          onSubmit={(e) => {
            e.preventDefault();
            void send();
          }}
        >
          <label>
            数据集
            <select
              value={dataset}
              onChange={(e) => setDataset(e.target.value)}
            >
              {datasets.map((d) => (
                <option key={d}>{d}</option>
              ))}
            </select>
          </label>
          <label>
            配置版本
            <input
              required
              value={version}
              onChange={(e) => setVersion(e.target.value)}
            />
          </label>
          <label>
            手册版本
            <input
              required
              value={manual}
              onChange={(e) => setManual(e.target.value)}
            />
          </label>
          <label className="span-all">
            配置快照 JSON
            <textarea
              className="code-input"
              required
              rows={10}
              value={snapshot}
              onChange={(e) => setSnapshot(e.target.value)}
            />
          </label>
          <p className="muted span-all">
            从下方已批准版本复制后修改；仅接受有限Schema和已注册统计策略。专项审批不会自动补造κ或D7倍率。
          </p>
          <label className="span-all">
            配置变更理由
            <textarea
              required
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <button className="button primary" disabled={command.pending}>
            {editing ? "保存配置草案" : "登记配置草案"}
          </button>
        </form>
      )}
      <label>
        审批 / 流程理由
        <input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="提交、批准、退回、归档的依据"
        />
      </label>
      <label>
        审批证据 JSON
        <textarea
          className="code-input"
          value={evidence}
          onChange={(e) => setEvidence(e.target.value)}
        />
      </label>
      <QueryState pending={query.isPending} error={query.error}>
        {query.data?.items?.map((item) => (
          <details className="decision-card" key={item.id}>
            <summary>
              <span>
                {item.dataset} · {String(item.version)}
              </span>
              <Badge value={item.state ?? "UNKNOWN"} />
            </summary>
            <div className="decision-content">
              <pre className="source-text">{safeText(item)}</pre>
              <div className="button-row">
                <button
                  className="button small"
                  onClick={() => {
                    setDataset(String(item.dataset));
                    setVersion("");
                    setManual(String(item.manual_version ?? ""));
                    setSnapshot(JSON.stringify(item.snapshot ?? {}, null, 2));
                    setOpen(true);
                    setEditing(null);
                  }}
                >
                  复制为新草案
                </button>
                {item.state === "DRAFT" && (
                  <>
                    <button
                      className="button small"
                      onClick={() => {
                        setEditing(item);
                        setDataset(String(item.dataset));
                        setVersion(String(item.version));
                        setManual(String(item.manual_version ?? ""));
                        setSnapshot(
                          JSON.stringify(item.snapshot ?? {}, null, 2),
                        );
                        setOpen(true);
                      }}
                    >
                      编辑草案
                    </button>
                    <button
                      className="button small"
                      disabled={!reason.trim() || command.pending}
                      onClick={() => void review(item, "submit")}
                    >
                      提交审批
                    </button>
                  </>
                )}
                {item.state === "IN_REVIEW" && (
                  <>
                    <button
                      className="button small"
                      disabled={!reason.trim() || command.pending}
                      onClick={() => void review(item, "approve")}
                    >
                      独立批准
                    </button>
                    <button
                      className="button small"
                      disabled={!reason.trim() || command.pending}
                      onClick={() => void review(item, "reject")}
                    >
                      退回草案
                    </button>
                  </>
                )}
                {item.state === "APPROVED" && (
                  <button
                    className="button small"
                    disabled={!reason.trim() || command.pending}
                    onClick={() => void review(item, "retire")}
                  >
                    归档版本
                  </button>
                )}
              </div>
            </div>
          </details>
        ))}
      </QueryState>
    </Panel>
  );
}

export function IssuesPage() {
  const query = useList<GovernanceRecord>("/work-issues");
  const command = useCommand();
  const [reason, setReason] = useState("");
  const [disposition, setDisposition] = useState("UNCHANGED");
  const [revision, setRevision] = useState("");
  return (
    <Panel
      title="材料问题处理"
      description="只展示服务端授权范围。实质变化必须关联新revision；原封存保留历史。"
    >
      <label>
        处置理由
        <textarea value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <label>
        处置方式
        <select
          value={disposition}
          onChange={(e) => setDisposition(e.target.value)}
        >
          <option value="UNCHANGED">原材料不变</option>
          <option value="NEW_REVISION">使用新revision</option>
        </select>
      </label>
      {disposition === "NEW_REVISION" && (
        <label>
          新revision引用
          <input
            value={revision}
            onChange={(e) => setRevision(e.target.value)}
          />
        </label>
      )}
      <ErrorNotice error={command.error} />
      <QueryState pending={query.isPending} error={query.error}>
        {query.data?.items?.map((item) => (
          <article className="label-card" key={item.id}>
            <strong>
              {String(item.issue_type)} ·{" "}
              {String(item.unit_id ?? item.assignment_id)}
            </strong>
            <Badge value={item.status ?? "OPEN"} />
            <pre>{safeText(item)}</pre>
            {item.status === "OPEN" && (
              <button
                className="button"
                disabled={
                  command.pending ||
                  !reason.trim() ||
                  (disposition === "NEW_REVISION" && !revision.trim())
                }
                onClick={() =>
                  void command.run(`/work-issues/${item.id}/resolve`, {
                    version: item.version,
                    reason,
                    disposition,
                    ...(revision ? { revision_ref: revision } : {}),
                  })
                }
              >
                独立处置问题
              </button>
            )}
          </article>
        ))}
      </QueryState>
    </Panel>
  );
}

interface Field {
  name: string;
  label: string;
  kind?: "json" | "lines" | "date" | "boolean" | "dataset";
  initial?: string;
}
const definitions: Record<
  string,
  { title: string; description: string; fields: Field[] }
> = {
  "/calibrations": {
    title: "校准会议与培训记录",
    description: "关联旧批、争议案例、手册版本与培训材料；新轮须引用此记录。",
    fields: [
      { name: "batch_id", label: "旧批次ID" },
      { name: "meeting_at", label: "会议时间", kind: "date" },
      { name: "participant_ids", label: "参加人ID（每行一个）", kind: "lines" },
      { name: "case_refs", label: "争议案例引用（每行一个）", kind: "lines" },
      { name: "decisions", label: "会议决定" },
      { name: "manual_version", label: "校准手册版本" },
      {
        name: "training_refs",
        label: "培训材料引用（每行一个）",
        kind: "lines",
      },
      { name: "reason", label: "重标与校准理由" },
    ],
  },
  "/qualifications": {
    title: "人员资格与可用性",
    description: "资格依据和有效期由授权人员登记；专项无资格时排班继续阻塞。",
    fields: [
      { name: "user_id", label: "人员账号ID" },
      { name: "dataset", label: "资格数据集", kind: "dataset" },
      {
        name: "available",
        label: "当前可排班",
        kind: "boolean",
        initial: "true",
      },
      { name: "valid_until", label: "资格有效至", kind: "date" },
      { name: "evidence", label: "资格批准依据 JSON", kind: "json" },
      { name: "reason", label: "资格登记理由" },
    ],
  },
  "/validation-revisions": {
    title: "独立复验证据",
    description:
      "绑定最终候选内容与profile摘要。浏览器不声明passed；受控证据和独立性由服务端核验。",
    fields: [
      { name: "batch_id", label: "复验批次ID" },
      { name: "unit_id", label: "复验单元ID" },
      { name: "final_gold", label: "最终gold JSON", kind: "json" },
      { name: "content_hash", label: "完整候选SHA-256" },
      { name: "profile_hash", label: "冻结profile SHA-256" },
      { name: "evidence", label: "受控复验证据 JSON", kind: "json" },
      { name: "reason", label: "独立复验理由" },
    ],
  },
};
export function GovernanceForm({ path }: { path: string }) {
  const definition = definitions[path];
  const query = useList<GovernanceRecord>(path);
  const command = useCommand();
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      definition.fields.map((f) => [
        f.name,
        f.initial ??
          (f.kind === "json" ? "{}" : f.kind === "dataset" ? "QA-D1" : ""),
      ]),
    ),
  );
  const [error, setError] = useState<Error | null>(null);
  const [candidate, setCandidate] = useState<{
    contexts: ContextDocument[];
    proposal_id?: string;
  } | null>(null);
  const [verifierId, setVerifierId] = useState("");
  async function loadCandidate(propose: boolean) {
    setError(null);
    try {
      const data = propose
        ? await api<Record<string, unknown>>("/validation-candidates", {
            method: "POST",
            body: {
              batch_id: values.batch_id,
              unit_id: values.unit_id,
              final_gold: object(values.final_gold),
              reason: values.reason,
              verifier_id: verifierId,
            },
          })
        : await api<Record<string, unknown>>(
            `/validation-candidates?batch_id=${encodeURIComponent(values.batch_id)}&unit_id=${encodeURIComponent(values.unit_id)}`,
          );
      setValues({
        ...values,
        final_gold: JSON.stringify(data.final_gold, null, 2),
        content_hash: String(data.content_hash),
        profile_hash: String(data.profile_hash),
      });
      setCandidate({
        contexts: (data.contexts ?? []) as ContextDocument[],
        proposal_id: String(data.proposal_id ?? ""),
      });
      command.setSuccess(
        propose
          ? "复验候选已登记，请由独立复验员加载并验证。"
          : "已加载冻结候选；修改内容须重新登记候选。",
      );
    } catch (e) {
      setError(e as Error);
    }
  }

  return (
    <Panel title={definition.title} description={definition.description}>
      {path === "/validation-revisions" && (
        <div className="action-bar">
          <label>
            指定复验人ID
            <input
              value={verifierId}
              onChange={(event) => setVerifierId(event.target.value)}
              placeholder="由负责人指定独立复验账号"
            />
          </label>
          <button
            className="button"
            disabled={!values.batch_id || !values.unit_id}
            onClick={() => void loadCandidate(false)}
          >
            载入已登记复验候选
          </button>
          <button
            className="button"
            disabled={
              !values.batch_id ||
              !values.unit_id ||
              !values.reason ||
              !verifierId.trim()
            }
            onClick={() => void loadCandidate(true)}
          >
            提交复验候选（负责人）
          </button>
        </div>
      )}
      {candidate && (
        <details>
          <summary>冻结复验材料 · {candidate.proposal_id}</summary>
          {candidate.contexts.map((doc) => (
            <SourceDocument key={doc.doc_id} document={doc} />
          ))}
        </details>
      )}
      <form
        className="form-grid"
        onSubmit={async (e) => {
          e.preventDefault();
          setError(null);
          try {
            const body = Object.fromEntries(
              definition.fields.map((field) => {
                const v = values[field.name];
                return [
                  field.name,
                  field.kind === "json"
                    ? object(v)
                    : field.kind === "lines"
                      ? v
                          .split("\n")
                          .map((s) => s.trim())
                          .filter(Boolean)
                      : field.kind === "boolean"
                        ? v === "true"
                        : field.kind === "date"
                          ? new Date(v).toISOString()
                          : v,
                ];
              }),
            );
            const result = await command.run(path, body);
            if (result)
              command.setSuccess("记录已登记，最终状态以服务端核验结果为准。");
          } catch (e) {
            setError(e as Error);
          }
        }}
      >
        {definition.fields.map((field) => (
          <label
            key={field.name}
            className={field.kind === "json" ? "span-all" : ""}
          >
            {field.label}
            {field.kind === "boolean" ? (
              <input
                type="checkbox"
                checked={values[field.name] === "true"}
                onChange={(e) =>
                  setValues({
                    ...values,
                    [field.name]: String(e.target.checked),
                  })
                }
              />
            ) : field.kind === "dataset" ? (
              <select
                value={values[field.name]}
                onChange={(e) =>
                  setValues({ ...values, [field.name]: e.target.value })
                }
              >
                {datasets.map((d) => (
                  <option key={d}>{d}</option>
                ))}
              </select>
            ) : field.kind === "json" || field.kind === "lines" ? (
              <textarea
                rows={field.kind === "json" ? 5 : 3}
                required
                value={values[field.name]}
                onChange={(e) =>
                  setValues({ ...values, [field.name]: e.target.value })
                }
              />
            ) : (
              <input
                required
                type={field.kind === "date" ? "datetime-local" : "text"}
                value={values[field.name]}
                onChange={(e) =>
                  setValues({ ...values, [field.name]: e.target.value })
                }
              />
            )}
          </label>
        ))}
        <button className="button primary" disabled={command.pending}>
          登记{definition.title}
        </button>
      </form>
      <ErrorNotice error={error ?? command.error} />
      {command.success && (
        <div role="status" className="notice success">
          {command.success}
        </div>
      )}
      <QueryState pending={query.isPending} error={query.error}>
        {query.data?.items?.map((item) => (
          <details className="decision-card" key={item.id}>
            <summary>
              {String(item.unit_id ?? item.user_id ?? item.batch_id ?? item.id)}{" "}
              · {item.status ?? formatTime(String(item.created_at ?? ""))}
            </summary>
            <pre className="source-text">{safeText(item)}</pre>
          </details>
        ))}
      </QueryState>
    </Panel>
  );
}
export function GovernancePage({
  verifierOnly = false,
}: {
  verifierOnly?: boolean;
}) {
  const [tab, setTab] = useState(
    verifierOnly ? "/validation-revisions" : "/work-issues",
  );
  return (
    <>
      <h1>材料、资格与复验</h1>
      <div className="filter-tabs">
        {[
          ["/work-issues", "材料问题"],
          ["/calibrations", "校准会议"],
          ["/qualifications", "人员资格"],
          ["/validation-revisions", "独立复验"],
        ]
          .filter(
            ([value]) => !verifierOnly || value === "/validation-revisions",
          )
          .map(([value, label]) => (
            <button
              key={value}
              className={tab === value ? "active" : ""}
              onClick={() => setTab(value)}
            >
              {label}
            </button>
          ))}
      </div>
      {tab === "/work-issues" ? (
        <IssuesPage />
      ) : (
        <GovernanceForm key={tab} path={tab} />
      )}
    </>
  );
}
