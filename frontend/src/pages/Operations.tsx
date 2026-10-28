import { OperationsPanel, HandoffSending } from "./CompletionOperations";

import { formatTime, safeText } from "../format";

import { useState } from "react";

import { Link, useParams } from "react-router-dom";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  Activity,
  ArrowLeft,
  Download,
  FileOutput,
  ShieldCheck,
} from "lucide-react";

import { api, API_ROOT } from "../api";

import { useCommand, useList } from "../hooks";

import type { AuditEvent, Handoff, Health, ImportRecord } from "../types";

import {
  Badge,
  BlockedReasons,
  Empty,
  ErrorNotice,
  JobProgress,
  PageHeader,
  PageLink,
  Panel,
  QueryState,
  RefreshButton,
} from "../components/Common";

export function HandoffsPage({ canWrite }: { canWrite: boolean }) {
  const query = useList<Handoff>("/handoffs");
  const imports = useList<ImportRecord>("/imports", canWrite);
  const command = useCommand();
  const client = useQueryClient();
  const [importId, setImportId] = useState("");
  const [jobId, setJobId] = useState("");

  return (
    <>
      <PageHeader
        eyebrow="SNAPSHOT & HANDOFF"
        title="导出与交接"
        description="全量N与抽检n分别交付；文件摘要核对后发布只读快照，实际接收状态依赖真实回执。"
        action={<RefreshButton onClick={() => void query.refetch()} />}
      />
      <div className="notice warning">
        <ShieldCheck size={19} />
        <div>
          <strong>外部契约待对齐</strong>
          <p>
            S4就绪、交接发布与S5接收分别记录。演示快照与本地接收桩不构成正式接收证据。
          </p>
        </div>
      </div>
      {canWrite && (
        <Panel
          title="发布交接快照"
          description="全部数据集的当前批次通过质量门并完成最终内容确认后，才能发布对应模式快照。"
        >
          <form
            className="inline-form"
            onSubmit={async (event) => {
              event.preventDefault();
              const result = await command.run<{ job_id: string }>(
                "/handoffs",
                { import_id: importId },
              );
              if (result) setJobId(result.job_id);
            }}
          >
            <label>
              来源批次
              <select
                value={importId}
                required
                onChange={(event) => setImportId(event.target.value)}
              >
                <option value="">选择已完成的来源批次</option>
                {imports.data?.items.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.batch_id} · {item.mode} · {item.unit_count}单元
                  </option>
                ))}
              </select>
            </label>
            <button
              className="button primary"
              disabled={command.pending || !importId}
            >
              <FileOutput size={17} />
              创建交接快照
            </button>
          </form>
          <ErrorNotice error={imports.error ?? command.error} />
        </Panel>
      )}
      {jobId && (
        <JobProgress
          id={jobId}
          onComplete={() => void client.invalidateQueries()}
        />
      )}
      <Panel title="交接记录">
        <QueryState pending={query.isPending} error={query.error}>
          {query.data?.items.length ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>交接标识</th>
                    <th>模式</th>
                    <th>快照状态</th>
                    <th>外部状态</th>
                    <th>发布时间</th>
                    <th>结果</th>
                  </tr>
                </thead>
                <tbody>
                  {query.data.items.map((item) => (
                    <tr key={item.id}>
                      <td className="mono tiny">{item.id}</td>
                      <td>
                        <Badge value={item.mode} />
                      </td>
                      <td>
                        <Badge value={item.status} />
                      </td>
                      <td>
                        <Badge value={item.external_status} />
                      </td>
                      <td>{formatTime(item.created_at)}</td>
                      <td>
                        <PageLink to={`/handoffs/${item.id}`}>
                          清单与文件
                        </PageLink>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty
              title="尚未发布交接快照"
              description="后台核对全量、抽检和统计记录后，发布结果将展示在这里。"
            />
          )}
        </QueryState>
      </Panel>
    </>
  );
}

export function HandoffPage() {
  const { id } = useParams();
  const query = useQuery({
    queryKey: [`/handoffs/${id}`],
    queryFn: () => api<Handoff>(`/handoffs/${id}`),
  });
  const item = query.data;
  const files = item?.manifest?.files;

  const entries = Array.isArray(files)
    ? files.map((file) => ({ name: file.name ?? file.filename ?? "", ...file }))
    : files && typeof files === "object"
      ? Object.entries(files).map(([name, value]) => ({
          name,
          ...(typeof value === "object" && value ? value : {}),
        }))
      : [];

  return (
    <>
      <Link className="back-link" to="/handoffs">
        <ArrowLeft size={16} />
        返回交接记录
      </Link>
      <PageHeader
        eyebrow="IMMUTABLE SNAPSHOT"
        title="交接清单与受控文件"
        description={id ?? ""}
        action={<RefreshButton onClick={() => void query.refetch()} />}
      />
      <QueryState pending={query.isPending} error={query.error}>
        {item && (
          <>
            <div className="action-bar">
              <Badge value={item.mode} />
              <Badge value={item.status} />
              <Badge value={item.external_status} />
              <span className="muted">
                发布于 {formatTime(item.created_at)}
              </span>
            </div>
            <BlockedReasons reasons={item.blocked_reasons} />
            <Panel
              title="六文件结果包"
              description="下载时服务端重新验证快照摘要和访问权限。"
            >
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>文件</th>
                      <th>记录数</th>
                      <th>SHA-256</th>
                      <th>获取</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entries.map((file) => (
                      <tr key={file.name}>
                        <td className="mono">{file.name}</td>
                        <td>
                          {"line_count" in file
                            ? String(file.line_count)
                            : "rows" in file
                              ? String(file.rows)
                              : "—"}
                        </td>
                        <td className="mono tiny hash-cell">
                          {"sha256" in file ? String(file.sha256) : "—"}
                        </td>
                        <td>
                          <a
                            className="text-link"
                            href={`${API_ROOT}/handoffs/${encodeURIComponent(item.id)}/files/${encodeURIComponent(file.name)}`}
                            download
                          >
                            <Download size={15} />
                            下载文件
                          </a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!entries.length && <Empty title="尚无可下载清单" />}
              <a
                className="button small manifest-download"
                href={`${API_ROOT}/handoffs/${encodeURIComponent(item.id)}/files/s4_handoff_manifest.json`}
                download
              >
                <Download size={15} />
                下载交接manifest
              </a>
            </Panel>
            <HandoffSending
              id={item.id}
              snapshotHash={
                item.snapshot_hash ?? String(item.manifest?.snapshot_hash ?? "")
              }
            />
            <Panel title="冻结清单详情">
              <pre className="source-text">{safeText(item.manifest)}</pre>
            </Panel>
          </>
        )}
      </QueryState>
    </>
  );
}

export function AuditPage() {
  const [offset, setOffset] = useState(0);
  const query = useList<AuditEvent>(`/audit?offset=${offset}&limit=100`);

  return (
    <>
      <PageHeader
        eyebrow="APPEND-ONLY AUDIT TRAIL"
        title="审计记录"
        description="查看权限访问、封存提交、阶段推进与快照下载记录。敏感材料不写入普通日志。"
        action={<RefreshButton onClick={() => void query.refetch()} />}
      />
      <Panel
        title="操作轨迹"
        description="服务端追加记录，界面以Asia/Shanghai显示时间。"
      >
        <QueryState pending={query.isPending} error={query.error}>
          {query.data?.items.length ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>动作 / 对象</th>
                    <th>操作者</th>
                    <th>请求标识</th>
                    <th>详情</th>
                  </tr>
                </thead>
                <tbody>
                  {query.data.items.map((item) => (
                    <tr key={item.id}>
                      <td className="nowrap">{formatTime(item.created_at)}</td>
                      <td>
                        <strong>{item.action}</strong>
                        <div className="tiny mono muted">
                          {item.object_id ?? "—"}
                        </div>
                      </td>
                      <td className="tiny mono">
                        {item.actor_id ?? "未认证 / 系统"}
                      </td>
                      <td className="tiny mono">{item.request_id ?? "—"}</td>
                      <td>
                        <details>
                          <summary>查看记录</summary>
                          <pre className="source-text">
                            {safeText(item.details)}
                          </pre>
                        </details>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty title="该页没有审计记录" />
          )}
        </QueryState>
        <div className="pagination">
          <button
            className="button small"
            disabled={offset === 0 || query.isPending}
            onClick={() => setOffset(Math.max(0, offset - 100))}
          >
            上一页
          </button>
          <span className="muted tiny">
            第 {offset / 100 + 1} 页 · 每页100条
          </span>
          <button
            className="button small"
            disabled={query.isPending || (query.data?.items.length ?? 0) < 100}
            onClick={() => setOffset(offset + 100)}
          >
            下一页
          </button>
        </div>
      </Panel>
    </>
  );
}

async function readHealth(path: string): Promise<Health> {
  const response = await fetch(`${API_ROOT}${path}`, {
    credentials: "include",
    cache: "no-store",
    headers: { Accept: "application/json" },
  });

  const data = (await response.json()) as Health;

  if (!response.ok && response.status !== 503)
    throw new Error(`健康检查未完成（${response.status}）`);

  return data;
}

export function HealthPage() {
  const live = useQuery({
    queryKey: ["/health/live"],
    queryFn: () => readHealth("/health/live"),
    refetchInterval: 15000,
  });
  const ready = useQuery({
    queryKey: ["/health/ready"],
    queryFn: () => readHealth("/health/ready"),
    refetchInterval: 15000,
  });

  const checks = [
    {
      title: "API存活",
      good: live.data?.status === "alive",
      value: live.data?.status,
      text: "HTTP服务进程",
    },
    {
      title: "数据库",
      good: ready.data?.database === true,
      value: ready.data ? (ready.data.database ? "已连接" : "不可用") : "",
      text: "数据库连接与迁移版本",
    },
    {
      title: "Worker",
      good: ready.data?.worker === true,
      value: ready.data ? (ready.data.worker ? "心跳正常" : "心跳失效") : "",
      text: "90秒内的持久工作进程心跳",
    },
  ];

  return (
    <>
      <PageHeader
        eyebrow="SYSTEM HEALTH"
        title="系统健康"
        description="分别检查服务存活、数据库迁移与worker就绪状态；后台任务依赖独立worker。"
        action={
          <RefreshButton
            onClick={() => {
              void live.refetch();
              void ready.refetch();
            }}
          />
        }
      />
      <ErrorNotice error={live.error ?? ready.error} />
      <div className="stats-grid health-grid">
        {checks.map((check) => (
          <div className="stat-card" key={check.title}>
            <div>
              <span>{check.title}</span>
              <Activity size={19} />
            </div>
            <Badge
              value={
                !check.value ? "PENDING" : check.good ? "READY" : "BLOCKED"
              }
              label={check.value ? String(check.value) : "读取中"}
            />
            <p>{check.text}</p>
          </div>
        ))}
      </div>
      <OperationsPanel />
      <Panel title="就绪诊断">
        <QueryState pending={ready.isPending} error={ready.error}>
          <dl className="health-details">
            <div>
              <dt>综合就绪</dt>
              <dd>
                <Badge
                  value={ready.data?.status === "ready" ? "READY" : "BLOCKED"}
                  label={ready.data?.status ?? "未知"}
                />
              </dd>
            </div>
            <div>
              <dt>迁移版本</dt>
              <dd className="mono">{String(ready.data?.migration ?? "—")}</dd>
            </div>
            <div>
              <dt>外部契约</dt>
              <dd>
                <Badge
                  value={String(
                    ready.data?.external_alignment ?? "NOT_ALIGNED",
                  )}
                />
              </dd>
            </div>
            <div>
              <dt>最近检查</dt>
              <dd>
                {ready.dataUpdatedAt
                  ? formatTime(new Date(ready.dataUpdatedAt).toISOString())
                  : "—"}
              </dd>
            </div>
          </dl>
        </QueryState>
      </Panel>
    </>
  );
}
