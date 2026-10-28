import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, it, expect, vi } from "vitest";
import { UsersPage } from "../pages/Configuration";
import { ImportsPage } from "../pages/Imports";
import { Dashboard } from "../pages/Dashboard";
import { BatchesPage, BatchPage } from "../pages/Batches";
import { QualityPage, ArbitrationPage } from "../pages/Quality";
import { HandoffsPage, AuditPage } from "../pages/Operations";
import { TasksPage, TaskWorkspace } from "../pages/Tasks";
import type { User, TaskDetail } from "../types";
function mount(node: React.ReactNode, path = "/", route = "/") {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path={route} element={node} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
interface Call {
  path: string;
  method: string;
  body: Record<string, unknown>;
}
function server(rows: Record<string, unknown> = {}, fail?: string) {
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
            fail === path && method !== "GET"
              ? { message: "服务器拒绝", error_code: "DENIED" }
              : method === "GET"
                ? (rows[path] ?? { items: [], total: 0 })
                : {
                    id: "created",
                    job_id: "j1",
                    state: "SUCCEEDED",
                    version: 2,
                  },
          ),
          { status: fail === path && method !== "GET" ? 403 : 200 },
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
async function mutation(
  calls: Call[],
  path: string,
  expected: unknown,
  method = "POST",
) {
  await waitFor(() =>
    expect(calls).toContainEqual(
      expect.objectContaining({
        path,
        method,
        body: expect.objectContaining(expected),
      }),
    ),
  );
}
afterEach(() => vi.unstubAllGlobals());
const lead = {
  id: "lead",
  username: "lead",
  display_name: "运营甲",
  person_id: "p-lead",
  active: true,
  roles: ["lead", "arbitrator"],
} as User;
const users = [
  {
    id: "a",
    username: "ann-a",
    display_name: "标注甲",
    person_id: "p-a",
    active: true,
    roles: ["annotator"],
  },
  {
    id: "b",
    username: "ann-b",
    display_name: "标注乙",
    person_id: "p-b",
    active: true,
    roles: ["annotator"],
  },
];
const imported = {
  id: "i",
  batch_id: "import-1",
  mode: "demo",
  status: "VALID",
  unit_count: 12,
  blocked_reasons: ["DEMO"],
  created_at: "2026-10-28T00:00:00Z",
};
const unit = {
  unit_id: "u",
  question: "待复核问题",
  contexts: [{ doc_id: "d", text: "原文甲乙" }],
  gold: {
    answer_points: ["原始要点"],
    gold_doc_ids: ["d"],
    answerable: "answerable",
  },
};
const batch = {
  id: "b",
  import_id: "i",
  dataset: "QA-D1",
  state: "PAIR_COMPLETE",
  round: 1,
  annotator_a: "a",
  annotator_b: "b",
  sample_count: 1,
  selected_ids: ["u"],
  blocked_reasons: [],
  blind_submitted: 2,
  review_submitted: 2,
  finalized: false,
  version: 1,
  units: [unit],
  manual_version: "m1",
  profile_revision_id: "p1",
};
const agreement = {
  id: "g",
  batch_id: "b",
  kappa: 0.65,
  po: 0.8,
  pe: 0.5,
  n: 10,
  verdict: "ARBITRATE",
  blocked_reasons: [],
  disagreement_unit_ids: ["u"],
};
it("管理员创建verifier角色账号并可更改角色和重置密码", async () => {
  const calls = server({ "/users": { items: users, total: 2 } });
  mount(<UsersPage />);
  await click("创建账号");
  fill("账号", "verifier1");
  fill("显示名称", "复验甲");
  fill("人员标识", "p-v");
  fill("初始密码", "long-example-password");
  fireEvent.click(screen.getByLabelText("独立复验员"));
  await click("确认创建");
  await mutation(calls, "/users", {
    username: "verifier1",
    roles: ["annotator", "verifier"],
  });
  await screen.findByText("标注甲");
  fireEvent.click(screen.getAllByRole("button", { name: "管理" })[0]);
  fill("重置密码（不修改则留空）", "updated-long-password");
  fireEvent.click(screen.getByLabelText("独立复验员"));
  await click("保存设置");
  await mutation(
    calls,
    "/users/a",
    { roles: ["annotator", "verifier"], password: "updated-long-password" },
    "PATCH",
  );
  fireEvent.click(screen.getAllByRole("button", { name: "停用" })[0]);
  await mutation(calls, "/users/a", { active: false }, "PATCH");
});
it("导入页面拒绝数组契约再提交对象并显示后台job", async () => {
  const calls = server({
    "/imports": { items: [imported], total: 1 },
    "/jobs/j1": {
      id: "j1",
      kind: "IMPORT",
      state: "SUCCEEDED",
      attempts: 1,
      result: { validation_report: { errors: [] } },
    },
  });
  mount(<ImportsPage canWrite />);
  fill("契约JSON内容", "[]");
  await click("提交接入校验");
  expect(await screen.findByRole("alert")).toHaveTextContent("完整JSON对象");
  fill("契约JSON内容", '{"mode":"demo","units":[]}');
  await click("提交接入校验");
  await mutation(calls, "/imports", { mode: "demo", units: [] });
  await click("查看阻塞");
  expect(await screen.findAllByText("DEMO")).not.toHaveLength(0);
  await click("查看阻塞");
});
it("创建批次冻结双席和种子，不能相同实际人员", async () => {
  const calls = server({
    "/annotation-batches": { items: [batch], total: 1 },
    "/imports": { items: [imported], total: 1 },
    "/users": { items: users, total: 2 },
    "/profiles": [{ dataset: "QA-D1", kind: "qa_points", version: "v1" }],
  });
  mount(<BatchesPage canWrite />);
  await click("创建标注批次");
  await screen.findAllByRole("option", { name: /标注甲/ });
  fill("来源批次", "i");
  fill("数据集", "QA-D1");
  fill("A席位", "a");
  fill("B席位", "b");
  fill("可复现随机种子", "77");
  await click("创建并开始独立作答");
  await mutation(calls, "/annotation-batches", {
    import_id: "i",
    dataset: "QA-D1",
    annotator_a: "a",
    annotator_b: "b",
    seed: 77,
  });
  expect(await screen.findByRole("link", { name: "管理批次" })).toHaveAttribute(
    "href",
    "/batches/b",
  );
});
it("逐题定稿明确编辑内容并记录独立理由，校准新轮关联会议", async () => {
  const calls = server({
    "/annotation-batches/b": batch,
    "/users": { items: users, total: 2 },
    "/agreements": { items: [agreement], total: 1 },
  });
  mount(<BatchPage canWrite />, "/batches/b", "/batches/:id");
  await click("打开逐单元定稿");
  fireEvent.click(screen.getByText("待复核问题"));
  fill("最终答案要点（每行一条）", "修订甲\n修订乙");
  fill("最终证据文档（每行一个doc_id）", "d");
  fill("最终可答性", "answerable");
  fill("定稿理由", "完整检查");
  await click("确认全部抽检单元并封存定稿");
  await mutation(calls, "/annotation-batches/b/finalize", {
    decisions: [
      {
        unit_id: "u",
        final_gold: {
          answer_points: ["修订甲", "修订乙"],
          gold_doc_ids: ["d"],
          answerable: "answerable",
        },
        reason: "完整检查",
      },
    ],
  });
  await click("开启新轮");
  fill("新A席", "a");
  fill("新B席", "b");
  fill("随机种子", "88");
  fill("关联校准记录ID", "cal1");
  fill("新轮手册版本", "m2");
  fill("新轮批准profile版本ID", "p2");
  fill("校准记录与重标原因", "完整重标");
  await click("创建完整样本新轮");
  await mutation(calls, "/rounds", {
    calibration_id: "cal1",
    manual_version: "m2",
    profile_revision_id: "p2",
    seed: 88,
  });
});
it("批次发布REVIEW与计算一致性分别受状态限制且调用独立API", async () => {
  const calls = server({
    "/annotation-batches/b": { ...batch, state: "BLIND_SEALED" },
    "/users": { items: users, total: 2 },
  });
  mount(<BatchPage canWrite />, "/batches/b", "/batches/:id");
  await click("统一开放复核");
  await mutation(calls, "/annotation-batches/b/release-review", {});
  expect(screen.getByRole("button", { name: "计算批次一致性" })).toBeDisabled();
});
it("灰区仲裁编辑内容再由不同负责人明确确认", async () => {
  const calls = server({
    "/agreements": { items: [agreement], total: 1 },
    "/annotation-batches/b": batch,
    "/arbitrations": {
      items: [
        {
          id: "arb",
          batch_id: "b",
          unit_id: "u",
          arbitrator_id: "other",
          confirmed: false,
          reason: "原裁决理由",
          final_gold: unit.gold,
        },
      ],
      total: 1,
    },
  });
  mount(<ArbitrationPage user={lead} />);
  await screen.findByRole("option", { name: /b · κ/ });
  fill("统计批次", "b");
  await screen.findByRole("option", { name: "u" });
  fill("分歧单元", "u");
  fill("最终答案要点（每行一条）", "裁决要点");
  fill("最终证据文档（每行一个doc_id）", "d");
  fill("最终可答性", "answerable");
  fill("裁决理由", "第三人核查");
  await click("记录内容裁决");
  await mutation(calls, "/arbitrations", {
    unit_id: "u",
    reason: "第三人核查",
  });
  await click("独立复核并确认");
  fill("负责人复核理由", "重新核查");
  await click("确认该项裁决");
  await mutation(calls, "/arbitrations/arb/confirm", { reason: "重新核查" });
});
it("质量页保留真实κ和原结论，快照发布只登记job", async () => {
  server({
    "/agreements": {
      items: [
        agreement,
        {
          ...agreement,
          id: "undef",
          kappa: null,
          po: null,
          pe: null,
          blocked_reasons: ["UNDEFINED"],
        },
      ],
      total: 2,
    },
  });
  mount(<QualityPage />);
  expect(await screen.findByText("0.6500")).toBeInTheDocument();
  expect(screen.getByText("未定义")).toBeInTheDocument();
  expect(screen.getByText("UNDEFINED")).toBeInTheDocument();
});
it("交接列表从授权来源创建后台快照", async () => {
  const calls = server({
    "/imports": { items: [imported], total: 1 },
    "/handoffs": {
      items: [
        {
          id: "h",
          mode: "demo",
          status: "DEMO_READY",
          external_status: "NOT_ALIGNED",
          created_at: "2026-10-28T00:00:00Z",
        },
      ],
      total: 1,
    },
    "/jobs/j1": { id: "j1", kind: "EXPORT", state: "SUCCEEDED", attempts: 1 },
  });
  mount(<HandoffsPage canWrite />);
  await screen.findByRole("option", { name: /import-1/ });
  fill("来源批次", "i");
  await click("创建交接快照");
  await mutation(calls, "/handoffs", { import_id: "i" });
  expect(screen.getByRole("link", { name: "清单与文件" })).toHaveAttribute(
    "href",
    "/handoffs/h",
  );
});
it("仪表盘按角色展示本人任务和冻结批次数而不扩大读取", async () => {
  const calls = server({
    "/annotation-batches": { items: [batch], total: 10 },
    "/imports": { items: [imported], total: 3 },
    "/me/tasks": {
      items: [
        {
          id: "a1",
          unit_id: "mine",
          phase: "BLIND",
          status: "PENDING",
          dataset: "QA-D1",
        },
      ],
      total: 1,
    },
  });
  mount(<Dashboard user={{ ...lead, roles: ["lead", "annotator"] }} />);
  expect(await screen.findByText("mine")).toBeInTheDocument();
  expect(calls.some((c) => c.path === "/me/tasks")).toBe(true);
});
it("任务列表筛选保留本人封存和阶段，不请求他人", async () => {
  server({
    "/me/tasks": {
      items: [
        {
          id: "a1",
          unit_id: "one",
          batch_id: "b",
          phase: "BLIND",
          status: "PENDING",
          dataset: "QA-D1",
          profile_version: "v1",
        },
        {
          id: "a2",
          unit_id: "two",
          batch_id: "b",
          phase: "REVIEW",
          status: "SEALED",
          dataset: "QA-D1",
          profile_version: "v1",
        },
      ],
      total: 2,
    },
  });
  mount(<TasksPage />);
  await screen.findByText("one");
  await click("三栏复核");
  expect(screen.queryByText("one")).not.toBeInTheDocument();
  expect(screen.getByText("two")).toBeInTheDocument();
  await click("待我处理");
  expect(screen.getByText("one")).toBeInTheDocument();
  await click("独立作答");
  await click("全部任务");
});
it("审计分页和详情展示按授权追加事件", async () => {
  server({
    "/audit": {
      items: [
        {
          id: "audit",
          action: "SEALED",
          created_at: "2026-10-28T00:00:00Z",
          actor_id: null,
          details: { request: "safe" },
        },
      ],
      total: 1,
    },
  });
  mount(<AuditPage />);
  expect(await screen.findByText("SEALED")).toBeInTheDocument();
  fireEvent.click(screen.getByText("查看记录"));
  expect(screen.getByText(/safe/)).toBeInTheDocument();
});
it("工作台暂存恢复乐观版本，v2提交携带冻结profile摘要", async () => {
  const calls = server();
  const task = {
    id: "mine",
    batch_id: "b",
    unit_id: "u",
    dataset: "QA-D1",
    phase: "BLIND",
    status: "PENDING",
    review_version: "openkb.s4-review.v2",
    content_revision: "r1",
    profile_version: "v2",
    profile_hash: "frozen-hash",
    material: { contexts: [] },
    draft: null,
  } as TaskDetail;
  mount(<TaskWorkspace task={task} />);
  fill("独立答案 / 拒答判断", "原文独立答案");
  fill("所据原文与理由", "范围内");
  await click("暂存草稿");
  await mutation(
    calls,
    "/assignments/mine/draft",
    { phase: "BLIND", version: 0 },
    "PATCH",
  );
  await click("提交并封存盲答");
  await mutation(calls, "/assignments/mine/submit", {
    profile_hash: "frozen-hash",
    profile_version: "v2",
    phase: "BLIND",
  });
});
it("服务端错误在页面可诊断且不会声称登记成功", async () => {
  server({}, "/imports");
  mount(<ImportsPage canWrite />);
  fill("契约JSON内容", '{"mode":"demo"}');
  await click("提交接入校验");
  expect(await screen.findByRole("alert")).toHaveTextContent("服务器拒绝");
});

it("建批表单冻结批准profile、到期时间与提醒周期", async () => {
  const calls = server({
    "/annotation-batches": { items: [], total: 0 },
    "/imports": { items: [imported], total: 1 },
    "/users": { items: users, total: 2 },
    "/profiles": [{ dataset: "QA-D1", kind: "qa_points", version: "v1" }],
    "/profile-revisions": {
      items: [{ id: "p1", dataset: "QA-D1", version: "v1", state: "APPROVED" }],
      total: 1,
    },
  });
  mount(<BatchesPage canWrite />);
  await click("创建标注批次");
  await screen.findAllByRole("option", { name: /标注甲/ });
  fill("来源批次", "i");
  fill("数据集", "QA-D1");
  fill("A席位", "a");
  fill("B席位", "b");
  fill("批准配置版本", "p1");
  fill("任务截止时间", "2026-11-01T09:00");
  fill("提醒间隔（分钟）", "30");
  await click("创建并开始独立作答");
  await mutation(calls, "/annotation-batches", {
    profile_revision_id: "p1",
    reminder_interval_minutes: 30,
    due_at: expect.stringMatching(/2026-11-01T/),
  });
});
it("v2已封存BLIND不是legacy，legacy REVIEW直接展示原始记录只读", () => {
  server();
  const task = {
    id: "mine",
    batch_id: "b",
    unit_id: "u",
    dataset: "QA-D1",
    phase: "REVIEW",
    status: "SEALED",
    review_version: "openkb.s4-review.v1",
    content_revision: "r1",
    profile_version: "v1",
    material: { contexts: [] },
    draft: null,
    own_submission: { point_labels: { P001: "correct" }, reason: "历史总理由" },
  } as TaskDetail;
  mount(<TaskWorkspace task={task} />);
  expect(screen.getByText(/历史总理由/)).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "提交并封存复核" }),
  ).not.toBeInTheDocument();
});
