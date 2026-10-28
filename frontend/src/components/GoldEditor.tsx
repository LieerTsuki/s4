import type { Answerability, ContextDocument, Gold, Locator } from "../types";
import { LocatorEditor } from "./LocatorEditor";
import { safeText } from "../format";

export function GoldEditor({
  value,
  onChange,
  idPrefix,
  disabled,
  unanswerable,
  contexts = [],
  keyFacts,
}: {
  value: Gold;
  onChange: (gold: Gold) => void;
  idPrefix: string;
  disabled?: boolean;
  unanswerable?: boolean;
  contexts?: ContextDocument[];
  keyFacts?: unknown;
}) {
  const validSpans =
    Array.isArray(value.gold_spans) &&
    value.gold_spans.every(
      (span) =>
        span && typeof span === "object" && typeof span.doc_id === "string",
    );
  const spans = validSpans ? (value.gold_spans as Locator[]) : [];
  const invalidSpans = value.gold_spans !== undefined && !validSpans;
  const orphaned = spans.filter(
    (span) => !(value.gold_doc_ids ?? []).includes(span.doc_id),
  );
  return (
    <div className="form-stack">
      <label htmlFor={`${idPrefix}-points`}>最终答案要点（每行一条）</label>
      <textarea
        id={`${idPrefix}-points`}
        rows={3}
        value={(value.answer_points ?? []).join("\n")}
        disabled={disabled || unanswerable}
        onChange={(event) =>
          onChange({ ...value, answer_points: event.target.value.split("\n") })
        }
        placeholder={
          unanswerable ? "D4保持空答案要点" : "逐行填写经原文核实的最终要点"
        }
      />
      <label htmlFor={`${idPrefix}-docs`}>最终证据文档（每行一个doc_id）</label>
      <textarea
        id={`${idPrefix}-docs`}
        rows={2}
        value={(value.gold_doc_ids ?? []).join("\n")}
        disabled={disabled}
        onChange={(event) =>
          onChange({ ...value, gold_doc_ids: event.target.value.split("\n") })
        }
      />
      <label htmlFor={`${idPrefix}-answerable`}>最终可答性</label>
      <select
        id={`${idPrefix}-answerable`}
        value={value.answerable ?? ""}
        disabled={disabled}
        onChange={(event) =>
          onChange({
            ...value,
            answerable: event.target.value as Answerability,
          })
        }
      >
        <option value="">请选择</option>
        <option value="answerable">answerable · 可回答</option>
        <option value="no_answer">no_answer · 无答案</option>
        <option value="expired">expired · 已过期</option>
        <option value="out_of_scope">out_of_scope · 范围外</option>
      </select>
      {orphaned.length > 0 && (
        <p role="alert" className="notice warning">
          定位引用了已移除文档：{orphaned.map((span) => span.doc_id).join("、")}
          。请移除旧定位或恢复文档后重新核对。
        </p>
      )}
      {invalidSpans && (
        <div role="alert" className="notice danger">
          原gold_spans不是定位数组，须明确清除后重建，不能保留无效定位。
          <button
            type="button"
            disabled={disabled}
            className="button small"
            onClick={() => onChange({ ...value, gold_spans: [] })}
          >
            清除无效最终定位
          </button>
        </div>
      )}
      <LocatorEditor
        label="最终证据定位"
        contexts={contexts.filter((doc) =>
          (value.gold_doc_ids ?? []).includes(doc.doc_id),
        )}
        value={spans}
        disabled={disabled}
        onChange={(locators) =>
          onChange({
            ...value,
            gold_spans: locators.map((locator) => ({
              doc_id: locator.doc_id,
              ...(locator.start !== undefined ? { start: locator.start } : {}),
              ...(locator.end !== undefined ? { end: locator.end } : {}),
              ...(locator.page !== undefined ? { page: locator.page } : {}),
              ...(locator.span !== undefined ? { span: locator.span } : {}),
            })),
          })
        }
      />
      {(keyFacts ?? value.key_facts) !== undefined && (
        <div className="context-meta">
          <strong>冻结key_facts（只读）</strong>
          <pre>{safeText(keyFacts ?? value.key_facts)}</pre>
          <p className="muted">
            此表单保留冻结事实；实质修改须通过受控新revision与独立复验。
          </p>
        </div>
      )}
    </div>
  );
}
