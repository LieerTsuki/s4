import { BookOpen } from "lucide-react";
import type { ContextDocument, Locator } from "../types";
import { safeText } from "../format";

const fields = [
  ["valid_from", "有效起始"],
  ["valid_until", "有效截止"],
  ["version", "文档版本"],
  ["page", "页码"],
  ["start", "起始位置"],
  ["end", "终止位置"],
  ["acl_context", "权限背景"],
  ["license", "许可"],
  ["source_url", "来源地址"],
  ["sha256", "原文SHA-256"],
] as const;

export function SourceDocument({
  document,
  open = false,
  locators = [],
}: {
  document: ContextDocument;
  open?: boolean;
  locators?: Locator[];
}) {
  const metadata = fields.filter(([key]) => document[key] != null);
  const chars = Array.from(document.text);
  const ranges = locators.filter(
    (item) =>
      item.doc_id === document.doc_id &&
      Number.isInteger(item.start) &&
      Number.isInteger(item.end) &&
      item.start! >= 0 &&
      item.end! <= chars.length &&
      item.start! < item.end!,
  );
  const boundaries = [
    ...new Set([
      0,
      chars.length,
      ...ranges.flatMap((item) => [item.start!, item.end!]),
    ]),
  ].sort((a, b) => a - b);
  const highlighted = boundaries.slice(0, -1).map((start, index) => {
    const end = boundaries[index + 1];
    const text = chars.slice(start, end).join("");
    return ranges.some((item) => item.start! <= start && item.end! >= end) ? (
      <mark key={start}>{text}</mark>
    ) : (
      text
    );
  });
  return (
    <details className="context-document" open={open}>
      <summary>
        <BookOpen size={16} />
        <strong>{document.title ?? document.doc_id}</strong>
        <span className="mono tiny">{document.doc_id}</span>
      </summary>
      {metadata.length > 0 && (
        <dl className="document-metadata">
          {metadata.map(([key, title]) => (
            <div key={key}>
              <dt>{title}</dt>
              <dd>{safeText(document[key])}</dd>
            </div>
          ))}
        </dl>
      )}
      <pre className="source-text">{highlighted}</pre>
    </details>
  );
}
