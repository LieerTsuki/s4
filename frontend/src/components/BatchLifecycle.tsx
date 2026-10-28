import { useState } from "react";
import type { components } from "../generated/openapi";
import type { AnnotationBatch, User } from "../types";
import { useCommand, useList } from "../hooks";
import { ErrorNotice, Panel } from "./Common";
export function BatchLifecycle({ batch }: { batch: AnnotationBatch }) {
  const users = useList<User>("/users");
  const command = useCommand();
  const [reason, setReason] = useState("");
  const [seat, setSeat] = useState<"A" | "B">("A");
  const [person, setPerson] = useState("");
  return (
    <Panel
      title="暂停、恢复与整席补派"
      description="BLIND补派覆盖该席位完整样本；另一席位不变。REVIEW已开放须建立完整新轮。"
    >
      <label>
        操作依据
        <textarea value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <div className="button-row">
        <button
          className="button"
          disabled={
            command.pending || !reason.trim() || batch.state === "PAUSED"
          }
          onClick={() =>
            void command.run(`/annotation-batches/${batch.id}/pause`, {
              version: batch.version,
              reason,
            })
          }
        >
          暂停批次
        </button>
        <button
          className="button"
          disabled={
            command.pending || !reason.trim() || batch.state !== "PAUSED"
          }
          onClick={() =>
            void command.run(`/annotation-batches/${batch.id}/resume`, {
              version: batch.version,
              reason,
            })
          }
        >
          核对后恢复
        </button>
      </div>
      <form
        className="form-grid"
        onSubmit={(e) => {
          e.preventDefault();
          const body: components["schemas"]["SeatReplace"] = {
            seat,
            new_annotator_id: person,
            reason,
            version: batch.version!,
          };
          void command.run(
            `/annotation-batches/${batch.id}/replace-seat`,
            body,
          );
        }}
      >
        <label>
          替换席位
          <select
            value={seat}
            onChange={(e) => setSeat(e.target.value as "A" | "B")}
          >
            <option>A</option>
            <option>B</option>
          </select>
        </label>
        <label>
          新标注员
          <select
            required
            value={person}
            onChange={(e) => setPerson(e.target.value)}
          >
            <option value="">选择未暴露且有资格的人员</option>
            {users.data?.items
              ?.filter((u) => u.active && u.roles.includes("annotator"))
              .map((user) => (
                <option key={user.id} value={user.id}>
                  {user.display_name} · {user.person_id}
                </option>
              ))}
          </select>
        </label>
        <button
          className="button primary"
          disabled={
            command.pending ||
            !reason.trim() ||
            !person ||
            !["BLIND_OPEN", "BLIND_SEALED"].includes(batch.state)
          }
        >
          补派整个席位
        </button>
      </form>
      <ErrorNotice error={command.error ?? users.error} />
    </Panel>
  );
}
