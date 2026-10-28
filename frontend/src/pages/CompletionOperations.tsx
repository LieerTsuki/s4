import { useState } from "react";
import type { components } from "../generated/openapi";
import { useQuery } from "@tanstack/react-query";
import { api, API_ROOT } from "../api";
import { useCommand, useList } from "../hooks";
import { formatTime, safeText } from "../format";
import {
  Badge,
  ErrorNotice,
  JobProgress,
  Panel,
  QueryState,
} from "../components/Common";
interface Notification {
  id: string;
  kind: string;
  payload: Record<string, unknown>;
  created_at: string;
  read_at: string | null;
}
interface Run {
  id: string;
  state: string;
  created_at: string;
  summary?: unknown;
}
interface Finding {
  id: string;
  kind: string;
  severity: string;
  status: string;
  details: unknown;
  object_id: string;
}
function Findings({ id }: { id: string }) {
  const [offset, setOffset] = useState(0);
  const query = useList<Finding>(
    `/reconciliations/${id}/findings?offset=${offset}&limit=50`,
  );
  return (
    <>
      <QueryState pending={query.isPending} error={query.error}>
        {query.data?.items?.map((item) => (
          <div className="label-card" key={item.id}>
            <strong>{item.kind}</strong>
            <Badge value={item.status} />
            <p>
              {item.severity} · {item.object_id}
            </p>
            <pre>{safeText(item.details)}</pre>
          </div>
        ))}
      </QueryState>
      <Pager
        offset={offset}
        setOffset={setOffset}
        total={query.data?.total ?? 0}
      />
    </>
  );
}
export function Pager({
  offset,
  setOffset,
  total,
}: {
  offset: number;
  setOffset: (v: number) => void;
  total: number;
}) {
  return (
    <div className="pagination">
      <button
        className="button small"
        disabled={offset === 0}
        onClick={() => setOffset(Math.max(0, offset - 50))}
      >
        上一页
      </button>
      <span className="muted">
        共{total}条 · 第{Math.floor(offset / 50) + 1}页
      </span>
      <button
        className="button small"
        disabled={offset + 50 >= total}
        onClick={() => setOffset(offset + 50)}
      >
        下一页
      </button>
    </div>
  );
}
export function OperationsPanel() {
  const metrics = useQuery({
    queryKey: ["/operations"],
    queryFn: () => api<Record<string, unknown>>("/operations"),
    refetchInterval: 15000,
  });
  const [offset, setOffset] = useState(0);
  const runs = useList<Run>(`/reconciliations?offset=${offset}&limit=50`);
  const [job, setJob] = useState("");
  const command = useCommand();
  return (
    <Panel
      title="运维指标与业务对账"
      description="核对有效分配、提交、磁盘manifest、孤立目录与缺回执；异常留工单，不自动制造接收。"
      action={
        <button
          className="button"
          disabled={command.pending}
          onClick={async () => {
            const result = await command.run<{ job_id: string }>(
              "/reconciliations",
            );
            if (result) setJob(result.job_id);
          }}
        >
          运行对账
        </button>
      }
    >
      <ErrorNotice error={command.error} />
      <QueryState pending={metrics.isPending} error={metrics.error}>
        <pre className="source-text">{safeText(metrics.data)}</pre>
      </QueryState>
      {job && <JobProgress id={job} />}
      <QueryState pending={runs.isPending} error={runs.error}>
        {runs.data?.items?.map((run) => (
          <details className="decision-card" key={run.id}>
            <summary>
              {formatTime(run.created_at)} · {run.state} · {run.id}
            </summary>
            <div className="decision-content">
              <pre>{safeText(run.summary)}</pre>
              <Findings id={run.id} />
            </div>
          </details>
        ))}
      </QueryState>
      <Pager
        offset={offset}
        setOffset={setOffset}
        total={runs.data?.total ?? 0}
      />
    </Panel>
  );
}
export function NotificationsPage() {
  const [offset, setOffset] = useState(0);
  const query = useList<Notification>(
    `/notifications?offset=${offset}&limit=50`,
  );
  const command = useCommand();
  return (
    <Panel
      title="我的站内提醒"
      description="仅显示本人到期任务与服务端授权提醒；不通过邮件或群消息发送。"
    >
      <ErrorNotice error={command.error} />
      <QueryState pending={query.isPending} error={query.error}>
        {query.data?.items?.length ? (
          query.data.items.map((item) => (
            <article className="label-card" key={item.id}>
              <strong>{item.kind}</strong>
              <p className="muted">{formatTime(item.created_at)}</p>
              <pre>{safeText(item.payload)}</pre>
              {item.read_at ? (
                <Badge value="READY" label="已读" />
              ) : (
                <button
                  className="button small"
                  disabled={command.pending}
                  onClick={() =>
                    void command.run(`/notifications/${item.id}/read`)
                  }
                >
                  标为已读
                </button>
              )}
            </article>
          ))
        ) : (
          <p className="muted">暂无本人提醒。</p>
        )}
      </QueryState>
      <Pager
        offset={offset}
        setOffset={setOffset}
        total={query.data?.total ?? 0}
      />
    </Panel>
  );
}
export function HandoffSending({
  id,
  snapshotHash,
}: {
  id: string;
  snapshotHash?: string;
}) {
  const command = useCommand();
  const [hash, setHash] = useState(snapshotHash ?? "");
  const [destination, setDestination] = useState("");
  const [kind, setKind] =
    useState<components["schemas"]["DeliveryEvidence"]["kind"]>(
      "manual_delivery",
    );
  const [reference, setReference] = useState("");
  const [evidenceHash, setEvidenceHash] = useState("");
  const [key] = useState(() => crypto.randomUUID());
  return (
    <Panel
      title="发送与复算证据"
      description="下载不计作发送；实际交付后登记证据。演示交付不会变成正式S5接收。"
    >
      <a
        className="button"
        href={`${API_ROOT}/handoffs/${encodeURIComponent(id)}/evidence`}
        download
      >
        下载受控原始复算资料
      </a>
      <form
        className="form-grid"
        onSubmit={async (e) => {
          e.preventDefault();
          const body: components["schemas"]["SentInput"] = {
            snapshot_hash: hash,
            destination_ref: destination,
            evidence: { kind, reference, sha256: evidenceHash },
            idempotency_key: key,
          };
          const result = await command.run(`/handoffs/${id}/sent`, body);
          if (result)
            command.setSuccess("发送事件已登记。S5是否接收仍以独立回执为准。");
        }}
      >
        <label>
          冻结快照SHA-256
          <input
            required
            pattern="[0-9a-f]{64}"
            value={hash}
            onChange={(e) => setHash(e.target.value)}
          />
        </label>
        <label>
          接收方引用
          <input
            required
            value={destination}
            placeholder="manual:接收人引用 或 receiver:受控接收方"
            onChange={(e) => setDestination(e.target.value)}
          />
        </label>
        <label>
          交付证据类型
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as typeof kind)}
          >
            <option value="manual_delivery">人工交付证据</option>
            <option value="controlled_transfer">受控传输证据</option>
          </select>
        </label>
        <label>
          实际交付证据引用
          <input
            required
            value={reference}
            placeholder="evidence:证据标识"
            onChange={(e) => setReference(e.target.value)}
          />
        </label>
        <label className="span-all">
          交付证据SHA-256
          <input
            required
            pattern="[0-9a-f]{64}"
            value={evidenceHash}
            onChange={(e) => setEvidenceHash(e.target.value)}
          />
        </label>
        <button className="button primary" disabled={command.pending}>
          登记已发送证据
        </button>
      </form>
      <ErrorNotice error={command.error} />
      {command.success && (
        <div role="status" className="notice success">
          {command.success}
        </div>
      )}
    </Panel>
  );
}
