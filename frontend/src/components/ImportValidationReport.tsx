interface ReportRow {
  row: number;
  unit_id?: string;
  field_path: string;
  error_code: string;
  message: string;
}
export interface ValidationReport {
  valid: boolean;
  total_rows: number;
  error_count: number;
  errors: ReportRow[];
  truncated: boolean;
}
export function ImportValidationReport({
  report,
}: {
  report: ValidationReport;
}) {
  return (
    <section className="import-validation-report">
      <h3>接入校验明细</h3>
      <p>
        检查{report.total_rows}行，共{report.error_count}项错误。
        {report.valid ? "结构校验通过；最终接入以后台任务为准。" : ""}
      </p>
      {report.truncated && (
        <p className="notice warning">
          报告已截断，当前显示{report.errors.length}项；总错误数仍为
          {report.error_count}，需修复后重新校验。
        </p>
      )}
      {report.errors.length > 0 && (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>行号</th>
                <th>单元</th>
                <th>字段路径</th>
                <th>错误码</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              {report.errors.map((row, index) => (
                <tr key={`${row.row}-${row.field_path}-${index}`}>
                  <td>{row.row === 0 ? "批次 / 契约" : row.row}</td>
                  <td>{row.unit_id ?? "—"}</td>
                  <td className="mono tiny">{row.field_path}</td>
                  <td className="mono tiny">{row.error_code}</td>
                  <td>{row.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
