import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, it, expect, vi } from "vitest";
import {
  ProfileRevisions,
  GovernanceForm,
  IssuesPage,
  GovernancePage,
} from "../pages/Governance";
import {
  NotificationsPage,
  OperationsPanel,
  HandoffSending,
} from "../pages/CompletionOperations";
import { MaterialIssueForm } from "../components/MaterialIssueForm";
import { BatchLifecycle } from "../components/BatchLifecycle";
import type { AnnotationBatch, User } from "../types";

function mount(node: React.ReactNode) {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}
interface Call {
  path: string;
  method: string;
  body: Record<string, unknown>;
}
function server(rows: Record<string, unknown> = {}) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init: RequestInit = {}) => {
      const path = url.replace("/api/s4/v1", "").split("?")[0];
      const method = init.method ?? "GET";
      const body = init.body ? JSON.parse(String(init.body)) : {};
      calls.push({ path, method, body });
      return Promise.resolve(
        new Response(
          JSON.stringify(
            method === "GET"
              ? (rows[path] ?? { items: [], total: 0 })
              : { id: "created", job_id: "j1", state: "SUCCEEDED", version: 2 },
          ),
          { status: 200 },
        ),
      );
    }),
  );
  return calls;
}
function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}
async function click(name: string) {
  fireEvent.click(await screen.findByRole("button", { name }));
}
async function posted(calls: Call[], path: string, expected: unknown) {
  await waitFor(() =>
    expect(calls).toContainEqual(
      expect.objectContaining({
        path,
        method: "POST",
        body: expect.objectContaining(expected),
      }),
    ),
  );
}
afterEach(() => vi.unstubAllGlobals());
const profile = {
  id: "p",
  dataset: "QA-D1",
  version: "v2",
  manual_version: "m2",
  revision: 3,
  state: "IN_REVIEW",
  snapshot: { version: "v2", manual_version: "m2", instructions: "旧说明" },
};
it("配置批准使用state和真实revision并保留证据", async () => {
  const calls = server({
    "/profile-revisions": { items: [profile], total: 1 },
  });
  mount(<ProfileRevisions />);
  fill("审批 / 流程理由", "独立审核完成");
  fill("审批证据 JSON", '{"ref":"evidence:approval"}');
  fireEvent.click(await screen.findByText("QA-D1 · v2"));
  await click("独立批准");
  await posted(calls, "/profile-revisions/p/approve", {
    version: 3,
    reason: "独立审核完成",
    evidence: { ref: "evidence:approval" },
  });
});
it("配置复制创建会同步新版本和手册到完整快照", async () => {
  const calls = server({
    "/profile-revisions": { items: [profile], total: 1 },
  });
  mount(<ProfileRevisions />);
  fireEvent.click(await screen.findByText("QA-D1 · v2"));
  await click("复制为新草案");
  fill("配置版本", "v3");
  fill("手册版本", "m3");
  fill("配置变更理由", "更新说明");
  await click("登记配置草案");
  await posted(calls, "/profile-revisions", {
    version: "v3",
    manual_version: "m3",
    snapshot: { version: "v3", manual_version: "m3", instructions: "旧说明" },
  });
});
it("草案可编辑并提交审批，错误JSON阻止请求", async () => {
  const calls = server({
    "/profile-revisions": { items: [{ ...profile, state: "DRAFT" }], total: 1 },
  });
  mount(<ProfileRevisions />);
  fireEvent.click(await screen.findByText("QA-D1 · v2"));
  await click("编辑草案");
  fill("配置快照 JSON", "[]");
  fill("配置变更理由", "改说明");
  await click("保存配置草案");
  expect(await screen.findByRole("alert")).toHaveTextContent("JSON对象");
  fill("配置快照 JSON", '{"instructions":"新说明"}');
  await click("保存配置草案");
  await waitFor(() =>
    expect(
      calls.some(
        (c) => c.path === "/profile-revisions/p" && c.method === "PATCH" && c.body.expected_revision === 3,
      ),
    ).toBe(true),
  );
  fill("审批 / 流程理由", "检查通过");
  await click("提交审批");
  await posted(calls, "/profile-revisions/p/submit", { version: 3 });
});
it("退回与归档分别调用有版本条件的流程动作", async () => {
  const calls = server({
    "/profile-revisions": {
      items: [
        profile,
        { ...profile, id: "approved", state: "APPROVED", version: "v1" },
      ],
      total: 2,
    },
  });
  mount(<ProfileRevisions />);
  fill("审批 / 流程理由", "独立评审");
  fireEvent.click(await screen.findByText("QA-D1 · v2"));
  await click("退回草案");
  await posted(calls, "/profile-revisions/p/reject", { version: 3 });
  fireEvent.click(await screen.findByText("QA-D1 · v1"));
  await click("归档版本");
  await posted(calls, "/profile-revisions/approved/retire", { version: 3 });
});
it("复验工作台明确载入单元候选摘要并提交逐点受控证据", async () => {
  const calls = server({
    "/validation-candidates": {
      batch_id: "b",
      unit_id: "u",
      proposal_id: "pr",
      final_gold: { answer_points: ["候选"] },
      content_hash: "a".repeat(64),
      profile_hash: "b".repeat(64),
      contexts: [],
    },
  });
  mount(<GovernanceForm path="/validation-revisions" />);
  fill("复验批次ID", "b");
  fill("复验单元ID", "u");
  await click("载入已登记复验候选");
  await waitFor(() =>
    expect(screen.getByLabelText("完整候选SHA-256")).toHaveValue(
      "a".repeat(64),
    ),
  );
  fill("独立复验理由", "逐点核对");
  fill("受控复验证据 JSON", '{"kind":"synthetic","revision":"v1"}');
  await click("登记独立复验证据");
  await posted(calls, "/validation-revisions", {
    content_hash: "a".repeat(64),
    profile_hash: "b".repeat(64),
    final_gold: { answer_points: ["候选"] },
  });
});
it("负责人先登记实质修订复验候选", async () => {
  const calls = server();
  mount(<GovernanceForm path="/validation-revisions" />);
  fill("复验批次ID", "b");
  fill("复验单元ID", "u");
  fill("独立复验理由", "修订答案");
  fill("指定复验人ID", "verifier-1");
  fill("最终gold JSON", '{"answer_points":["新要点"]}');
  await click("提交复验候选（负责人）");
  await posted(calls, "/validation-candidates", {
    batch_id: "b",
    unit_id: "u",
    final_gold: { answer_points: ["新要点"] },
    reason: "修订答案",
    verifier_id: "verifier-1",
  });
});
it("会议登记把参加人案例培训引用保持为数组并保存带时区时间", async () => {
  const calls = server();
  mount(<GovernanceForm path="/calibrations" />);
  fill("旧批次ID", "b");
  fill("会议时间", "2026-10-28T09:00");
  fill("参加人ID（每行一个）", "a\nb");
  fill("争议案例引用（每行一个）", "u1\nu2");
  fill("会议决定", "完整重标");
  fill("校准手册版本", "manual2");
  fill("培训材料引用（每行一个）", "training:1");
  fill("重标与校准理由", "低κ校准");
  await click("登记校准会议与培训记录");
  await posted(calls, "/calibrations", {
    participant_ids: ["a", "b"],
    case_refs: ["u1", "u2"],
    training_refs: ["training:1"],
  });
  expect(await screen.findByRole("status")).toHaveTextContent("已登记");
});
it("资格登记记录不可用状态和真实批准依据", async () => {
  const calls = server();
  mount(<GovernanceForm path="/qualifications" />);
  fill("人员账号ID", "a");
  fill("资格数据集", "SEC-D1");
  fireEvent.click(screen.getByLabelText("当前可排班"));
  fill("资格有效至", "2027-01-01T09:00");
  fill("资格批准依据 JSON", '{"ref":"training:sec"}');
  fill("资格登记理由", "完成培训");
  await click("登记人员资格与可用性");
  await posted(calls, "/qualifications", {
    user_id: "a",
    dataset: "SEC-D1",
    available: false,
    evidence: { ref: "training:sec" },
  });
});
it("本人材料工单有独立类型理由且不会创建对方反馈", async () => {
  const calls = server();
  mount(<MaterialIssueForm assignmentId="mine" contexts={[]} />);
  await click("报告材料问题");
  fill("问题类型", "INSUFFICIENT_SCOPE");
  fill("问题描述", "缺少授权范围");
  await click("登记材料问题");
  await posted(calls, "/work-issues", {
    assignment_id: "mine",
    issue_type: "INSUFFICIENT_SCOPE",
    reason: "缺少授权范围",
    locators: [],
  });
  expect(await screen.findByRole("status")).toHaveTextContent("服务端暂停");
});
it("独立处置关联受控新revision而不原位恢复变更材料", async () => {
  const calls = server({
    "/work-issues": {
      items: [
        {
          id: "issue",
          issue_type: "MISSING_SOURCE",
          status: "OPEN",
          version: 7,
          unit_id: "u",
        },
      ],
      total: 1,
    },
  });
  mount(<IssuesPage />);
  fill("处置理由", "补充新材料");
  fill("处置方式", "NEW_REVISION");
  fill("新revision引用", "source-r2");
  await click("独立处置问题");
  await posted(calls, "/work-issues/issue/resolve", {
    version: 7,
    disposition: "NEW_REVISION",
    revision_ref: "source-r2",
    reason: "补充新材料",
  });
});
const batch = { id: "b", state: "BLIND_OPEN", version: 4 } as AnnotationBatch;
const user = {
  id: "new",
  display_name: "新人",
  person_id: "p-new",
  roles: ["annotator"],
  active: true,
} as User;
it("整席补派提交席位新人及乐观版本，REVIEW阶段禁止原位补派", async () => {
  const calls = server({ "/users": { items: [user], total: 1 } });
  mount(<BatchLifecycle batch={batch} />);
  fill("操作依据", "原人员不可用");
  await screen.findByRole("option", { name: "新人 · p-new" });
  fill("替换席位", "B");
  fill("新标注员", "new");
  await click("补派整个席位");
  await posted(calls, "/annotation-batches/b/replace-seat", {
    seat: "B",
    new_annotator_id: "new",
    version: 4,
    reason: "原人员不可用",
  });
  await click("暂停批次");
  await posted(calls, "/annotation-batches/b/pause", { version: 4 });
});
it("暂停后恢复提交原因版本而不自行变更质量门", async () => {
  const calls = server();
  mount(<BatchLifecycle batch={{ ...batch, state: "PAUSED" }} />);
  fill("操作依据", "材料核对无变更");
  await click("核对后恢复");
  await posted(calls, "/annotation-batches/b/resume", { version: 4 });
  expect(screen.getByRole("button", { name: "补派整个席位" })).toBeDisabled();
});
it("本人提醒可标已读并使用分页total而不是当前页条数", async () => {
  const calls = server({
    "/notifications": {
      items: [
        {
          id: "n",
          kind: "DUE",
          payload: { assignment_id: "mine" },
          created_at: "2026-10-28T00:00:00Z",
          read_at: null,
        },
      ],
      total: 51,
    },
  });
  mount(<NotificationsPage />);
  await click("标为已读");
  await posted(calls, "/notifications/n/read", {});
  await click("下一页");
  await waitFor(() =>
    expect(screen.getByText("共51条 · 第2页")).toBeInTheDocument(),
  );
  await click("上一页");
});
it("交付登记绑定快照接收方证据和幂等键，下载不自动发送", async () => {
  const calls = server();
  mount(<HandoffSending id="h" snapshotHash={"a".repeat(64)} />);
  expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  expect(
    screen.getByRole("link", { name: "下载受控原始复算资料" }),
  ).toHaveAttribute("href", "/api/s4/v1/handoffs/h/evidence");
  fill("接收方引用", "manual:reviewer");
  fill("实际交付证据引用", "evidence:handoff");
  fill("交付证据SHA-256", "b".repeat(64));
  await click("登记已发送证据");
  await posted(calls, "/handoffs/h/sent", {
    snapshot_hash: "a".repeat(64),
    destination_ref: "manual:reviewer",
    evidence: {
      kind: "manual_delivery",
      reference: "evidence:handoff",
      sha256: "b".repeat(64),
    },
  });
});
it("对账操作展示真实运行与发现并提交后台job", async () => {
  const calls = server({
    "/operations": { queue: { pending: 3 } },
    "/reconciliations": {
      items: [
        {
          id: "r",
          state: "SUCCEEDED",
          summary: { count: 1 },
          created_at: "2026-10-28T00:00:00Z",
        },
      ],
      total: 1,
    },
    "/reconciliations/r/findings": {
      items: [
        {
          id: "f",
          kind: "MISSING_RECEIPT",
          severity: "warning",
          status: "OPEN",
          object_id: "h",
          details: { reason: "no receipt" },
        },
      ],
      total: 1,
    },
    "/jobs/j1": {
      id: "j1",
      state: "SUCCEEDED",
      kind: "RECONCILE",
      attempts: 1,
    },
  });
  mount(<OperationsPanel />);
  fireEvent.click(await screen.findByText(/SUCCEEDED · r/));
  expect(await screen.findByText("MISSING_RECEIPT")).toBeInTheDocument();
  await click("运行对账");
  await posted(calls, "/reconciliations", {});
});
it("治理入口的四个tab保留独立可操作表单", async () => {
  server();
  mount(<GovernancePage />);
  await click("校准会议");
  expect(screen.getByLabelText("旧批次ID")).toBeInTheDocument();
  await click("人员资格");
  expect(screen.getByLabelText("人员账号ID")).toBeInTheDocument();
  await click("独立复验");
  expect(screen.getByLabelText("复验单元ID")).toBeInTheDocument();
  await click("材料问题");
  expect(screen.getByLabelText("处置理由")).toBeInTheDocument();
});
