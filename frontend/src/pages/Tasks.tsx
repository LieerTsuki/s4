import { safeText } from "../format";

import { useState } from "react";

import { Link, useParams } from "react-router-dom";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { ArrowLeft, LockKeyhole } from "lucide-react";

import { api } from "../api";

import { useList } from "../hooks";

import type { ReviewPayload, Task, TaskDetail } from "../types";

import {
  Badge,
  Empty,
  PageHeader,
  PageLink,
  Panel,
  QueryState,
  RefreshButton,
} from "../components/Common";

import { BlindForm } from "../components/BlindForm";

import { ReviewForm } from "../components/ReviewForm";

import { MaterialIssueForm } from "../components/MaterialIssueForm";

import { SpecializedForm } from "../components/SpecializedReview";
import { SpecializedMaterials } from "../components/SpecializedMaterials";

import { SourceDocument } from "../components/SourceDocument";

export function TasksPage() {
  const query = useList<Task>("/me/tasks");
  const [filter, setFilter] = useState("all");

  const items = (query.data?.items ?? []).filter(
    (task) =>
      filter === "all" ||
      (filter === "pending" ? task.status !== "SEALED" : task.phase === filter),
  );

  return (
    <>
      <PageHeader
        eyebrow="MY ASSIGNMENTS"
        title="我的标注任务"
        description="这里仅展示你自己的任务。先独立判断，再复核草案；正式提交后保留不可变快照。"
        action={<RefreshButton onClick={() => void query.refetch()} />}
      />
      <div className="filter-tabs">
        {[
          ["all", "全部任务"],
          ["pending", "待我处理"],
          ["BLIND", "独立作答"],
          ["REVIEW", "三栏复核"],
        ].map(([value, label]) => (
          <button
            key={value}
            className={filter === value ? "active" : ""}
            onClick={() => setFilter(value)}
          >
            {label}
          </button>
        ))}
      </div>
      <Panel>
        <QueryState pending={query.isPending} error={query.error}>
          {items.length ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>评测单元</th>
                    <th>数据集</th>
                    <th>当前阶段</th>
                    <th>我的状态</th>
                    <th>规则版本</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((task) => (
                    <tr key={task.id}>
                      <td>
                        <strong className="mono">{task.unit_id}</strong>
                        <div className="tiny muted mono">{task.batch_id}</div>
                      </td>
                      <td>
                        <span className="dataset-chip">{task.dataset}</span>
                      </td>
                      <td>
                        <Badge value={task.phase} />
                      </td>
                      <td>
                        <Badge
                          value={task.status}
                          label={
                            task.status === "SEALED" ? "本人已封存" : "待我处理"
                          }
                        />
                      </td>
                      <td className="mono tiny">{task.profile_version}</td>
                      <td>
                        <PageLink to={`/tasks/${task.id}`}>
                          {task.status === "SEALED"
                            ? "查看本人记录"
                            : "进入作业"}
                        </PageLink>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty
              title="当前筛选下没有任务"
              description="已分配任务将按服务端阶段和本人状态展示。"
            />
          )}
        </QueryState>
      </Panel>
    </>
  );
}

export function TaskWorkspace({ task }: { task: TaskDetail }) {
  const client = useQueryClient();
  const [version, setVersion] = useState(task.draft?.version ?? 0);

  const [idempotencyKey] = useState(() => crypto.randomUUID());

  const legacy =
    task.review_version === "openkb.s4-review.v1" ||
    (task.phase === "REVIEW" &&
      !!task.own_submission &&
      task.own_submission.review_version !== "openkb.s4-review.v2");
  const disabled = task.status === "SEALED" || legacy || task.paused === true;
  const specialized =
    task.dataset.startsWith("SEC") || task.dataset === "QA-D6";

  const initial = task.own_submission ?? task.draft?.payload ?? {};

  async function save(
    payload:
      | Record<string, unknown>
      | ReviewPayload
      | { answer: string; reason: string },
  ) {
    const result = await api<{ version: number }>(
      `/assignments/${task.id}/draft`,
      { method: "PATCH", body: { phase: task.phase, version, payload } },
    );
    setVersion(result.version);
    await client.invalidateQueries({ queryKey: [`/assignments/${task.id}`] });
  }

  async function submit(
    payload:
      | Record<string, unknown>
      | ReviewPayload
      | { answer: string; reason: string },
  ) {
    await api(`/assignments/${task.id}/submit`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: {
        phase: task.phase,
        content_revision: task.content_revision,
        profile_version: task.profile_version,
        profile_hash: task.profile_hash,
        payload,
      },
    });
    await client.invalidateQueries();
  }

  return (
    <>
      <div className="task-meta">
        <span className="dataset-chip">{task.dataset}</span>
        <span className="mono">{task.unit_id}</span>
        <Badge value={task.phase} />
        <Badge
          value={task.status}
          label={
            task.paused ? "批次已暂停" : disabled ? "本人已封存" : "待本人处理"
          }
        />
        <span className="muted tiny">
          规则 {task.profile_version} · 草稿版本 {version}
        </span>
      </div>

      {task.paused && (
        <div className="notice warning">
          批次已暂停，请等待材料问题或版本处置完成。
        </div>
      )}
      {legacy && (
        <div className="notice warning">
          legacy v1记录仅供只读核对，不补造v2理由。升级须由运营登记新轮。
        </div>
      )}
      <MaterialIssueForm
        assignmentId={task.id}
        contexts={task.material.contexts}
      />
      {disabled && (
        <div className="notice success">
          <LockKeyhole size={19} />
          <div>
            <strong>本阶段记录已封存</strong>
            <p>
              原始提交不可覆盖。若仍处于独立作答阶段，请等待运营统一开放复核。
            </p>
          </div>
        </div>
      )}

      {task.phase === "REVIEW" && (
        <SpecializedMaterials
          dataset={task.dataset}
          metadata={task.material.metadata}
        />
      )}
      <Panel title={specialized ? "待审核材料" : "题目与阅读范围"}>
        <h2 className="task-question">
          {task.material.question ??
            (task.dataset === "QA-D6" ? "分块质量审核" : "安全行为材料审核")}
        </h2>
        {task.material.payload !== undefined && (
          <pre className="payload-text">{safeText(task.material.payload)}</pre>
        )}
        {task.material.acl_context != null && (
          <div className="context-meta">
            <strong>权限背景</strong>
            <pre>{safeText(task.material.acl_context)}</pre>
          </div>
        )}
        {task.material.time_context != null && (
          <div className="context-meta">
            <strong>时效背景</strong>
            <pre>{safeText(task.material.time_context)}</pre>
          </div>
        )}
        {(
          ["access_context", "chunk", "inject_plan", "quality_metrics"] as const
        ).map((key) =>
          task.material[key] != null &&
          (key !== "quality_metrics" || task.phase === "REVIEW") ? (
            <div className="context-meta" key={key}>
              <strong>
                {
                  {
                    access_context: "权限与访问范围",
                    chunk: "分块材料",
                    inject_plan: "注入计划（仅静态阅读）",
                    quality_metrics: "质量指标草案",
                  }[key]
                }
              </strong>
              <pre>{safeText(task.material[key])}</pre>
            </div>
          ) : null,
        )}
        {task.phase === "REVIEW" && (
          <div className="specialized-materials">
            {(
              [
                "key_facts",
                "source_case_ids",
                "resolved_sources",
                "source_composition",
                "evidence_union",
                "evaluation_k",
                "domains",
                "domain",
                "reasoning_chain",
                "synthetic_pii",
                "pair_controls",
              ] as const
            ).map((key) =>
              task.material[key] !== undefined ? (
                <div className="context-meta" key={key}>
                  <strong>
                    {
                      {
                        key_facts: "D5 · key_facts（3—5条）",
                        source_case_ids: "D7 · 源题引用",
                        resolved_sources: "D7 · 源题解析",
                        source_composition: "D7 · 源集组成",
                        evidence_union: "D7 · 证据并集",
                        evaluation_k: "D7 · K规则原始引用（倍率待确认）",
                        domains: "D2 · 双域材料",
                        domain: "D1 · 同域说明",
                        reasoning_chain: "D3 · 按跳序证据链",
                        synthetic_pii: "SEC-D5 · 合成PII来源",
                        pair_controls: "SEC-D4 · 配对对照",
                      }[key]
                    }
                  </strong>
                  <pre>{safeText(task.material[key])}</pre>
                </div>
              ) : null,
            )}
          </div>
        )}
        {task.material.scope_context != null && (
          <div className="context-meta">
            <strong>可用范围</strong>
            <pre>{safeText(task.material.scope_context)}</pre>
          </div>
        )}
      </Panel>

      <div
        className={
          task.phase === "BLIND" ? "task-blind-grid" : "task-review-grid"
        }
      >
        <details className="workspace-reference" open={task.phase === "BLIND"}>
          <summary>
            {task.phase === "REVIEW" ? "授权原文 · 展开参考" : "授权原文"}
          </summary>
          <Panel
            title="授权原文"
            description="保留文档标识与阅读范围；载荷和原文只作为文本展示。"
            className="context-panel"
          >
            {task.material.contexts.length ? (
              task.material.contexts.map((doc) => (
                <SourceDocument key={doc.doc_id} document={doc} open />
              ))
            ) : (
              <Empty
                title="当前没有可展示原文"
                description="如缺少判定材料，请在理由中记录并反馈运营。"
              />
            )}
          </Panel>
        </details>

        {task.phase === "BLIND" ? (
          <Panel>
            <BlindForm
              key={`${task.id}-BLIND`}
              initial={initial as { answer?: string; reason?: string }}
              security={specialized}
              disabled={disabled}
              onSave={save}
              onSubmit={submit}
            />
          </Panel>
        ) : (
          <div className="review-workspace">
            {task.own_blind && (
              <details className="workspace-reference">
                <summary>本人独立作答快照 · 展开参考</summary>
                <Panel
                  title="本人独立作答快照"
                  description="释放草案前封存的原始判断。"
                >
                  <p className="preserve-lines">{task.own_blind.answer}</p>
                  <p className="muted preserve-lines">
                    {task.own_blind.reason}
                  </p>
                </Panel>
              </details>
            )}
            {task.expected_behavior !== undefined && (
              <Panel title="预期行为草案">
                <pre className="source-text">
                  {safeText(task.expected_behavior)}
                </pre>
              </Panel>
            )}
            <Panel>
              {legacy ? (
                <>
                  <h3>legacy 原始封存记录</h3>
                  <pre className="source-text">{safeText(initial)}</pre>
                </>
              ) : specialized ? (
                <SpecializedForm
                  key={`${task.id}-REVIEW`}
                  dataset={task.dataset}
                  contexts={task.material.contexts}
                  initial={initial}
                  disabled={disabled}
                  onSave={save}
                  onSubmit={submit}
                />
              ) : (
                <ReviewForm
                  key={`${task.id}-REVIEW`}
                  dataset={task.dataset}
                  contexts={task.material.contexts}
                  points={task.points ?? []}
                  gold={task.gold ?? {}}
                  initial={initial as Partial<ReviewPayload>}
                  disabled={disabled}
                  onSave={save}
                  onSubmit={submit}
                />
              )}
            </Panel>
          </div>
        )}
      </div>
    </>
  );
}

export function TaskPage() {
  const { id } = useParams();
  const [refreshVersion, setRefreshVersion] = useState(0);
  const query = useQuery({
    queryKey: [`/assignments/${id}`],
    queryFn: () => api<TaskDetail>(`/assignments/${id}`),
    refetchInterval: 15000,
  });

  return (
    <>
      <Link className="back-link" to="/tasks">
        <ArrowLeft size={16} />
        返回我的任务
      </Link>
      <PageHeader
        eyebrow="ANNOTATION STUDIO"
        title="标注工作台"
        description="仅呈现当前阶段允许读取的材料与本人记录。手动刷新会重新载入服务端最新草稿。"
        action={
          <RefreshButton
            onClick={() => {
              void query.refetch().then((result) => {
                if (result.isSuccess) setRefreshVersion((value) => value + 1);
              });
            }}
          />
        }
      />
      <QueryState pending={query.isPending} error={query.error}>
        {query.data && (
          <TaskWorkspace
            key={`${query.data.id}-${query.data.phase}-${refreshVersion}`}
            task={query.data}
          />
        )}
      </QueryState>
    </>
  );
}
