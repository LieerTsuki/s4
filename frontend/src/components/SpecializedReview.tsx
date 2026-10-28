import { labels, specializedFields, completeSpecialized } from "../specialized";
import type { Observations } from "../specialized";
import { useState } from "react";
import type { ContextDocument } from "../types";
import { LocatorEditor } from "./LocatorEditor";
export function SpecializedFields({
  dataset,
  value,
  onChange,
  contexts,
  disabled,
}: {
  dataset: string;
  value: Observations;
  onChange: (v: Observations) => void;
  contexts: ContextDocument[];
  disabled?: boolean;
}) {
  return (
    <section className="specialized-observations">
      <h3>{dataset} 专项逐项观察</h3>
      <p className="muted">
        只登记原始观察与依据，不新增专项统计阈值。载荷仅供静态核对。
      </p>
      {(specializedFields[dataset] ?? []).map((key) => {
        const row = value[key] ?? { observation: "", reason: "", evidence: [] };
        return (
          <details className="label-card" key={key}>
            <summary>{labels[key]}</summary>
            <label>
              {labels[key]} · 观察
              <textarea
                disabled={disabled}
                value={row.observation}
                onChange={(e) =>
                  onChange({
                    ...value,
                    [key]: { ...row, observation: e.target.value },
                  })
                }
              />
            </label>
            <label>
              {labels[key]} · 理由
              <textarea
                disabled={disabled}
                value={row.reason}
                onChange={(e) =>
                  onChange({
                    ...value,
                    [key]: { ...row, reason: e.target.value },
                  })
                }
              />
            </label>
            <LocatorEditor
              label={`${labels[key]}依据`}
              contexts={contexts}
              disabled={disabled}
              value={row.evidence}
              onChange={(evidence) =>
                onChange({ ...value, [key]: { ...row, evidence } })
              }
            />
          </details>
        );
      })}
    </section>
  );
}
export function SpecializedForm({
  dataset,
  initial,
  disabled,
  onSave,
  onSubmit,
  contexts,
}: {
  dataset: string;
  initial: Record<string, unknown>;
  disabled: boolean;
  contexts: ContextDocument[];
  onSave: (v: Record<string, unknown>) => Promise<void>;
  onSubmit: (v: Record<string, unknown>) => Promise<void>;
}) {
  const [value, setValue] = useState<Observations>(
    initial.specialized_review && typeof initial.specialized_review === "object"
      ? (initial.specialized_review as Observations)
      : {},
  );
  const [reason, setReason] = useState(String(initial.reason ?? ""));
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [saved, setSaved] = useState(false);
  async function perform(seal: boolean) {
    setError("");
    setSaved(false);
    if (
      seal &&
      (!reason.trim() || !completeSpecialized(dataset, value, contexts))
    ) {
      setError("请完成每项专项观察、理由与原文依据。");
      return;
    }
    setPending(true);
    try {
      await (seal ? onSubmit : onSave)({
        review_version: "openkb.s4-review.v2",
        specialized_review: value,
        reason,
      });
      if (!seal) setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    } finally {
      setPending(false);
    }
  }
  return (
    <form
      className="form-stack"
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        void perform(true);
      }}
    >
      <div className="notice warning">
        专项量表尚未冻结；审核记录不自动获得正式κ与交接资格。
      </div>
      <SpecializedFields
        dataset={dataset}
        contexts={contexts}
        value={value}
        onChange={setValue}
        disabled={disabled}
      />
      <label>
        专项总说明
        <textarea
          disabled={disabled}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </label>
      {error && (
        <div role="alert" className="notice danger">
          {error}
        </div>
      )}
      {saved && <div role="status">专项草稿已保存。</div>}
      <div className="button-row">
        <button
          type="button"
          className="button"
          disabled={disabled || pending}
          onClick={() => void perform(false)}
        >
          暂存草稿
        </button>
        <button className="button primary" disabled={disabled || pending}>
          提交并封存专项复核
        </button>
      </div>
    </form>
  );
}
