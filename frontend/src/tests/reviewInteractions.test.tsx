import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { it, expect, vi } from "vitest";
import { ReviewForm } from "../components/ReviewForm";
import { BlindForm } from "../components/BlindForm";
import { GoldEditor } from "../components/GoldEditor";
import { LocatorEditor } from "../components/LocatorEditor";
import { SpecializedForm } from "../components/SpecializedReview";
import { validLocator } from "../locators";
import type { ContextDocument, Gold, Locator } from "../types";
const contexts: ContextDocument[] = [
  {
    doc_id: "d",
    text: "甲😀乙丙",
    version: "v1",
    sha256: "a".repeat(64),
    page: 2,
  },
  { doc_id: "d2", text: "新增原文甲乙", version: "v1" },
];
function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}
function click(name: string) {
  fireEvent.click(screen.getByRole("button", { name }));
}
function anchor(label: string) {
  fill(`${label} 起点`, "0");
  fill(`${label} 终点`, "2");
  click(`加入${label}`);
}
it("BLIND先拒绝空判断，再暂存与封存真实输入；服务失败不会当作成功", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  const submit = vi.fn().mockRejectedValue(new Error("版本冲突"));
  render(<BlindForm onSave={save} onSubmit={submit} />);
  click("提交并封存盲答");
  expect(screen.getByRole("alert")).toHaveTextContent("请完成独立判断");
  fill("独立答案 / 拒答判断", "  独立回答  ");
  fill("所据原文与理由", "原文d");
  click("暂存草稿");
  expect(await screen.findByRole("status")).toHaveTextContent("尚未正式封存");
  expect(save).toHaveBeenCalledWith({ answer: "独立回答", reason: "原文d" });
  click("提交并封存盲答");
  expect(await screen.findByRole("alert")).toHaveTextContent("版本冲突");
});
it("定位编辑拒绝超出Unicode长度并冻结doc版本摘要，支持移除", async () => {
  function Harness() {
    const [value, setValue] = useState<Locator[]>([]);
    return (
      <LocatorEditor
        contexts={contexts}
        label="依据"
        value={value}
        onChange={setValue}
      />
    );
  }
  render(<Harness />);
  fill("依据 起点", "1");
  fill("依据 终点", "5");
  click("加入依据");
  expect(screen.getByRole("alert")).toHaveTextContent("定位无效");
  fill("依据 终点", "2");
  fill("依据 页码", "2");
  fill("依据 章节", "章节甲");
  click("加入依据");
  expect(screen.getByText("[1, 2)", { exact: false })).toBeInTheDocument();
  expect(screen.getByText(/v1 aaaaa/)).toBeInTheDocument();
  click("移除此定位");
  expect(
    screen.queryByText("[1, 2)", { exact: false }),
  ).not.toBeInTheDocument();
});
it("定位校验拒绝未知文档、版本漂移、反向区间与不相容页码", () => {
  expect(validLocator({ doc_id: "x", span: "章" }, contexts)).toBe(false);
  expect(
    validLocator({ doc_id: "d", span: "章", context_version: "old" }, contexts),
  ).toBe(false);
  expect(
    validLocator({ doc_id: "d", span: "章", context_sha256: "old" }, contexts),
  ).toBe(false);
  expect(validLocator({ doc_id: "d", start: 2, end: 1 }, contexts)).toBe(false);
  expect(validLocator({ doc_id: "d", page: 3 }, contexts)).toBe(false);
  expect(validLocator({ doc_id: "d", page: 2, span: "" }, contexts)).toBe(
    false,
  );
  expect(validLocator({ doc_id: "d", span: "章节" }, contexts)).toBe(true);
});
it("错误要点可登记已核查文档范围且不虚构支持定位", async () => {
  const submit = vi.fn().mockResolvedValue(undefined);
  render(
    <ReviewForm
      contexts={contexts}
      points={[{ point_key: "P001", text: "错误点" }]}
      gold={{ gold_doc_ids: ["d"] }}
      initial={{
        evidence_labels: { d: 2 },
        evidence_reasons: { d: "来源存在" },
        answerable: "answerable",
        answerable_reason: "原文可回答",
        reason: "逐点检查",
      }}
      onSave={submit}
      onSubmit={submit}
    />,
  );
  fill("P001 正确性", "wrong");
  fill("P001 逐点理由", "核查全文未找到支持");
  fireEvent.click(screen.getByLabelText("P001 已核查 d"));
  click("提交并封存复核");
  await waitFor(() =>
    expect(submit).toHaveBeenCalledWith(
      expect.objectContaining({
        point_evidence: { P001: [] },
        point_search_scope: { P001: ["d"] },
        point_reasons: { P001: "核查全文未找到支持" },
      }),
    ),
  );
});
it("遗漏与证据增删绑定各自理由和定位并保留原始证据等级", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(
    <ReviewForm
      contexts={contexts}
      points={[]}
      gold={{ gold_doc_ids: ["d"] }}
      onSave={save}
      onSubmit={save}
    />,
  );
  fireEvent.click(screen.getByText("补充遗漏要点"));
  fill("遗漏要点", "遗漏甲");
  fill("遗漏理由", "原文明确");
  anchor("遗漏依据");
  click("加入遗漏建议");
  fireEvent.click(screen.getByText("建议增删证据"));
  fill("变更文档标识", "d2");
  fill("证据变更理由", "补充依据");
  fill("变更依据 文档", "d2");
  anchor("变更依据");
  click("加入建议");
  fill("d 相关度", "1");
  fill("d 逐文档理由", "部分相关");
  click("暂存草稿");
  await waitFor(() =>
    expect(save).toHaveBeenLastCalledWith(
      expect.objectContaining({
        suggested_points: [
          expect.objectContaining({
            text: "遗漏甲",
            evidence: [expect.objectContaining({ start: 0, end: 2 })],
          }),
        ],
        evidence_changes: [
          expect.objectContaining({ action: "add", doc_id: "d2" }),
        ],
        evidence_labels: { d: 1 },
      }),
    ),
  );
  click("移除遗漏建议");
  click("移除建议");
  fill("证据变更类型", "remove");
  fill("变更文档标识", "d");
  fill("证据变更理由", "建议删除");
  fill("变更依据 文档", "d");
  anchor("变更依据");
  click("加入建议");
  click("暂存草稿");
  await waitFor(() =>
    expect(save).toHaveBeenLastCalledWith(
      expect.objectContaining({
        suggested_points: [],
        evidence_changes: [
          expect.objectContaining({
            action: "remove",
            locators: [
              expect.objectContaining({ doc_id: "d", start: 0, end: 2 }),
            ],
          }),
        ],
        evidence_labels: { d: 1 },
      }),
    ),
  );
});
it("专项每项观察理由和证据齐全才能封存，保持静态审核", async () => {
  const submit = vi.fn().mockResolvedValue(undefined);
  render(
    <SpecializedForm
      dataset="SEC-D1"
      contexts={contexts}
      initial={{}}
      disabled={false}
      onSave={submit}
      onSubmit={submit}
    />,
  );
  click("提交并封存专项复核");
  expect(screen.getByRole("alert")).toHaveTextContent("每项专项观察");
  for (const label of ["ACL角色与范围", "拒答或脱敏行为"]) {
    fireEvent.click(screen.getByText(label));
    fill(`${label} · 观察`, "静态核对");
    fill(`${label} · 理由`, "符合范围");
    anchor(`${label}依据`);
  }
  fill("专项总说明", "保留待审批统计");
  click("暂存草稿");
  expect(await screen.findByRole("status")).toHaveTextContent("已保存");
  click("提交并封存专项复核");
  await waitFor(() =>
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({
        review_version: "openkb.s4-review.v2",
        specialized_review: {
          acl_scope: expect.objectContaining({ observation: "静态核对" }),
          refusal_redaction: expect.objectContaining({ reason: "符合范围" }),
        },
      }),
    ),
  );
});
it("最终编辑保持逐行要点和文档，D4保持禁用要点", () => {
  const change = vi.fn();
  function Harness() {
    const [gold, setGold] = useState<Gold>({});
    return (
      <GoldEditor
        idPrefix="g"
        value={gold}
        onChange={(value) => {
          change(value);
          setGold(value);
        }}
      />
    );
  }
  render(<Harness />);
  fill("最终答案要点（每行一条）", "甲\n乙");
  fill("最终证据文档（每行一个doc_id）", "d1\nd2");
  fill("最终可答性", "answerable");
  expect(change).toHaveBeenLastCalledWith({
    answer_points: ["甲", "乙"],
    gold_doc_ids: ["d1", "d2"],
    answerable: "answerable",
  });
});
it("最终证据删文档后可删除旧定位并创建新定位，剔除review专用版本摘要", () => {
  const change = vi.fn();
  function FinalGold() {
    const [gold, setGold] = useState<Gold>({
      answer_points: ["甲"],
      gold_doc_ids: ["d"],
      answerable: "answerable",
      gold_spans: [{ doc_id: "d", start: 0, end: 2 }],
      key_facts: ["冻结事实"],
    });
    return (
      <GoldEditor
        idPrefix="final"
        contexts={contexts}
        value={gold}
        onChange={(value) => {
          change(value);
          setGold(value);
        }}
      />
    );
  }
  render(<FinalGold />);
  fill("最终证据文档（每行一个doc_id）", "d2");
  expect(screen.getByText(/定位引用了已移除文档/)).toBeInTheDocument();
  click("移除此定位");
  fill("最终证据定位 文档", "d2");
  fill("最终证据定位 起点", "1");
  fill("最终证据定位 终点", "3");
  click("加入最终证据定位");
  expect(change).toHaveBeenLastCalledWith(
    expect.objectContaining({
      gold_doc_ids: ["d2"],
      gold_spans: [{ doc_id: "d2", start: 1, end: 3 }],
    }),
  );
  expect(screen.getByText("冻结key_facts（只读）")).toBeInTheDocument();
});
it("无效最终定位需要显式清除，不把错误JSON当作旧定位继续使用", () => {
  const change = vi.fn();
  render(
    <GoldEditor
      idPrefix="broken"
      value={{ gold_spans: [null] }}
      contexts={contexts}
      onChange={change}
    />,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("须明确清除后重建");
  expect(change).not.toHaveBeenCalled();
  click("清除无效最终定位");
  expect(change).toHaveBeenCalledWith({ gold_spans: [] });
});
