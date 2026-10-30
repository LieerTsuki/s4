import { useState } from "react";
import { ApiError } from "../api";
import { ErrorNotice, Panel } from "../components/Common";
import { apiV2 } from "./api";

interface RowError { row: number; unit_id?: string; field_path?: string; error_code: string; message: string }
interface ValidationReport { valid: boolean; errors: RowError[]; total_rows?: number; error_count?: number; truncated?: boolean }
interface ImportResult { id?: string; import_id?: string; raw_file_sha256?: string; validation_report?: ValidationReport }

function object(source: string): Record<string, unknown> {
  const value: unknown = JSON.parse(source);
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("候选包或元信息必须是JSON对象。");
  return value as Record<string, unknown>;
}

function base64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let start = 0; start < bytes.length; start += 32768) binary += String.fromCharCode(...bytes.subarray(start, start + 32768));
  return btoa(binary);
}

function ValidationDetails({ report }: { report: ValidationReport }) {
  return <section className="import-validation-report"><h3>新版逐条校验报告</h3>
    <p>{report.total_rows !== undefined && `检查 ${report.total_rows} 行；`}{report.error_count !== undefined ? `共 ${report.error_count} 项错误` : `列出 ${report.errors.length} 项错误`}。{report.valid ? "结构校验通过。" : "尚未通过校验。"}</p>
    {report.truncated && <p className="notice warm">报告已截断，需修复已列问题后重新检查；不将当前列表冒充全部错误。</p>}
    {!!report.errors.length && <div className="table-scroll"><table><thead><tr><th>行号</th><th>单元</th><th>字段路径</th><th>错误码</th><th>说明</th></tr></thead><tbody>{report.errors.map((row, index) => <tr key={`${row.row}-${row.error_code}-${index}`}><td>{row.row === 0 ? "批次 / 契约" : row.row}</td><td>{row.unit_id ?? "—"}</td><td>{row.field_path ?? "—"}</td><td className="mono tiny">{row.error_code}</td><td>{row.message}</td></tr>)}</tbody></table></div>}
  </section>;
}

export function V13Ingress({ onImported }: { onImported: () => Promise<void> }) {
  const [source, setSource] = useState("");
  const [envelope, setEnvelope] = useState("");
  const [filename, setFilename] = useState("");
  const [fileBase64, setFileBase64] = useState("");
  const [pending, setPending] = useState(false);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [preflight, setPreflight] = useState(false);

  function recordError(failure: unknown) {
    setError(failure instanceof Error ? failure : new Error("材料校验或接入失败"));
    if (failure instanceof ApiError && failure.details?.validation_report)
      setReport(failure.details.validation_report as ValidationReport);
  }
  async function read(file: File | undefined) {
    if (!file) return;
    setReading(true); setError(null); setFilename(""); setFileBase64(""); setResult(null); setReport(null);
    try {
      if (file.size > 20_000_000) throw new Error("JSONL文件超过20MB，请拆分批次。");
      const bytes = await file.arrayBuffer();
      if (bytes.byteLength > 20_000_000) throw new Error("JSONL文件超过20MB，请拆分批次。");
      setFileBase64(base64(bytes)); setFilename(file.name);
    } catch (failure) { recordError(failure); }
    finally { setReading(false); }
  }
  async function checkOrImport(checkOnly: boolean) {
    setPending(true); setError(null); setReport(null); setResult(null); setPreflight(checkOnly);
    try {
      const payload = object(source);
      if (checkOnly) setReport(await apiV2<ValidationReport>("/imports/validate", { method: "POST", body: payload }));
      else {
        const imported = await apiV2<ImportResult>("/imports", { method: "POST", body: payload });
        setResult(imported); setReport(imported.validation_report ?? null); setSource(""); await onImported();
      }
    } catch (failure) { recordError(failure); }
    finally { setPending(false); }
  }
  function extractEnvelope() {
    setError(null);
    try {
      const metadata = object(source);
      delete metadata.units;
      setEnvelope(JSON.stringify(metadata, null, 2));
    } catch (failure) { recordError(failure); }
  }
  async function upload() {
    setPending(true); setError(null); setReport(null); setResult(null); setPreflight(false);
    try {
      const metadata = object(envelope);
      if ("units" in metadata) throw new Error("JSONL元信息不能含units；单元必须来自所选原始文件。");
      const imported = await apiV2<ImportResult>("/imports/upload", { method: "POST", body: { envelope: metadata, file_base64: fileBase64 } });
      setResult(imported); setReport(imported.validation_report ?? null); await onImported();
    } catch (failure) { recordError(failure); }
    finally { setPending(false); }
  }
  return <Panel title="导入受控候选包">
    <label>读取本机 JSON 契约文件<input aria-label="v1.3 导入文件" type="file" accept=".json,application/json" onChange={event => { const file = event.target.files?.[0]; if (file) void file.text().then(setSource).catch(recordError); }} /></label>
    <label>候选包 JSON<textarea aria-label="v1.3 候选包 JSON" value={source} rows={12} onChange={event => setSource(event.target.value)} placeholder="完整v2契约：contract_version、mode、batch_id、source_revision、s3_report、units" /></label>
    <div className="form-actions"><button className="button" disabled={pending || reading || !source.trim()} onClick={() => void checkOrImport(true)}>仅检查候选包，不接入</button><button className="button primary" disabled={pending || reading || !source.trim()} onClick={() => void checkOrImport(false)}>校验并接入候选</button></div>
    <details><summary>原始UTF-8 JSONL上传</summary>
      <p>上传原始字节，保留BOM、换行与文件摘要。契约、原始S3报告和来源清单放在元信息中；不读取任意URL或服务器路径。</p>
      <button className="button" disabled={pending || !source.trim()} onClick={extractEnvelope}>从完整候选包提取元信息</button>
      <label>JSONL契约与来源元信息<textarea aria-label="v1.3 JSONL元信息" value={envelope} rows={8} onChange={event => setEnvelope(event.target.value)} placeholder="不含units的完整v2契约元信息" /></label>
      <label>选择原始单元JSONL<input aria-label="v1.3 JSONL文件" type="file" accept=".jsonl,application/x-ndjson" disabled={pending} onChange={event => void read(event.target.files?.[0])} /></label>
      {filename && <p>{filename}（原始字节已读取）</p>}
      <button className="button primary" disabled={pending || reading || !fileBase64 || !envelope.trim()} onClick={() => void upload()}>校验并接入原始JSONL</button>
    </details>
    <ErrorNotice error={error} />
    {preflight && report && <p>本次仅检查，不创建导入记录或核实任务。</p>}
    {report && <ValidationDetails report={report} />}
    {result && <div role="status" className="notice info"><p>候选已接入</p>{(result.id ?? result.import_id) && <p className="mono tiny">来源 {result.id ?? result.import_id}</p>}{result.raw_file_sha256 && <><p>原始文件SHA256</p><p className="mono tiny">{result.raw_file_sha256}</p></>}</div>}
    <p className="tiny muted">旧v1包不自动换算证据等级、拒答或难度。接入记录也不等于已经完成全量人工核实。</p>
  </Panel>;
}
