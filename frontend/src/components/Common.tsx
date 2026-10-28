import type { ReactNode } from "react";
import {
  AlertCircle,
  ArrowRight,
  Inbox,
  LoaderCircle,
  RefreshCw,
} from "lucide-react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import type { Job } from "../types";
import { ImportValidationReport } from "./ImportValidationReport";
import type { ValidationReport } from "./ImportValidationReport";

const names: Record<string, string> = {
  IMPORTED: "已导入",
  PLANNED: "已规划",
  BLIND_OPEN: "独立作答中",
  BLIND_SEALED: "独立作答已封存",
  REVIEW_OPEN: "三栏复核中",
  PAIR_COMPLETE: "双方已齐备",
  S4_READY: "S4就绪",
  ACCEPT: "通过",
  ARBITRATE: "待仲裁",
  REJECT_BATCH: "整批重标",
  BLOCKED: "已阻塞",
  DEMO_READY: "演示快照就绪",
  READY: "已就绪",
  DONE: "已完成",
  PENDING: "待处理",
  RUNNING: "处理中",
  FAILED: "失败",
  SUBMITTED: "已封存",
  COMPLETED: "已完成",
  BLIND: "独立作答",
  REVIEW: "三栏复核",
  NOT_ALIGNED: "外部未对齐",
  ACTIVE: "进行中",
  CLOSED: "已关闭",
  CANCELLED: "已终止",
  demo: "演示",
  formal: "正式",
};
export function Badge({ value, label }: { value: string; label?: string }) {
  const state = value.toUpperCase();
  const tone = [
    "ACCEPT",
    "DONE",
    "COMPLETED",
    "READY",
    "S4_READY",
    "SUBMITTED",
  ].includes(state)
    ? "good"
    : ["FAILED", "BLOCKED", "REJECT_BATCH", "S5_REJECTED"].includes(state)
      ? "bad"
      : ["ARBITRATE", "DEMO_READY", "NOT_ALIGNED"].includes(state)
        ? "warm"
        : "neutral";
  return (
    <span className={`badge ${tone}`}>
      <span />
      {label ?? names[value] ?? names[state] ?? value}
    </span>
  );
}
export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-header">
      <div>
        <div className="section-eyebrow">{eyebrow ?? "S4 WORKSPACE"}</div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}
export function Panel({
  title,
  description,
  children,
  action,
  className = "",
}: {
  title?: string;
  description?: string;
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      {(title || action) && (
        <div className="panel-heading">
          <div>
            <h2>{title}</h2>
            {description && <p className="muted">{description}</p>}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}
export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <div className="notice danger" role="alert">
      <AlertCircle size={18} />
      <div>
        {error instanceof Error ? error.message : "操作失败，请重试。"}
        {error instanceof ApiError && error.requestId && (
          <span className="request-id">请求标识 {error.requestId}</span>
        )}
      </div>
    </div>
  );
}
export function Empty({
  title = "暂无记录",
  description = "记录产生后会显示在这里。",
  action,
}: {
  title?: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Inbox size={26} strokeWidth={1.5} />
      </div>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}
export function Loading({ label = "正在读取…" }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <LoaderCircle className="spin" size={20} />
      {label}
    </div>
  );
}
export function QueryState({
  pending,
  error,
  children,
}: {
  pending: boolean;
  error: unknown;
  children: ReactNode;
}) {
  return pending ? (
    <Loading />
  ) : error ? (
    <ErrorNotice error={error} />
  ) : (
    children
  );
}
export function RefreshButton({ onClick }: { onClick: () => void }) {
  return (
    <button className="button small" onClick={onClick}>
      <RefreshCw size={14} />
      刷新
    </button>
  );
}
export function PageLink({
  to,
  children,
}: {
  to: string;
  children: ReactNode;
}) {
  return (
    <Link className="text-link" to={to}>
      {children}
      <ArrowRight size={14} />
    </Link>
  );
}
export function BlockedReasons({ reasons }: { reasons?: string[] }) {
  return reasons?.length ? (
    <div className="notice warning">
      <AlertCircle size={18} />
      <div>
        <strong>当前阻塞事项</strong>
        <ul>
          {reasons.map((reason, index) => (
            <li key={`${reason}-${index}`}>{reason}</li>
          ))}
        </ul>
      </div>
    </div>
  ) : null;
}
export function JobProgress({
  id,
  onComplete,
}: {
  id: string;
  onComplete?: () => void;
}) {
  const query = useQuery({
    queryKey: ["job", id],
    queryFn: () => api<Job>(`/jobs/${id}`),
    refetchInterval: (data) => {
      const state = data.state.data?.state?.toUpperCase();
      return state && ["DONE", "SUCCEEDED", "FAILED"].includes(state)
        ? false
        : 1500;
    },
  });
  const job = query.data;
  const finished = ["DONE", "SUCCEEDED"].includes(
    job?.state?.toUpperCase() ?? "",
  );
  return (
    <div
      className={`notice ${finished ? "success" : job?.state?.toUpperCase() === "FAILED" ? "danger" : "info"}`}
      role="status"
    >
      <div>
        <strong>后台任务</strong> <span className="mono tiny">{id}</span>
        {query.isPending && <Loading />}
        {query.error && <ErrorNotice error={query.error} />}
        {job && (
          <div className="job-state">
            <Badge value={job.state} /> <span>已尝试 {job.attempts} 次</span>
            {job.error_message && <p>{job.error_message}</p>}
            {finished && (
              <button className="text-button" onClick={onComplete}>
                刷新业务记录
              </button>
            )}
          </div>
        )}
        {!!job?.result?.validation_report && (
          <ImportValidationReport
            report={job.result.validation_report as ValidationReport}
          />
        )}
      </div>
    </div>
  );
}
