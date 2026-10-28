import { validLocator } from "../locators";
import { useState } from "react";
import type { ContextDocument, Locator } from "../types";
import { SourceDocument } from "./SourceDocument";

export function LocatorEditor({
  label,
  contexts,
  value,
  onChange,
  disabled = false,
}: {
  label: string;
  contexts: ContextDocument[];
  value: Locator[];
  onChange: (value: Locator[]) => void;
  disabled?: boolean;
}) {
  const [docId, setDocId] = useState(contexts[0]?.doc_id ?? "");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [page, setPage] = useState("");
  const [span, setSpan] = useState("");
  const [error, setError] = useState("");
  const doc = contexts.find((item) => item.doc_id === docId);
  function add() {
    const locator: Locator = {
      doc_id: docId,
      ...(doc?.version !== undefined
        ? { context_version: String(doc.version) }
        : {}),
      ...(doc?.sha256 !== undefined
        ? { context_sha256: String(doc.sha256) }
        : {}),
      ...(start !== "" ? { start: Number(start) } : {}),
      ...(end !== "" ? { end: Number(end) } : {}),
      ...(page !== "" ? { page: Number(page) } : {}),
      ...(span ? { span: span.trim() } : {}),
    };
    if (!validLocator(locator, contexts)) {
      setError("定位无效：请核对授权原文、Unicode半开字符范围、页码或章节。");
      return;
    }
    onChange([...value, locator]);
    setError("");
    setStart("");
    setEnd("");
    setSpan("");
    setPage("");
  }
  return (
    <fieldset className="locator-editor" disabled={disabled}>
      <legend>{label}</legend>
      <p className="tiny muted">
        字符坐标从0开始，结束位置不包含；😀等字符计1。文档版本与摘要随定位冻结。
      </p>
      <label>
        定位文档
        <select
          aria-label={`${label} 文档`}
          value={docId}
          onChange={(e) => setDocId(e.target.value)}
        >
          <option value="">选择授权文档</option>
          {contexts.map((item) => (
            <option key={item.doc_id} value={item.doc_id}>
              {item.title ?? item.doc_id}
            </option>
          ))}
        </select>
      </label>
      <div className="locator-range">
        <label>
          起点
          <input
            aria-label={`${label} 起点`}
            type="number"
            min="0"
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
        </label>
        <label>
          终点
          <input
            aria-label={`${label} 终点`}
            type="number"
            min="1"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
          />
        </label>
        <label>
          页码
          <input
            aria-label={`${label} 页码`}
            type="number"
            min="1"
            value={page}
            onChange={(e) => setPage(e.target.value)}
          />
        </label>
      </div>
      <label>
        章节 / span
        <input
          aria-label={`${label} 章节`}
          value={span}
          onChange={(e) => setSpan(e.target.value)}
        />
      </label>
      <button type="button" className="button small" onClick={add}>
        加入{label}
      </button>
      {error && <p role="alert">{error}</p>}
      {value.map((item, index) => (
        <div className="suggestion" key={index}>
          <span>
            {item.doc_id} [{item.start ?? "—"}, {item.end ?? "—"}) {item.span}{" "}
            {item.page ? `第${item.page}页` : ""}
          </span>
          <span className="tiny mono">
            {item.context_version} {item.context_sha256}
          </span>
          <button
            type="button"
            className="text-button"
            onClick={() => onChange(value.filter((_, i) => i !== index))}
          >
            移除此定位
          </button>
        </div>
      ))}
      {doc && (
        <details>
          <summary>
            预览原文与定位高亮（{Array.from(doc.text).length}字符）
          </summary>
          <SourceDocument document={doc} open locators={value} />
        </details>
      )}
    </fieldset>
  );
}
