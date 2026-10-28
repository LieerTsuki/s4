import { useState } from "react";
import type { components } from "../generated/openapi";
import type { ContextDocument, Locator } from "../types";
import { useCommand } from "../hooks";
import { ErrorNotice } from "./Common";
import { LocatorEditor } from "./LocatorEditor";
export function MaterialIssueForm({
  assignmentId,
  contexts,
}: {
  assignmentId: string;
  contexts: ContextDocument[];
}) {
  const [open, setOpen] = useState(false);
  const [type, setType] =
    useState<components["schemas"]["IssueInput"]["issue_type"]>(
      "MISSING_SOURCE",
    );
  const [reason, setReason] = useState("");
  const [locators, setLocators] = useState<Locator[]>([]);
  const command = useCommand();
  return (
    <section className="material-issue">
      <button
        type="button"
        className="button small"
        onClick={() => setOpen(!open)}
      >
        报告材料问题
      </button>
      {open && (
        <form
          className="form-stack"
          onSubmit={async (e) => {
            e.preventDefault();
            const body: components["schemas"]["IssueInput"] = {
              assignment_id: assignmentId,
              issue_type: type,
              reason,
              locators,
            };
            const result = await command.run("/work-issues", body);
            if (result) {
              command.setSuccess(
                "材料问题已登记，阻塞问题由服务端暂停作业，等待独立运营处置。",
              );
              setOpen(false);
            }
          }}
        >
          <label>
            问题类型
            <select
              value={type}
              onChange={(e) => setType(e.target.value as typeof type)}
            >
              {[
                ["MISSING_SOURCE", "缺原文"],
                ["INVALID_LOCATOR", "定位失效"],
                ["VERSION_CONFLICT", "版本冲突"],
                ["EARLY_EXPOSURE", "提前暴露"],
                ["INSUFFICIENT_SCOPE", "权限范围不足"],
                ["OTHER", "其他"],
              ].map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            问题描述
            <textarea
              required
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <LocatorEditor
            label="问题定位（可选）"
            contexts={contexts}
            value={locators}
            onChange={setLocators}
          />
          <button
            className="button primary"
            disabled={command.pending || !reason.trim()}
          >
            登记材料问题
          </button>
        </form>
      )}
      <ErrorNotice error={command.error} />
      {command.success && (
        <div role="status" className="notice success">
          {command.success}
        </div>
      )}
    </section>
  );
}
