import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { User } from "../types";
import { useList } from "../hooks";
import { Empty, ErrorNotice, PageHeader, Panel, QueryState } from "../components/Common";
import { safeText } from "../format";
import { apiV2, listV2 } from "./api";
import type { V13Batch, V13Import } from "./types";

interface Issue {
  id: string; import_id: string; unit_index_id: string; status: string;
  reason?: string; record?: Record<string, unknown>; resolution?: Record<string, unknown>;
}
interface Revision {
  id: string; unit_index_id: string; status: string;
  verifier_id?: string;
  candidate: Record<string, unknown>; proposal: Record<string, unknown>;
}

function jsonEvidence(value: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed) || !Object.keys(parsed).length)
    throw new Error("证据须为包含实际依据的JSON对象。");
  return parsed as Record<string, unknown>;
}

function useV13Command() {
  const client = useQueryClient();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [success, setSuccess] = useState("");
  async function run(path: string, body: unknown): Promise<Record<string, unknown> | undefined> {
    setPending(true); setError(null); setSuccess("");
    try {
      const result = await apiV2<Record<string, unknown>>(path, { method: "POST", body });
      await client.invalidateQueries({ queryKey: ["v13"] });
      setSuccess("处理记录已封存，当前状态以服务端核对结果为准。");
      return result;
    } catch (failure) {
      setError(failure instanceof Error ? failure : new Error("操作失败"));
    } finally { setPending(false); }
  }
  return { run, pending, error, success, setError };
}

export function TaskIssue({ unitIndexId }: { unitIndexId?: string }) {
  const [reason, setReason] = useState("");
  const command = useV13Command();
  if (!unitIndexId) return null;
  return <Panel title="材料问题与暂停">
    <p>原文缺失、摘要不符或判据不足时提交问题。实质内容变更需要新修订及独立复验，关闭问题不会改写原封存。</p>
    <label>材料问题说明<textarea aria-label="材料问题说明" value={reason} onChange={event => setReason(event.target.value)} /></label>
    <button type="button" className="button" disabled={command.pending || !reason.trim()} onClick={() => void command.run("/issues", { unit_index_id: unitIndexId, reason })}>提交材料问题并暂停相关任务</button>
    <ErrorNotice error={command.error} />{command.success && <p role="status">{command.success}</p>}
  </Panel>;
}

function IssueCard({ issue, canResolve }: { issue: Issue; canResolve: boolean }) {
  const [reason, setReason] = useState("");
  const [evidence, setEvidence] = useState("{}");
  const command = useV13Command();
  async function resolve() {
    try { await command.run(`/issues/${issue.id}/resolve`, { reason, evidence: jsonEvidence(evidence) }); }
    catch (failure) { command.setError(failure instanceof Error ? failure : new Error("证据格式错误")); }
  }
  return <Panel title={`${issue.id} · ${issue.status}`}>
    <p className="mono tiny">单元索引 {issue.unit_index_id}</p>
    <p>{issue.reason ?? safeText(issue.record)}</p>
    {issue.resolution && <pre className="v13-safe-material">{safeText(issue.resolution)}</pre>}
    {canResolve && issue.status === "OPEN" && <>
      <label>解决说明<textarea aria-label={`${issue.id} 解决说明`} value={reason} onChange={event => setReason(event.target.value)} /></label>
      <label>实际解决证据 JSON<textarea aria-label={`${issue.id} 解决证据`} value={evidence} onChange={event => setEvidence(event.target.value)} /></label>
      <button className="button" disabled={command.pending || !reason.trim()} onClick={() => void resolve()}>封存材料问题处理</button>
      <p className="tiny muted">服务端检查独立处理人；问题提出者不能自行解决。</p>
    </>}
    <ErrorNotice error={command.error} />{command.success && <p role="status">{command.success}</p>}
  </Panel>;
}

function RevisionCard({ revision, canVerify }: { revision: Revision; canVerify: boolean }) {
  const [outcome, setOutcome] = useState("PASS");
  const [reason, setReason] = useState("");
  const [evidence, setEvidence] = useState("{}");
  const command = useV13Command();
  async function verify() {
    try { await command.run(`/revisions/${revision.id}/verify`, { outcome, reason, evidence: jsonEvidence(evidence) }); }
    catch (failure) { command.setError(failure instanceof Error ? failure : new Error("证据格式错误")); }
  }
  return <Panel title={`${revision.id} · ${revision.status}`}>
    <p className="mono tiny">单元索引 {revision.unit_index_id}</p>
    <details><summary>查看修订候选与原始提议</summary><pre className="v13-safe-material">{safeText(revision.candidate)}</pre><pre className="v13-safe-material">{safeText(revision.proposal)}</pre></details>
    {canVerify && revision.status === "PENDING" && <>
      <label>独立复验结论<select aria-label={`${revision.id} 复验结论`} value={outcome} onChange={event => setOutcome(event.target.value)}><option value="PASS">通过</option><option value="FAIL">不通过</option></select></label>
      <label>独立复验说明<textarea aria-label={`${revision.id} 复验说明`} value={reason} onChange={event => setReason(event.target.value)} /></label>
      <label>独立验证证据 JSON<textarea aria-label={`${revision.id} 复验证据`} value={evidence} onChange={event => setEvidence(event.target.value)} /></label>
      <button className="button" disabled={command.pending || !reason.trim()} onClick={() => void verify()}>封存独立复验结果</button>
      <p className="tiny muted">仅指定复验员能提交；原核实人员、观测人员与提议者不能自验。</p>
    </>}
    <ErrorNotice error={command.error} />{command.success && <p role="status">{command.success}</p>}
  </Panel>;
}

function RevisionProposal({currentUserId}:{currentUserId:string}) {
  const imports = useQuery({ queryKey: ["v13", "imports"], queryFn: ({ signal }) => listV2<V13Import>("/imports", signal) });
  const [importId, setImportId] = useState("");
  const detail = useQuery({ queryKey: ["v13", "import", importId], queryFn: ({ signal }) => apiV2<{ units: { unit_index_id: string; unit_id: string }[] }>(`/imports/${importId}`, { signal }), enabled: !!importId });
  const users = useList<User>("/users");
  const [unit, setUnit] = useState("");
  const [verifier, setVerifier] = useState("");
  const [candidate, setCandidate] = useState("{}");
  const [reason, setReason] = useState("");
  const [loadingCandidate,setLoadingCandidate]=useState(false);
  const command = useV13Command();
  async function loadCandidate() {
    setLoadingCandidate(true);command.setError(null);
    try {const result=await apiV2<{candidate:Record<string,unknown>}>(`/units/${unit}`);setCandidate(JSON.stringify(result.candidate,null,2));}
    catch(failure) {command.setError(failure instanceof Error?failure:new Error("无法载入当前候选"));}
    finally {setLoadingCandidate(false);}
  }
  async function propose() {
    try { await command.run("/revisions", { unit_index_id: unit, verifier_id: verifier, candidate: jsonEvidence(candidate), reason }); }
    catch (failure) { command.setError(failure instanceof Error ? failure : new Error("候选格式错误")); }
  }
  return <Panel title="提出实质修订与指定独立复验">
    <p>提交完整新版候选，保持单元身份和冻结原文。原S3报告与原始双方标签不回写；最终候选需真实独立验证。</p>
    <label>来源<select aria-label="修订来源" value={importId} onChange={event => { setImportId(event.target.value); setUnit(""); }}><option value="">请选择来源</option>{imports.data?.items.map(item => <option key={item.id} value={item.id}>{item.batch_id}</option>)}</select></label>
    <label>单元<select aria-label="修订单元" value={unit} onChange={event => setUnit(event.target.value)}><option value="">请选择单元</option>{detail.data?.units.map(item => <option key={item.unit_index_id} value={item.unit_index_id}>{item.unit_id}</option>)}</select></label>
    <label>独立复验员<select aria-label="指定独立复验员" value={verifier} onChange={event => setVerifier(event.target.value)}><option value="">请选择复验员</option>{users.data?.items.filter(item => item.active && item.id!==currentUserId && item.roles.includes("verifier")).map(item => <option key={item.id} value={item.id}>{item.display_name} · {item.person_id}</option>)}</select></label>
    <button className="button" disabled={!unit||loadingCandidate} onClick={()=>void loadCandidate()}>载入当前授权候选</button>
    <label>完整修订候选 JSON<textarea aria-label="完整修订候选" rows={10} value={candidate} onChange={event => setCandidate(event.target.value)} /></label>
    <label>修订理由<textarea aria-label="修订理由" value={reason} onChange={event => setReason(event.target.value)} /></label>
    <button className="button" disabled={command.pending || !unit || !verifier || !reason.trim()} onClick={() => void propose()}>提交候选并等待独立复验</button>
    <ErrorNotice error={imports.error ?? detail.error ?? users.error ?? command.error} />{command.success && <p role="status">{command.success}</p>}
  </Panel>;
}

export function V13Governance({ user }: { user: User }) {
  const readIssues = user.roles.some(role => ["lead", "auditor", "annotator"].includes(role));
  const readRevisions = user.roles.some(role => ["lead", "auditor", "arbitrator", "verifier"].includes(role));
  const issues = useQuery({ queryKey: ["v13", "issues"], queryFn: ({ signal }) => listV2<Issue>("/issues", signal), enabled: readIssues });
  const revisions = useQuery({ queryKey: ["v13", "revisions"], queryFn: ({ signal }) => listV2<Revision>("/revisions", signal), enabled: readRevisions });
  return <><PageHeader title="新版材料与独立复验" description="材料问题暂停相关任务；实质修订生成新版本，独立复验后才计最终核实。" />
    {readIssues && <QueryState pending={issues.isPending} error={issues.error}>{issues.data?.items.length ? issues.data.items.map(issue => <IssueCard key={issue.id} issue={issue} canResolve={user.roles.includes("lead")} />) : <Panel title="材料问题"><Empty title="当前没有可见材料问题" /></Panel>}</QueryState>}
    {user.roles.includes("lead") && <RevisionProposal currentUserId={user.id}/>}
    {readRevisions && <QueryState pending={revisions.isPending} error={revisions.error}>{revisions.data?.items.length ? revisions.data.items.map(revision => <RevisionCard key={revision.id} revision={revision} canVerify={user.roles.includes("verifier")&&revision.verifier_id===user.id} />) : <Panel title="修订复验"><Empty title="当前没有可见修订" /></Panel>}</QueryState>}
  </>;
}

export function BatchMaintenance({ batch }: { batch: V13Batch }) {
  const users = useList<User>("/users");
  const eligible = users.data?.items.filter(user => user.active && user.roles.includes("annotator") && !user.roles.includes("admin")) ?? [];
  const [assignment, setAssignment] = useState("");
  const [replacement, setReplacement] = useState("");
  const [replaceReason, setReplaceReason] = useState("");
  const [reason, setReason] = useState("");
  const [a, setA] = useState(""); const [b, setB] = useState("");
  const [assignees, setAssignees] = useState<string[]>([]);
  const [newId, setNewId] = useState("");
  const [expansionA,setExpansionA]=useState("");const [expansionB,setExpansionB]=useState("");
  const [expandedCount,setExpandedCount]=useState(batch.selected_ids.length+1);
  const [seed,setSeed]=useState(20261030);
  const command = useV13Command();
  const blind = batch.assignments?.filter(row => row.phase === "BLIND") ?? [];
  const closed = ["SUPERSEDED", "CANCELLED", "RETURNED_TO_S2", "OBSERVED"].includes(batch.state);
  const options = eligible.map(user => <option key={user.id} value={user.id}>{user.display_name} · {user.person_id}</option>);
  async function newRound() {
    const result = await command.run(`/batches/${batch.id}/new-round`, { reason, ...(batch.workflow_kind === "OBSERVATION" ? { annotator_a: a, annotator_b: b } : { assignee_ids: assignees }) });
    if (typeof result?.id === "string") setNewId(result.id);
  }
  async function expand() {
    const result=await command.run("/observation-batches",{import_id:batch.import_id,dataset:batch.dataset,annotator_a:expansionA,annotator_b:expansionB,parent_id:batch.id,expanded_count:expandedCount,seed,manual_version:batch.manual_version??"manual-v1.3",profile_version:batch.profile_version??"s4-v1.3"});
    if(typeof result?.id==="string")setNewId(result.id);
  }
  return <Panel title="离场补派与新轮">
    <p>未见草案时主核实逐任务补派、观测整席补派；已见草案后使用未暴露人员按完整范围新开一轮。原分配及封存留存。</p>
    {!closed && !!blind.length && <details><summary>独立阶段补派</summary>
      <label>原分配<select aria-label="补派原分配" value={assignment} onChange={event => setAssignment(event.target.value)}><option value="">请选择原分配</option>{blind.map(row => <option key={row.id} value={row.id}>{row.seat} · {row.unit_index_id} · {row.user_id}</option>)}</select></label>
      <label>替补人员<select aria-label="替补人员" value={replacement} onChange={event => setReplacement(event.target.value)}><option value="">请选择未暴露人员</option>{options}</select></label>
      <label>补派理由<textarea aria-label="补派理由" value={replaceReason} onChange={event => setReplaceReason(event.target.value)} /></label>
      <button className="button" disabled={command.pending || !assignment || !replacement || !replaceReason.trim()} onClick={() => void command.run(`/assignments/${assignment}/replace`, { user_id: replacement, reason: replaceReason })}>{batch.workflow_kind === "OBSERVATION" ? "补派整个观测席位" : "补派主核实任务"}</button>
    </details>}
    {!closed && <details open><summary>草案比对阶段完整新轮</summary>
      {batch.workflow_kind === "OBSERVATION" ? <div className="v13-plan-grid">
        <label>新轮观测员A<select aria-label="新轮观测员A" value={a} onChange={event => setA(event.target.value)}><option value="">请选择未暴露人员</option>{options}</select></label>
        <label>新轮观测员B<select aria-label="新轮观测员B" value={b} onChange={event => setB(event.target.value)}><option value="">请选择未暴露人员</option>{options}</select></label>
      </div> : <fieldset><legend>新轮主核实人员</legend>{eligible.map(user => <label key={user.id}><input type="checkbox" checked={assignees.includes(user.id)} onChange={event => setAssignees(event.target.checked ? [...assignees, user.id] : assignees.filter(id => id !== user.id))} />{user.display_name} · {user.person_id}</label>)}</fieldset>}
      <label>新轮原因<textarea aria-label="新轮原因" value={reason} onChange={event => setReason(event.target.value)} /></label>
      <button className="button" disabled={command.pending || !reason.trim() || (batch.workflow_kind === "OBSERVATION" ? !a || !b || a === b : !assignees.length)} onClick={() => void newRound()}>保留原轮并启动完整新轮</button>
    </details>}
    {closed && <p className="muted">本轮已关闭，不能补派或复用原失败批。</p>}
    {batch.workflow_kind==="OBSERVATION"&&batch.quality&&batch.state==="OBSERVED"&&batch.quality.action!=="RETURN_TO_S2"&&<details open><summary>质量扩样：另起观测范围与原报告关联</summary>
      <p>扩样保留原始κ，原范围不会覆盖。新任务需独立未暴露人员；扩样不替代全量核实或正式出口规则确认。</p>
      <div className="v13-plan-grid"><label>扩样观测员A<select aria-label="扩样观测员A" value={expansionA} onChange={event=>setExpansionA(event.target.value)}><option value="">请选择未暴露人员</option>{options}</select></label><label>扩样观测员B<select aria-label="扩样观测员B" value={expansionB} onChange={event=>setExpansionB(event.target.value)}><option value="">请选择未暴露人员</option>{options}</select></label></div>
      <label>扩样单元数量<input aria-label="扩样单元数量" type="number" min={batch.selected_ids.length+1} value={expandedCount} onChange={event=>setExpandedCount(Number(event.target.value))}/></label>
      <label>扩样随机种子<input aria-label="扩样随机种子" type="number" value={seed} onChange={event=>setSeed(Number(event.target.value))}/></label>
      <button className="button" disabled={command.pending||!expansionA||!expansionB||expansionA===expansionB||!Number.isInteger(expandedCount)||expandedCount<=batch.selected_ids.length} onClick={()=>void expand()}>冻结扩样范围并分配独立人员</button>
    </details>}
    {newId && <Link to={`/v13/batches/${newId}`}>进入新轮</Link>}
    <ErrorNotice error={users.error ?? command.error} />{command.success && <p role="status">{command.success}</p>}
  </Panel>;
}
