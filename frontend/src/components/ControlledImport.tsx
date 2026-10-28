import { useState } from "react";
import type { components } from "../generated/openapi";
import { api, ApiError } from "../api";
import { ErrorNotice, Panel } from "./Common";
import { ImportValidationReport } from "./ImportValidationReport";
import type { ValidationReport } from "./ImportValidationReport";

function object(text: string): Record<string, unknown> {
  const result: unknown = JSON.parse(text);
  if (!result || typeof result !== "object" || Array.isArray(result))
    throw new Error("契约、报告与原文索引必须为JSON对象。");
  return result as Record<string, unknown>;
}
async function fileText(file: File): Promise<string> {
  if (file.size > 20 * 1024 * 1024)
    throw new Error("文件超过20MB，请按批次拆分。");
  return new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(
    await file.arrayBuffer(),
  );
}
interface UploadResponse {
  job_id: string;
  raw_file_sha256: string;
  normalized_sha256: string;
  validation_report: ValidationReport;
}
export function ControlledImport({
  onCreated,
}: {
  onCreated: (jobId: string) => void;
}) {
  const [filename, setFilename] = useState("");
  const [jsonl, setJsonl] = useState("");
  const [envelope, setEnvelope] = useState("{}");
  const [index, setIndex] = useState("{}");
  const [pending, setPending] = useState(false);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [result, setResult] = useState<UploadResponse | null>(null);
  const [report, setReport] = useState<ValidationReport | null>(null);
  async function read(
    file: File | undefined,
    kind: "units" | "envelope" | "index",
  ) {
    if (!file) return;
    setError(null);
    setReading(true);
    try {
      if (
        kind === "units" &&
        !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,150}\.jsonl$/.test(file.name)
      )
        throw new Error(
          "单元文件名须使用字母、数字、下划线、点或连字符，并以.jsonl结尾。",
        );
      const text = await fileText(file);
      if (kind === "units") {
        setFilename(file.name);
        setJsonl(text);
      } else if (kind === "envelope") setEnvelope(text);
      else setIndex(text);
    } catch (e) {
      setError(e instanceof Error ? e : new Error("读取UTF-8文件失败"));
      if (kind === "units") {
        setFilename("");
        setJsonl("");
      }
    } finally {
      setReading(false);
    }
  }
  async function upload() {
    setError(null);
    setReport(null);
    setResult(null);
    setPending(true);
    try {
      const wrapper = object(envelope);
      if ("units" in wrapper)
        throw new Error("契约包装不得含units，单元须来自所选JSONL文件。");
      const sourceIndex: Record<string, Record<string, unknown>> = {};
      for (const [docId, document] of Object.entries(object(index))) {
        if (
          !document ||
          typeof document !== "object" ||
          Array.isArray(document)
        )
          throw new Error("原文索引每项必须为文档对象。");
        sourceIndex[docId] = document as Record<string, unknown>;
      }
      const body: components["schemas"]["ImportUpload"] = {
        filename,
        units_jsonl: jsonl,
        envelope: wrapper,
        source_index: sourceIndex,
      };
      const data = await api<UploadResponse>("/imports/upload", {
        method: "POST",
        body,
      });
      setResult(data);
      setReport(data.validation_report);
      onCreated(data.job_id);
    } catch (e) {
      setError(e instanceof Error ? e : new Error("上传失败"));
      if (e instanceof ApiError && e.details?.validation_report)
        setReport(e.details.validation_report as ValidationReport);
    } finally {
      setPending(false);
    }
  }
  return (
    <Panel
      title="JSONL受控上传"
      description="单元JSONL、契约/报告与原文索引一同提交；只使用本次上传内容，不访问任意URL或本机路径。"
    >
      <form
        className="form-stack"
        onSubmit={(event) => {
          event.preventDefault();
          void upload();
        }}
      >
        <label>
          选择单元JSONL文件
          <input
            type="file"
            accept=".jsonl,application/x-ndjson"
            aria-label="选择单元JSONL文件"
            onChange={(event) => void read(event.target.files?.[0], "units")}
          />
        </label>
        {filename && (
          <p className="muted">
            已选择 {filename} · UTF-8 · 最多2200行、20MB整体上限由服务端复核
          </p>
        )}
        <label>
          选择契约与S3报告文件（可选）
          <input
            type="file"
            accept=".json,application/json"
            onChange={(event) => void read(event.target.files?.[0], "envelope")}
          />
        </label>
        <label>
          契约与S3报告JSON（不含units）
          <textarea
            aria-label="契约与S3报告JSON（不含units）"
            rows={7}
            className="code-input"
            value={envelope}
            required
            onChange={(event) => setEnvelope(event.target.value)}
          />
        </label>
        <label>
          选择原文索引文件（可选）
          <input
            type="file"
            accept=".json,application/json"
            onChange={(event) => void read(event.target.files?.[0], "index")}
          />
        </label>
        <label>
          原文索引JSON（可选）
          <textarea
            aria-label="原文索引JSON（可选）"
            rows={4}
            className="code-input"
            value={index}
            onChange={(event) => setIndex(event.target.value)}
          />
        </label>
        <button
          className="button primary align-start"
          disabled={pending || reading || !filename || !jsonl.trim()}
        >
          {pending ? "正在上传…" : "提交JSONL受控上传"}
        </button>
      </form>
      <ErrorNotice error={error} />
      {report && <ImportValidationReport report={report} />}{" "}
      {result && (
        <dl className="document-metadata">
          <div>
            <dt>原始文件SHA-256</dt>
            <dd className="mono tiny">{result.raw_file_sha256}</dd>
          </div>
          <div>
            <dt>归一化SHA-256</dt>
            <dd className="mono tiny">{result.normalized_sha256}</dd>
          </div>
        </dl>
      )}
    </Panel>
  );
}
