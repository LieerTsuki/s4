import { useState } from "react";
import { CheckCheck, Save } from "lucide-react";
import { ErrorNotice } from "./Common";

export function BlindForm({
  initial,
  onSave,
  onSubmit,
  disabled,
  security,
}: {
  initial?: { answer?: string; reason?: string };
  onSave: (payload: { answer: string; reason: string }) => Promise<void>;
  onSubmit: (payload: { answer: string; reason: string }) => Promise<void>;
  disabled?: boolean;
  security?: boolean;
}) {
  const [answer, setAnswer] = useState(initial?.answer ?? "");
  const [reason, setReason] = useState(initial?.reason ?? "");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [saved, setSaved] = useState(false);
  async function perform(seal: boolean) {
    setError(null);
    setSaved(false);
    if (seal && (!answer.trim() || !reason.trim())) {
      setError(new Error("请完成独立判断及所据原文与理由。"));
      return;
    }
    setPending(true);
    try {
      await (seal ? onSubmit : onSave)({
        answer: answer.trim(),
        reason: reason.trim(),
      });
      if (!seal) setSaved(true);
    } catch (failure) {
      setError(failure instanceof Error ? failure : new Error("操作失败"));
    } finally {
      setPending(false);
    }
  }
  return (
    <form
      className="form-stack"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void perform(true);
      }}
    >
      <div className="section-eyebrow">BLIND · 独立作答</div>
      <h2>{security ? "独立判断安全边界" : "根据原文独立作答"}</h2>
      <p className="muted">
        此阶段未开放生成草案。请记录你自己的判断，提交后封存。
      </p>
      <p className="notice info">
        当前为独立作答阶段。整批A/B全部封存并由运营统一开放后，进入答案要点、证据相关度、可答性三栏复核。
      </p>
      <label htmlFor="blind-answer">
        {security ? "安全作用域与预期处理判断" : "独立答案 / 拒答判断"}
      </label>
      <textarea
        id="blind-answer"
        rows={8}
        value={answer}
        onChange={(event) => setAnswer(event.target.value)}
        disabled={disabled}
        placeholder={
          security
            ? "说明该载荷应如何处理，不执行载荷"
            : "根据可阅读材料作答，无法回答时说明判断"
        }
      />
      <label htmlFor="blind-reason">所据原文与理由</label>
      <textarea
        id="blind-reason"
        rows={5}
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        disabled={disabled}
        placeholder="列出doc_id、定位与判断依据"
      />
      <ErrorNotice error={error} />
      {saved && (
        <div className="notice success" role="status">
          草稿已保存，尚未正式封存。
        </div>
      )}
      <div className="button-row">
        <button
          className="button"
          type="button"
          disabled={disabled || pending}
          onClick={() => void perform(false)}
        >
          <Save size={16} />
          暂存草稿
        </button>
        <button
          className="button primary"
          type="submit"
          disabled={disabled || pending}
        >
          <CheckCheck size={16} />
          {pending ? "正在提交…" : "提交并封存盲答"}
        </button>
      </div>
    </form>
  );
}
