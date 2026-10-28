import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ReviewForm } from "../components/ReviewForm";
import { SourceDocument } from "../components/SourceDocument";
it("v2封存拒绝只有总理由而缺少逐对象理由和定位", async () => {
  const submit = vi.fn();
  render(
    <ReviewForm
      points={[{ point_key: "P001", text: "要点" }]}
      gold={{ gold_doc_ids: ["d"] }}
      initial={{
        point_labels: { P001: "correct" },
        evidence_labels: { d: 2 },
        answerable: "answerable",
        reason: "总理由",
      }}
      onSave={submit}
      onSubmit={submit}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: "提交并封存复核" }));
  expect(submit).not.toHaveBeenCalled();
  expect(screen.getByRole("alert")).toHaveTextContent("逐点理由");
});
it("v2暂存有明确协议且不捏造未填写理由", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(<ReviewForm points={[]} gold={{}} onSave={save} onSubmit={save} />);
  await userEvent.click(screen.getByRole("button", { name: "暂存草稿" }));
  expect(save).toHaveBeenCalledWith(
    expect.objectContaining({
      review_version: "openkb.s4-review.v2",
      point_reasons: {},
      point_evidence: {},
      evidence_reasons: {},
      answerable_reason: "",
    }),
  );
});
it("原文高亮以Unicode半开字符坐标展示且不解析HTML", () => {
  render(
    <SourceDocument
      document={{ doc_id: "d", text: "甲😀<b>乙</b>丙" }}
      open
      locators={[{ doc_id: "d", start: 1, end: 2 }]}
    />,
  );
  expect(screen.getByText("😀").tagName).toBe("MARK");
  expect(document.querySelector("b")).toBeNull();
});
import { SpecializedMaterials } from "../components/SpecializedMaterials";
it("有限专项材料显示缺失说明且不解释metadata中的HTML或未注册字段", () => {
  render(
    <SpecializedMaterials
      dataset="SEC-D5"
      metadata={{
        synthetic_pii: "<img src=x onerror=alert(1)>",
        secret: "不应展示",
      }}
    />,
  );
  expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
  expect(screen.queryByText("不应展示")).not.toBeInTheDocument();
  expect(screen.getByText(/源材料未提供/)).toBeInTheDocument();
  expect(document.querySelector("img")).toBeNull();
});
