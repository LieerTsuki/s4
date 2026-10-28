import { validLocator } from "../locators";
import { useState } from "react";

import type {
  Answerability,
  ContextDocument,
  EvidenceChange,
  Gold,
  Point,
  PointLabel,
  ReviewPayload,
  SuggestedPoint,
} from "../types";

import { LocatorEditor } from "./LocatorEditor";

import { SpecializedFields } from "./SpecializedReview";
import { completeSpecialized } from "../specialized";

export function ReviewForm({
  points,
  gold,
  onSave,
  onSubmit,
  initial,
  disabled,
  contexts = [],
  dataset = "QA-D1",
}: {
  points: Point[];
  gold: Gold;
  contexts?: ContextDocument[];
  dataset?: string;
  onSave: (payload: ReviewPayload) => Promise<void>;
  onSubmit: (payload: ReviewPayload) => Promise<void>;
  initial?: Partial<ReviewPayload>;
  disabled?: boolean;
}) {
  const [data, setData] = useState<ReviewPayload>(() => ({
    review_version: "openkb.s4-review.v2",
    specialized_review: initial?.specialized_review ?? {},
    point_labels: initial?.point_labels ?? {},
    evidence_labels: initial?.evidence_labels ?? {},
    answerable: initial?.answerable ?? "",
    reason: initial?.reason ?? "",
    point_reasons: initial?.point_reasons ?? {},
    point_evidence: initial?.point_evidence ?? {},
    point_search_scope: initial?.point_search_scope ?? {},
    evidence_reasons: initial?.evidence_reasons ?? {},
    answerable_reason: initial?.answerable_reason ?? "",
    suggested_points: Array.isArray(initial?.suggested_points)
      ? initial.suggested_points.filter((v) => typeof v === "object")
      : [],
    evidence_changes: initial?.evidence_changes ?? [],
  }));

  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [saved, setSaved] = useState(false);

  const [suggestion, setSuggestion] = useState<SuggestedPoint>({
    suggestion_id: "",
    text: "",
    reason: "",
    evidence: [],
  });
  const [change, setChange] = useState<EvidenceChange>({
    change_id: "",
    action: "add",
    doc_id: "",
    reason: "",
    locators: [],
  });

  const update = (patch: Partial<ReviewPayload>) =>
    setData({ ...data, ...patch });
  const docs = gold.gold_doc_ids ?? [];

  async function perform(seal: boolean) {
    setError("");
    setSaved(false);
    if (
      seal &&
      (!points.every(
        (p) =>
          data.point_labels[p.point_key] &&
          data.point_reasons?.[p.point_key]?.trim() &&
          ((data.point_evidence?.[p.point_key]?.length &&
            data.point_evidence[p.point_key].every((l) =>
              validLocator(l, contexts),
            )) ||
            (data.point_labels[p.point_key] === "wrong" &&
              data.point_search_scope?.[p.point_key]?.length &&
              data.point_search_scope[p.point_key].every((id) =>
                contexts.some((c) => c.doc_id === id),
              ))),
      ) ||
        !docs.every(
          (id) =>
            [0, 1, 2].includes(data.evidence_labels[id]) &&
            data.evidence_reasons?.[id]?.trim(),
        ) ||
        !data.answerable ||
        !data.answerable_reason?.trim() ||
        !data.reason.trim() ||
        !completeSpecialized(dataset, data.specialized_review, contexts))
    ) {
      setError(
        "请完成每个原始要点、证据、可答性及理由，包括逐点理由、定位、逐文档理由与题级可答理由。",
      );
      return;
    }
    setPending(true);
    try {
      await (seal ? onSubmit : onSave)(data);
      if (!seal) setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "提交失败");
    } finally {
      setPending(false);
    }
  }

  return (
    <form
      className="review-form"
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        void perform(true);
      }}
    >
      <div className="review-columns">
        <section className="review-column">
          <div className="section-eyebrow">01 · 答案要点</div>
          <h3>逐点核对正确性</h3>
          <p className="muted">
            原始要点保持统计身份；每点单独绑定理由与原文。
          </p>
          {points.length ? (
            points.map((p) => (
              <div className="label-card" key={p.point_key}>
                <span>{p.point_key}</span>
                <p>{p.text}</p>
                <select
                  aria-label={`${p.point_key} 正确性`}
                  value={data.point_labels[p.point_key] ?? ""}
                  disabled={disabled}
                  onChange={(e) =>
                    update({
                      point_labels: {
                        ...data.point_labels,
                        [p.point_key]: e.target.value as PointLabel,
                      },
                    })
                  }
                >
                  <option value="">请选择判定</option>
                  <option value="correct">正确</option>
                  <option value="partial">部分正确</option>
                  <option value="wrong">错误</option>
                </select>
                <label>
                  {p.point_key} 逐点理由
                  <textarea
                    disabled={disabled}
                    value={data.point_reasons?.[p.point_key] ?? ""}
                    onChange={(e) =>
                      update({
                        point_reasons: {
                          ...data.point_reasons,
                          [p.point_key]: e.target.value,
                        },
                      })
                    }
                  />
                </label>
                {data.point_labels[p.point_key] === "wrong" && (
                  <fieldset disabled={disabled}>
                    <legend>已核查授权原文，未找到支持依据</legend>
                    {contexts.map((doc) => (
                      <label className="checkbox-label" key={doc.doc_id}>
                        <input
                          type="checkbox"
                          aria-label={`${p.point_key} 已核查 ${doc.doc_id}`}
                          checked={
                            data.point_search_scope?.[p.point_key]?.includes(
                              doc.doc_id,
                            ) ?? false
                          }
                          onChange={(e) => {
                            const ids =
                              data.point_search_scope?.[p.point_key] ?? [];
                            update({
                              point_search_scope: {
                                ...data.point_search_scope,
                                [p.point_key]: e.target.checked
                                  ? [...ids, doc.doc_id]
                                  : ids.filter((id) => id !== doc.doc_id),
                              },
                              point_evidence: {
                                ...data.point_evidence,
                                [p.point_key]: [],
                              },
                            });
                          }}
                        />
                        {doc.title ?? doc.doc_id}
                      </label>
                    ))}
                  </fieldset>
                )}
                <LocatorEditor
                  label={`${p.point_key} 原文依据`}
                  contexts={contexts}
                  disabled={disabled}
                  value={data.point_evidence?.[p.point_key] ?? []}
                  onChange={(value) =>
                    update({
                      point_evidence: {
                        ...data.point_evidence,
                        [p.point_key]: value,
                      },
                    })
                  }
                />
              </div>
            ))
          ) : (
            <p className="empty-inline">该任务没有答案要点，不生成虚构判定。</p>
          )}

          <details>
            <summary>补充遗漏要点</summary>
            <label>
              遗漏要点
              <textarea
                value={suggestion.text}
                disabled={disabled}
                onChange={(e) =>
                  setSuggestion({ ...suggestion, text: e.target.value })
                }
              />
            </label>
            <label>
              遗漏理由
              <textarea
                value={suggestion.reason}
                disabled={disabled}
                onChange={(e) =>
                  setSuggestion({ ...suggestion, reason: e.target.value })
                }
              />
            </label>
            <LocatorEditor
              label="遗漏依据"
              contexts={contexts}
              value={suggestion.evidence}
              onChange={(evidence) =>
                setSuggestion({ ...suggestion, evidence })
              }
              disabled={disabled}
            />
            <button
              type="button"
              className="button"
              disabled={
                disabled ||
                !suggestion.text.trim() ||
                !suggestion.reason.trim() ||
                !suggestion.evidence.length
              }
              onClick={() => {
                update({
                  suggested_points: [
                    ...(data.suggested_points ?? []),
                    { ...suggestion, suggestion_id: crypto.randomUUID() },
                  ],
                });
                setSuggestion({
                  suggestion_id: "",
                  text: "",
                  reason: "",
                  evidence: [],
                });
              }}
            >
              加入遗漏建议
            </button>
          </details>
          {data.suggested_points?.map((item) => (
            <div className="suggestion" key={item.suggestion_id}>
              {item.text} · {item.reason}
              <button
                type="button"
                disabled={disabled}
                onClick={() =>
                  update({
                    suggested_points: data.suggested_points?.filter(
                      (p) => p.suggestion_id !== item.suggestion_id,
                    ),
                  })
                }
              >
                移除遗漏建议
              </button>
            </div>
          ))}
        </section>

        <section className="review-column">
          <div className="section-eyebrow">02 · 证据相关度</div>
          <h3>逐文档确认依据</h3>
          <p className="muted">相关度固定2 / 1 / 0，增删建议不覆盖原等级。</p>
          {docs.map((id) => (
            <div className="label-card" key={id}>
              <span>{id}</span>
              <select
                aria-label={`${id} 相关度`}
                disabled={disabled}
                value={data.evidence_labels[id] ?? ""}
                onChange={(e) => {
                  const labels = { ...data.evidence_labels };
                  if (e.target.value === "") delete labels[id];
                  else labels[id] = Number(e.target.value);
                  update({ evidence_labels: labels });
                }}
              >
                <option value="">请选择相关度</option>
                <option value="2">相关（2）</option>
                <option value="1">部分相关（1）</option>
                <option value="0">不相关（0）</option>
              </select>
              <label>
                {id} 逐文档理由
                <textarea
                  disabled={disabled}
                  value={data.evidence_reasons?.[id] ?? ""}
                  onChange={(e) =>
                    update({
                      evidence_reasons: {
                        ...data.evidence_reasons,
                        [id]: e.target.value,
                      },
                    })
                  }
                />
              </label>
            </div>
          ))}

          <details>
            <summary>建议增删证据</summary>
            <select
              aria-label="证据变更类型"
              disabled={disabled}
              value={change.action}
              onChange={(e) =>
                setChange({
                  ...change,
                  action: e.target.value as "add" | "remove",
                  doc_id: "",
                  locators: [],
                })
              }
            >
              <option value="add">建议新增</option>
              <option value="remove">建议删除</option>
            </select>
            <select
              aria-label="变更文档标识"
              disabled={disabled}
              value={change.doc_id}
              onChange={(e) =>
                setChange({ ...change, doc_id: e.target.value, locators: [] })
              }
            >
              <option value="">选择文档</option>
              {(change.action === "remove"
                ? docs
                : contexts
                    .map((c) => c.doc_id)
                    .filter((id) => !docs.includes(id))
              ).map((id) => (
                <option key={id}>{id}</option>
              ))}
            </select>
            <label>
              证据变更理由
              <textarea
                disabled={disabled}
                value={change.reason}
                onChange={(e) =>
                  setChange({ ...change, reason: e.target.value })
                }
              />
            </label>
            <LocatorEditor
              label="变更依据"
              contexts={contexts.filter((c) => c.doc_id === change.doc_id)}
              value={change.locators}
              disabled={disabled}
              onChange={(locators) => setChange({ ...change, locators })}
            />
            <button
              type="button"
              className="button"
              disabled={
                disabled ||
                !change.doc_id ||
                !change.reason.trim() ||
                !change.locators.length
              }
              onClick={() => {
                update({
                  evidence_changes: [
                    ...(data.evidence_changes ?? []),
                    { ...change, change_id: crypto.randomUUID() },
                  ],
                });
                setChange({
                  change_id: "",
                  action: "add",
                  doc_id: "",
                  reason: "",
                  locators: [],
                });
              }}
            >
              加入建议
            </button>
          </details>
          {data.evidence_changes?.map((item) => (
            <div className="suggestion" key={item.change_id}>
              {item.action === "add" ? "新增" : "删除"} {item.doc_id} ·{" "}
              {item.reason}
              <button
                type="button"
                disabled={disabled}
                onClick={() =>
                  update({
                    evidence_changes: data.evidence_changes?.filter(
                      (c) => c.change_id !== item.change_id,
                    ),
                  })
                }
              >
                移除建议
              </button>
            </div>
          ))}
        </section>

        <section className="review-column">
          <div className="section-eyebrow">03 · 可答性</div>
          <h3>核对回答边界</h3>
          <p className="muted">依据授权范围、时效与权限说明题级判断。</p>
          <label htmlFor="answerability">可答性</label>
          <select
            id="answerability"
            disabled={disabled}
            value={data.answerable}
            onChange={(e) =>
              update({ answerable: e.target.value as Answerability })
            }
          >
            <option value="">请选择</option>
            {["answerable", "no_answer", "expired", "out_of_scope"].map(
              (value) => (
                <option key={value}>{value}</option>
              ),
            )}
          </select>
          <label>
            题级可答理由
            <textarea
              disabled={disabled}
              value={data.answerable_reason ?? ""}
              onChange={(e) => update({ answerable_reason: e.target.value })}
            />
          </label>
          <label htmlFor="review-reason">复核理由</label>
          <textarea
            id="review-reason"
            rows={6}
            disabled={disabled}
            value={data.reason}
            onChange={(e) => update({ reason: e.target.value })}
          />
        </section>
      </div>
      <SpecializedFields
        dataset={dataset}
        contexts={contexts}
        disabled={disabled}
        value={data.specialized_review ?? {}}
        onChange={(specialized_review) => update({ specialized_review })}
      />
      {error && (
        <div role="alert" className="notice danger">
          {error}
        </div>
      )}
      {saved && (
        <div role="status" className="notice success">
          草稿已保存，尚未计入正式提交。
        </div>
      )}
      <div className="form-footer">
        <span className="muted">
          无法定位请先报告材料问题；封存保留原始判断。
        </span>
        <div className="button-row">
          <button
            type="button"
            className="button"
            disabled={disabled || pending}
            onClick={() => void perform(false)}
          >
            暂存草稿
          </button>
          <button
            type="submit"
            className="button primary"
            disabled={disabled || pending}
          >
            {pending ? "正在提交…" : "提交并封存复核"}
          </button>
        </div>
      </div>
    </form>
  );
}
