import { BatchLifecycle } from "../components/BatchLifecycle";
import type { components } from "../generated/openapi";

import { SourceDocument } from "../components/SourceDocument";

import { safeText } from "../format";

import { useState } from "react";

import { Link, useParams } from "react-router-dom";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  ArrowLeft,
  Calculator,
  CheckCheck,
  LockKeyhole,
  Plus,
  RotateCcw,
} from "lucide-react";

import { api } from "../api";

import { useCommand, useList } from "../hooks";

import type {
  Agreement,
  AnnotationBatch,
  Arbitration,
  Gold,
  ImportRecord,
  Profile,
  User,
} from "../types";

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

import { GoldEditor } from "../components/GoldEditor";

export function BatchesPage({ canWrite }: { canWrite: boolean }) {
  const query = useList<AnnotationBatch>("/annotation-batches");
  const imports = useList<ImportRecord>("/imports", canWrite);
  const users = useList<User>("/users", canWrite);
  const revisions = useList<{
    id: string;
    dataset: string;
    version: string;
    state: string;
  }>("/profile-revisions", canWrite);
  const profiles = useQuery({
    queryKey: ["/profiles"],
    queryFn: () => api<Profile[]>("/profiles"),
  });
  const command = useCommand();

  const [open, setOpen] = useState(false);
  const [importId, setImportId] = useState("");
  const [dataset, setDataset] = useState("");
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [seed, setSeed] = useState(42);
  const [profileId, setProfileId] = useState("");
  const [due, setDue] = useState("");
  const [reminder, setReminder] = useState(60);
  const [localError, setLocalError] = useState<Error | null>(null);

  const annotators =
    users.data?.items.filter(
      (user) => user.active && user.roles.includes("annotator"),
    ) ?? [];

  return (
    <>
      <PageHeader
        eyebrow="BATCH OPERATIONS"
        title="标注批次与排班"
        description="冻结抽样、固定实际人员对与统计范围；不能在看到标签后挑选题目或改变范围。"
        action={
          canWrite ? (
            <button className="button primary" onClick={() => setOpen(!open)}>
              <Plus size={17} />
              创建标注批次
            </button>
          ) : (
            <RefreshButton onClick={() => void query.refetch()} />
          )
        }
      />

      <div className="notice info">
        <LockKeyhole size={19} />
        <div>
          <strong>抽样按数据集与难度留账</strong>
          <p>
            每数据集max(8, ceil(10% ×
            N))；不足8条时如实阻塞正式出口。每个统计批次固定两名不同实际人员。
          </p>
        </div>
      </div>
      <ErrorNotice error={command.error ?? localError} />

      {open && canWrite && (
        <Panel title="冻结抽样与人员">
          <form
            className="form-grid"
            onSubmit={async (event) => {
              event.preventDefault();
              setLocalError(null);
              if (a === b) {
                setLocalError(new Error("A/B必须是两名不同实际人员。"));
                return;
              }
              const body: components["schemas"]["BatchCreate"] = {
                import_id: importId,
                dataset,
                annotator_a: a,
                annotator_b: b,
                seed,
                reminder_interval_minutes: reminder,
                ...(profileId ? { profile_revision_id: profileId } : {}),
                ...(due ? { due_at: new Date(due).toISOString() } : {}),
              };
              const result = await command.run<AnnotationBatch>(
                "/annotation-batches",
                body,
              );
              if (result) setOpen(false);
            }}
          >
            <label>
              来源批次
              <select
                value={importId}
                required
                onChange={(event) => setImportId(event.target.value)}
              >
                <option value="">请选择已导入批次</option>
                {imports.data?.items.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.batch_id} · {item.mode} · {item.unit_count}单元
                  </option>
                ))}
              </select>
            </label>
            <label>
              数据集
              <select
                value={dataset}
                required
                onChange={(event) => setDataset(event.target.value)}
              >
                <option value="">请选择数据集</option>
                {profiles.data?.map((profile) => (
                  <option key={profile.dataset} value={profile.dataset}>
                    {profile.dataset} · {profile.kind}
                  </option>
                ))}
              </select>
            </label>
            <label>
              A席位
              <select
                value={a}
                required
                onChange={(event) => setA(event.target.value)}
              >
                <option value="">请选择标注员</option>
                {annotators.map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.display_name} · {user.person_id}
                  </option>
                ))}
              </select>
            </label>
            <label>
              B席位
              <select
                value={b}
                required
                onChange={(event) => setB(event.target.value)}
              >
                <option value="">请选择另一位标注员</option>
                {annotators.map((user) => (
                  <option
                    key={user.id}
                    value={user.id}
                    disabled={user.id === a}
                  >
                    {user.display_name} · {user.person_id}
                  </option>
                ))}
              </select>
            </label>
            <label>
              可复现随机种子
              <input
                type="number"
                min={0}
                max={2147483647}
                value={seed}
                required
                onChange={(event) => setSeed(Number(event.target.value))}
              />
            </label>
            <label>
              批准配置版本
              <select
                value={profileId}
                onChange={(event) => setProfileId(event.target.value)}
              >
                <option value="">服务端选择批准基线</option>
                {revisions.data?.items
                  ?.filter(
                    (item) =>
                      item.state === "APPROVED" && item.dataset === dataset,
                  )
                  .map((item) => (
                    <option value={item.id} key={item.id}>
                      {item.dataset} · {item.version}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              任务截止时间
              <input
                type="datetime-local"
                value={due}
                onChange={(event) => setDue(event.target.value)}
              />
            </label>
            <label>
              提醒间隔（分钟）
              <input
                type="number"
                min={1}
                max={10080}
                required
                value={reminder}
                onChange={(event) => setReminder(Number(event.target.value))}
              />
            </label>
            <div className="form-grid-note">
              服务端将重新验证资格、职责冲突、暴露历史、版本与采样范围。
            </div>
            <ErrorNotice
              error={imports.error ?? users.error ?? profiles.error}
            />
            <div className="button-row span-all">
              <button className="button primary" disabled={command.pending}>
                创建并开始独立作答
              </button>
              <button
                type="button"
                className="button"
                onClick={() => setOpen(false)}
              >
                取消
              </button>
            </div>
          </form>
        </Panel>
      )}

      <Panel
        title="批次记录"
        action={<RefreshButton onClick={() => void query.refetch()} />}
      >
        <QueryState pending={query.isPending} error={query.error}>
          {query.data?.items.length ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>数据集 / 批次</th>
                    <th>轮次</th>
                    <th>抽检单元</th>
                    <th>双人盲答</th>
                    <th>双人复核</th>
                    <th>状态</th>
                    <th>查看</th>
                  </tr>
                </thead>
                <tbody>
                  {query.data.items.map((batch) => (
                    <tr key={batch.id}>
                      <td>
                        <strong>{batch.dataset}</strong>
                        <div className="tiny muted mono">{batch.id}</div>
                      </td>
                      <td>R{batch.round}</td>
                      <td>{batch.sample_count}</td>
                      <td>
                        <span className="count-value">
                          {batch.blind_submitted}
                        </span>
                        <span className="muted">
                          {" "}
                          / {batch.sample_count * 2}份
                        </span>
                      </td>
                      <td>
                        <span className="count-value">
                          {batch.review_submitted}
                        </span>
                        <span className="muted">
                          {" "}
                          / {batch.sample_count * 2}份
                        </span>
                      </td>
                      <td>
                        <Badge value={batch.state} />
                      </td>
                      <td>
                        <PageLink to={`/batches/${batch.id}`}>
                          管理批次
                        </PageLink>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty
              title="尚未创建标注批次"
              description="先完成候选接入，再按数据集安排固定双人作业。"
            />
          )}
        </QueryState>
      </Panel>
    </>
  );
}

function FinalizationForm({
  batch,
  arbitrations,
}: {
  batch: AnnotationBatch;
  arbitrations: Arbitration[];
}) {
  const command = useCommand();
  const units = batch.units ?? [];
  const [decisions, setDecisions] = useState<
    Record<string, { final_gold: Gold; reason: string }>
  >(() =>
    Object.fromEntries(
      units.map((unit) => [
        unit.unit_id,
        {
          final_gold: structuredClone(
            arbitrations.find(
              (item) => item.unit_id === unit.unit_id && item.confirmed,
            )?.final_gold ??
              unit.gold ??
              {},
          ),
          reason: "",
        },
      ]),
    ),
  );
  const [open, setOpen] = useState(false);

  const update = (
    id: string,
    change: Partial<{ final_gold: Gold; reason: string }>,
  ) => setDecisions({ ...decisions, [id]: { ...decisions[id], ...change } });

  return (
    <Panel
      title="最终内容确认"
      description="一致性通过仍需核对内容。每个抽检单元由授权负责人依据原文确认，原始标签与κ保持不变。"
      action={
        <button
          className="button small"
          disabled={batch.finalized}
          onClick={() => setOpen(!open)}
        >
          <CheckCheck size={16} />
          {batch.finalized
            ? "已定稿"
            : open
              ? "收起定稿表单"
              : "打开逐单元定稿"}
        </button>
      }
    >
      <ErrorNotice error={command.error} />
      {batch.finalized ? (
        <div className="notice success">该轮最终内容已封存。</div>
      ) : open ? (
        <form
          className="form-stack"
          onSubmit={async (event) => {
            event.preventDefault();
            const rows = units.map((unit) => {
              const decision = decisions[unit.unit_id];
              return {
                unit_id: unit.unit_id,
                final_gold: {
                  ...decision.final_gold,
                  answer_points: (decision.final_gold.answer_points ?? [])
                    .map((point) => point.trim())
                    .filter(Boolean),
                  gold_doc_ids: (decision.final_gold.gold_doc_ids ?? [])
                    .map((doc) => doc.trim())
                    .filter(Boolean),
                },
                reason: decision.reason,
              };
            });
            const result = await command.run(
              `/annotation-batches/${batch.id}/finalize`,
              { decisions: rows },
            );
            if (result) setOpen(false);
          }}
        >
          {units.length ? (
            units.map((unit) => (
              <details className="decision-card" key={unit.unit_id}>
                <summary>
                  <span className="mono">{unit.unit_id}</span>
                  <span>{unit.question ?? "专项材料"}</span>
                  <Badge
                    value={
                      decisions[unit.unit_id]?.reason ? "READY" : "PENDING"
                    }
                    label={
                      decisions[unit.unit_id]?.reason ? "已填写理由" : "待确认"
                    }
                  />
                </summary>
                <div className="decision-content">
                  <GoldEditor
                    contexts={unit.contexts}
                    keyFacts={unit.key_facts}
                    idPrefix={`final-${unit.unit_id}`}
                    value={decisions[unit.unit_id]?.final_gold ?? {}}
                    onChange={(gold) =>
                      update(unit.unit_id, { final_gold: gold })
                    }
                    unanswerable={batch.dataset === "QA-D4"}
                    disabled={arbitrations.some(
                      (item) => item.unit_id === unit.unit_id && item.confirmed,
                    )}
                  />
                  <label>
                    定稿理由
                    <textarea
                      required
                      rows={3}
                      value={decisions[unit.unit_id]?.reason ?? ""}
                      onChange={(event) =>
                        update(unit.unit_id, { reason: event.target.value })
                      }
                      placeholder="说明沿用或修订草案的原文依据"
                    />
                  </label>
                  <div className="final-contexts">
                    {unit.contexts?.map((doc) => (
                      <SourceDocument key={doc.doc_id} document={doc} />
                    ))}
                  </div>
                </div>
              </details>
            ))
          ) : (
            <Empty title="没有可定稿单元" />
          )}

          <button
            className="button primary align-start"
            disabled={
              command.pending ||
              !units.length ||
              units.some((unit) => !decisions[unit.unit_id]?.reason.trim())
            }
          >
            确认全部抽检单元并封存定稿
          </button>
        </form>
      ) : (
        <p className="muted">
          检查原文和已授权的双方记录后，再逐单元填写最终内容及理由。
        </p>
      )}
    </Panel>
  );
}

function RoundsForm({ batch }: { batch: AnnotationBatch }) {
  const users = useList<User>("/users");
  const command = useCommand();
  const [open, setOpen] = useState(false);
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [reason, setReason] = useState("");
  const [calibrationId, setCalibrationId] = useState("");
  const [manualVersion, setManualVersion] = useState(
    batch.manual_version ?? "",
  );
  const [profileRevisionId, setProfileRevisionId] = useState(
    batch.profile_revision_id ?? "",
  );
  const [seed, setSeed] = useState(42);
  const annotators =
    users.data?.items.filter(
      (user) => user.active && user.roles.includes("annotator"),
    ) ?? [];

  return (
    <Panel
      title="校准与全批新轮"
      description="保留旧轮次，按完整统计范围重标；已经暴露的人员不能冒充首次盲答。"
      action={
        <button className="button small" onClick={() => setOpen(!open)}>
          <RotateCcw size={15} />
          开启新轮
        </button>
      }
    >
      {open && (
        <form
          className="form-grid"
          onSubmit={async (event) => {
            event.preventDefault();
            const result = await command.run("/rounds", {
              batch_id: batch.id,
              annotator_a: a,
              annotator_b: b,
              reason,
              seed,
              calibration_id: calibrationId,
              manual_version: manualVersion,
              profile_revision_id: profileRevisionId,
            });
            if (result) setOpen(false);
          }}
        >
          <label>
            新A席
            <select
              value={a}
              required
              onChange={(event) => setA(event.target.value)}
            >
              <option value="">选择未暴露人员</option>
              {annotators.map((user) => (
                <option value={user.id} key={user.id}>
                  {user.display_name}
                </option>
              ))}
            </select>
          </label>
          <label>
            新B席
            <select
              value={b}
              required
              onChange={(event) => setB(event.target.value)}
            >
              <option value="">选择另一位未暴露人员</option>
              {annotators.map((user) => (
                <option value={user.id} key={user.id} disabled={user.id === a}>
                  {user.display_name}
                </option>
              ))}
            </select>
          </label>
          <label>
            随机种子
            <input
              type="number"
              min={0}
              max={2147483647}
              value={seed}
              onChange={(event) => setSeed(Number(event.target.value))}
              required
            />
          </label>
          <label>
            关联校准记录ID
            <input
              required
              value={calibrationId}
              onChange={(event) => setCalibrationId(event.target.value)}
            />
          </label>
          <label>
            新轮手册版本
            <input
              required
              value={manualVersion}
              onChange={(event) => setManualVersion(event.target.value)}
            />
          </label>
          <label>
            新轮批准profile版本ID
            <input
              required
              value={profileRevisionId}
              onChange={(event) => setProfileRevisionId(event.target.value)}
            />
          </label>
          <label className="span-all">
            校准记录与重标原因
            <textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              rows={3}
              required
            />
          </label>
          <ErrorNotice error={users.error ?? command.error} />
          <button
            className="button primary align-start"
            disabled={command.pending || !a || !b || a === b}
          >
            创建完整样本新轮
          </button>
        </form>
      )}
    </Panel>
  );
}

function PairSummary({ batch }: { batch: AnnotationBatch }) {
  const rows = (batch.units ?? []).flatMap((unit) =>
    (unit.gold?.answer_points ?? []).map((text, index) => {
      const pointKey = `P${String(index + 1).padStart(3, "0")}`;

      const label = (seat: string) => {
        const assignment = batch.assignments?.find(
          (item) => item.unit_id === unit.unit_id && item.seat === seat,
        );

        const payload = batch.submissions?.find(
          (item) =>
            item.assignment_id === assignment?.id && item.phase === "REVIEW",
        )?.payload;

        const labels = payload?.point_labels;

        return labels && typeof labels === "object"
          ? String((labels as Record<string, unknown>)[pointKey] ?? "缺配对")
          : "缺配对";
      };

      return {
        unit: unit.unit_id,
        pointKey,
        text,
        a: label("A"),
        b: label("B"),
      };
    }),
  );

  return (
    <Panel
      title="原始标签配对核查"
      description="按冻结单元、原始point_key与A/B席位核对。此处展示授权原始记录，正式κ由服务端计算。"
    >
      {rows.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>单元</th>
                <th>point_key</th>
                <th>原始要点</th>
                <th>A原始标签</th>
                <th>B原始标签</th>
                <th>配对</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.unit}-${row.pointKey}`}>
                  <td className="mono tiny">{row.unit}</td>
                  <td className="mono tiny">{row.pointKey}</td>
                  <td>{row.text}</td>
                  <td>{row.a}</td>
                  <td>{row.b}</td>
                  <td>
                    <Badge
                      value={
                        row.a === "缺配对" || row.b === "缺配对"
                          ? "BLOCKED"
                          : row.a === row.b
                            ? "READY"
                            : "ARBITRATE"
                      }
                      label={
                        row.a === "缺配对" || row.b === "缺配对"
                          ? "缺配对"
                          : row.a === row.b
                            ? "一致"
                            : "分歧"
                      }
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted tiny">
          本批没有可展示的QA原始要点向量；专项材料使用各自规则。
        </p>
      )}
    </Panel>
  );
}

export function BatchPage({ canWrite }: { canWrite: boolean }) {
  const { id } = useParams();
  const query = useQuery({
    queryKey: [`/annotation-batches/${id}`],
    queryFn: () => api<AnnotationBatch>(`/annotation-batches/${id}`),
    refetchInterval: 10000,
  });
  const command = useCommand();
  const client = useQueryClient();
  const [jobId, setJobId] = useState("");
  const agreements = useList<Agreement>("/agreements");
  const arbitrationQuery = useList<Arbitration>("/arbitrations", canWrite);
  const arbitrations =
    arbitrationQuery.data?.items.filter((item) => item.batch_id === id) ?? [];
  const agreement = agreements.data?.items.find((item) => item.batch_id === id);
  const batch = query.data
    ? { ...query.data, agreement: agreement ?? query.data.agreement }
    : undefined;

  return (
    <>
      <Link className="back-link" to="/batches">
        <ArrowLeft size={16} />
        返回批次列表
      </Link>
      <PageHeader
        eyebrow="BATCH CONTROL"
        title={batch ? `${batch.dataset} · 第${batch.round}轮` : "批次详情"}
        description={id ?? ""}
        action={<RefreshButton onClick={() => void query.refetch()} />}
      />
      <QueryState pending={query.isPending} error={query.error}>
        {batch && (
          <>
            <div className="stats-grid compact">
              <div className="stat-card">
                <div>抽检单元</div>
                <strong>{batch.sample_count}</strong>
                <p>每人均审核完整样本</p>
              </div>
              <div className="stat-card">
                <div>独立作答封存</div>
                <strong>
                  {batch.blind_submitted}
                  <small> / {batch.sample_count * 2}</small>
                </strong>
                <p>全批齐备后才可统一解锁</p>
              </div>
              <div className="stat-card">
                <div>复核封存</div>
                <strong>
                  {batch.review_submitted}
                  <small> / {batch.sample_count * 2}</small>
                </strong>
                <p>保留双方原始判断</p>
              </div>
              <div className="stat-card">
                <div>批次状态</div>
                <Badge value={batch.state} />
                <p>质量verdict与过程状态分开</p>
              </div>
            </div>
            <BlockedReasons reasons={batch.blocked_reasons} />
            <ErrorNotice error={agreements.error ?? arbitrationQuery.error} />
            <ErrorNotice error={command.error} />

            {canWrite && (
              <div className="action-bar">
                <button
                  className="button"
                  disabled={command.pending || batch.state !== "BLIND_SEALED"}
                  onClick={() =>
                    void command.run(
                      `/annotation-batches/${batch.id}/release-review`,
                    )
                  }
                >
                  <LockKeyhole size={16} />
                  统一开放复核
                </button>
                <button
                  className="button primary"
                  disabled={command.pending || batch.state !== "PAIR_COMPLETE"}
                  onClick={async () => {
                    const result = await command.run<{ job_id: string }>(
                      `/annotation-batches/${batch.id}/agreement`,
                    );
                    if (result) setJobId(result.job_id);
                  }}
                >
                  <Calculator size={17} />
                  计算批次一致性
                </button>
                <span className="muted">
                  服务端重查全部封存、版本与暴露状态。
                </span>
              </div>
            )}

            {jobId && (
              <JobProgress
                id={jobId}
                onComplete={() => void client.invalidateQueries()}
              />
            )}

            {batch.agreement && (
              <Panel title="原始一致性结论">
                <div className="agreement-summary">
                  <div>
                    <span className="muted">Cohen's κ</span>
                    <strong>
                      {batch.agreement.kappa == null
                        ? "未定义"
                        : batch.agreement.kappa.toFixed(4)}
                    </strong>
                  </div>
                  <Badge value={batch.agreement.verdict} />
                  <dl>
                    <div>
                      <dt>标签对数 N</dt>
                      <dd>{batch.agreement.n}</dd>
                    </div>
                    <div>
                      <dt>观察一致率 po</dt>
                      <dd>{batch.agreement.po?.toFixed(4) ?? "—"}</dd>
                    </div>
                    <div>
                      <dt>期望一致率 pe</dt>
                      <dd>{batch.agreement.pe?.toFixed(4) ?? "—"}</dd>
                    </div>
                  </dl>
                </div>
                <BlockedReasons reasons={batch.agreement.blocked_reasons} />
              </Panel>
            )}

            <Panel
              title="冻结抽样清单"
              description="单元数与双人提交份数分开核对。"
            >
              <div className="unit-id-list">
                {batch.selected_ids.map((unit) => (
                  <span className="plain-tag mono" key={unit}>
                    {unit}
                  </span>
                ))}
              </div>
            </Panel>

            {!!batch.submissions?.length && <PairSummary batch={batch} />}
            {batch.submissions?.length ? (
              <Panel
                title="授权提交记录"
                description="仅授权非参标人员可读取；原始封存不因仲裁而覆盖。"
              >
                <div className="submission-grid">
                  {batch.submissions.map((record, index) => (
                    <details className="decision-card" key={record.id ?? index}>
                      <summary>
                        <Badge value={record.phase ?? "SUBMITTED"} />
                        <span className="mono tiny">
                          {String(record.assignment_id ?? record.id ?? "")}
                        </span>
                      </summary>
                      <div className="decision-content">
                        {record.payload &&
                          Object.entries(record.payload).map(([key, value]) => (
                            <div key={key} className="submission-field">
                              <strong>
                                {(
                                  {
                                    answer: "独立判断",
                                    reason: "理由",
                                    point_labels: "要点标签",
                                    evidence_labels: "证据相关度",
                                    answerable: "可答性",
                                    suggested_points: "遗漏建议",
                                    evidence_changes: "证据变更建议",
                                    specialized_review: "专项记录",
                                  } as Record<string, string>
                                )[key] ?? key}
                              </strong>
                              <pre>{safeText(value)}</pre>
                            </div>
                          ))}
                      </div>
                    </details>
                  ))}
                </div>
              </Panel>
            ) : null}

            {canWrite && (
              <>
                <BatchLifecycle batch={batch} />
                <FinalizationForm
                  key={`${batch.id}-${batch.finalized}-${arbitrations
                    .filter((item) => item.confirmed)
                    .map((item) => item.id)
                    .join()} `}
                  batch={batch}
                  arbitrations={arbitrations}
                />
                <RoundsForm batch={batch} />
              </>
            )}
          </>
        )}
      </QueryState>
    </>
  );
}
