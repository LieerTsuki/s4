import type { ContextDocument, Locator } from "./types";
export function validLocator(
  locator: Locator,
  contexts: ContextDocument[],
): boolean {
  const doc = contexts.find((item) => item.doc_id === locator.doc_id);
  if (!doc) return false;
  if (
    locator.context_version !== undefined &&
    locator.context_version !== String(doc.version ?? "")
  )
    return false;
  if (
    locator.context_sha256 !== undefined &&
    locator.context_sha256 !== String(doc.sha256 ?? "")
  )
    return false;
  const hasRange = locator.start !== undefined || locator.end !== undefined;
  if (
    hasRange &&
    (!Number.isInteger(locator.start) ||
      !Number.isInteger(locator.end) ||
      locator.start! < 0 ||
      locator.start! >= locator.end! ||
      locator.end! > Array.from(doc.text).length)
  )
    return false;
  if (
    locator.page !== undefined &&
    (!Number.isInteger(locator.page) ||
      locator.page < 1 ||
      (typeof doc.page === "number" && locator.page !== doc.page))
  )
    return false;
  if (locator.span !== undefined && !locator.span.trim()) return false;
  return hasRange || !!locator.span?.trim() || locator.page !== undefined;
}
