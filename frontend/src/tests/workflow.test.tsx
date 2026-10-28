import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { BatchPage } from "../pages/Batches";
import { HandoffPage, HealthPage } from "../pages/Operations";
import { TaskPage, TaskWorkspace } from "../pages/Tasks";
import type { TaskDetail } from "../types";

afterEach(() => vi.unstubAllGlobals());
function mount(node: React.ReactNode, path = "/", route = "/") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path={route} element={node} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
it("批次详情从独立统计接口展示未定义κ与向量摘要", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((path: string) =>
      Promise.resolve(
        new Response(
          JSON.stringify(
            path.split("?")[0].endsWith("/agreements")
              ? {
                  items: [
                    {
                      id: "g1",
                      batch_id: "b1",
                      kappa: null,
                      n: 8,
                      po: 1,
                      pe: 1,
                      verdict: "BLOCKED",
                      blocked_reasons: ["UNDEFINED_KAPPA_PE_ONE"],
                      vector_a: ["correct"],
                      vector_b: ["correct"],
                    },
                  ],
                  total: 1,
                }
              : {
                  id: "b1",
                  import_id: "i1",
                  dataset: "QA-D1",
                  state: "PAIR_COMPLETE",
                  round: 1,
                  selected_ids: ["u1"],
                  sample_count: 1,
                  blind_submitted: 2,
                  review_submitted: 2,
                  blocked_reasons: [],
                  finalized: false,
                },
          ),
          { status: 200 },
        ),
      ),
    ),
  );
  mount(<BatchPage canWrite={false} />, "/batches/b1", "/batches/:id");
  expect(await screen.findByText("原始一致性结论")).toBeInTheDocument();
  expect(screen.getByText("未定义")).toBeInTheDocument();
  expect(screen.getByText("UNDEFINED_KAPPA_PE_ONE")).toBeInTheDocument();
});
it("交接清单按后端line_count显示真实数量和受控下载链接", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "h1",
          import_id: "i1",
          mode: "demo",
          status: "DEMO_READY",
          external_status: "NOT_ALIGNED",
          blocked_reasons: [],
          created_at: "2026-10-27T00:00:00Z",
          manifest: {
            unit_count: 10,
            sample_count: 8,
            files: {
              "units_for_s5.jsonl": { sha256: "abc123", line_count: 10 },
            },
          },
        }),
        { status: 200 },
      ),
    ),
  );
  mount(<HandoffPage />, "/handoffs/h1", "/handoffs/:id");
  expect(await screen.findByRole("cell", { name: "10" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "下载文件" })).toHaveAttribute(
    "href",
    "/api/s4/v1/handoffs/h1/files/units_for_s5.jsonl",
  );
});
it("BLIND工作台只显示原文和独立作答表单，载荷保持静态文本", () => {
  const task = {
    id: "a1",
    batch_id: "b1",
    unit_id: "u1",
    dataset: "QA-D1",
    phase: "BLIND",
    status: "PENDING",
    content_revision: "r1",
    profile_version: "v1",
    material: {
      question: "什么是范围？",
      payload: "<img src=x onerror=alert(1)>",
      contexts: [{ doc_id: "d1", text: "授权原文" }],
    },
    draft: null,
  } satisfies TaskDetail;
  mount(<TaskWorkspace task={task} />);
  expect(screen.getByLabelText("独立答案 / 拒答判断")).toBeInTheDocument();
  expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  expect(screen.queryByText("逐点核对正确性")).not.toBeInTheDocument();
});
it("逐文档保留有效期、版本、定位与权限背景，权限载荷作为静态文字", () => {
  const task: TaskDetail = {
    id: "a1",
    batch_id: "b1",
    unit_id: "u1",
    dataset: "QA-D1",
    phase: "BLIND",
    status: "PENDING",
    content_revision: "r1",
    profile_version: "v1",
    material: {
      question: "判断时效和阅读边界",
      contexts: [
        {
          doc_id: "d1",
          title: "文档甲",
          text: "甲原文",
          valid_from: "2026-01-01",
          valid_until: "2026-10-01",
          version: "doc-v3",
          license: "CC-BY-4.0",
          source_url: "javascript:alert(1)",
          sha256: "frozen-doc-sha256",
          page: 12,
          start: 0,
          end: 300,
          acl_context: "<img src=x onerror=alert(1)>",
        },
        { doc_id: "d2", title: "文档乙", text: "乙原文", version: "doc-v4" },
      ],
    },
    draft: null,
  };
  mount(<TaskWorkspace task={task} />);
  const first = within(screen.getByText("文档甲").closest("details")!);
  const second = within(screen.getByText("文档乙").closest("details")!);
  for (const value of [
    "有效起始",
    "2026-01-01",
    "有效截止",
    "2026-10-01",
    "文档版本",
    "doc-v3",
    "页码",
    "12",
    "起始位置",
    "0",
    "终止位置",
    "300",
    "权限背景",
    "<img src=x onerror=alert(1)>",
    "许可",
    "CC-BY-4.0",
    "来源地址",
    "javascript:alert(1)",
    "原文SHA-256",
    "frozen-doc-sha256",
  ])
    expect(first.getByText(value)).toBeInTheDocument();
  expect(first.queryByRole("link")).not.toBeInTheDocument();
  expect(second.getByText("doc-v4")).toBeInTheDocument();
  expect(second.queryByText("2026-10-01")).not.toBeInTheDocument();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
});
it("专项工作台展示服务端阶段投影的chunk和质量指标", () => {
  const task: TaskDetail = {
    id: "a1",
    batch_id: "b1",
    unit_id: "u1",
    dataset: "QA-D6",
    phase: "REVIEW",
    status: "PENDING",
    content_revision: "r1",
    profile_version: "v1",
    material: {
      contexts: [],
      chunk: { text: "待核对分块原文" },
      quality_metrics: { completeness: 0.9 },
      access_context: "受控权限范围",
      inject_plan: "静态注入计划",
    },
    draft: null,
  };
  mount(<TaskWorkspace task={task} />);
  expect(screen.getByText("分块材料")).toBeInTheDocument();
  expect(screen.getByText(/待核对分块原文/)).toBeInTheDocument();
  expect(screen.getByText("质量指标草案")).toBeInTheDocument();
  expect(screen.getByText(/completeness/)).toBeInTheDocument();
});
it("授权批次显示按单元及point_key绑定的双人标签配对", async () => {
  const batch = {
    id: "b1",
    import_id: "i1",
    dataset: "QA-D1",
    state: "PAIR_COMPLETE",
    round: 1,
    selected_ids: ["u1"],
    sample_count: 1,
    blind_submitted: 2,
    review_submitted: 2,
    blocked_reasons: [],
    finalized: false,
    units: [
      {
        unit_id: "u1",
        gold: { answer_points: ["同一原始要点"] },
        contexts: [],
      },
    ],
    assignments: [
      { id: "aa", unit_id: "u1", seat: "A", user_id: "a" },
      { id: "ab", unit_id: "u1", seat: "B", user_id: "b" },
    ],
    submissions: [
      {
        assignment_id: "aa",
        phase: "REVIEW",
        payload: { point_labels: { P001: "correct" } },
      },
      {
        assignment_id: "ab",
        phase: "REVIEW",
        payload: { point_labels: { P001: "partial" } },
      },
    ],
  };
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockImplementation((path: string) =>
        Promise.resolve(
          new Response(
            JSON.stringify(
              path.includes("/annotation-batches/")
                ? batch
                : { items: [], total: 0 },
            ),
            { status: 200 },
          ),
        ),
      ),
  );
  mount(<BatchPage canWrite={false} />, "/batches/b1", "/batches/:id");
  expect(await screen.findByText("原始标签配对核查")).toBeInTheDocument();
  expect(screen.getByRole("cell", { name: "correct" })).toBeInTheDocument();
  expect(screen.getByRole("cell", { name: "partial" })).toBeInTheDocument();
  expect(screen.getByRole("cell", { name: "P001" })).toBeInTheDocument();
});
it("就绪检查503仍展示数据库与worker的真实诊断", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((path: string) =>
      Promise.resolve(
        new Response(
          JSON.stringify(
            path.endsWith("/live")
              ? { status: "alive" }
              : {
                  status: "not_ready",
                  database: true,
                  migration: "0001_s4",
                  worker: false,
                },
          ),
          { status: path.endsWith("/live") ? 200 : 503 },
        ),
      ),
    ),
  );
  mount(<HealthPage />);
  expect(await screen.findByText("心跳失效")).toBeInTheDocument();
  expect(screen.getByText("0001_s4")).toBeInTheDocument();
});
it("定稿表单沿用已确认仲裁的内容，保留独立定稿理由", async () => {
  const batch = {
    id: "b1",
    dataset: "QA-D1",
    state: "PAIR_COMPLETE",
    round: 1,
    selected_ids: ["u1"],
    sample_count: 1,
    blind_submitted: 2,
    review_submitted: 2,
    blocked_reasons: [],
    finalized: false,
    units: [
      {
        unit_id: "u1",
        question: "问题",
        contexts: [],
        gold: {
          answer_points: ["原始要点"],
          gold_doc_ids: [],
          answerable: "answerable",
        },
      },
    ],
  };
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((path: string) =>
      Promise.resolve(
        new Response(
          JSON.stringify(
            path.split("?")[0].endsWith("/arbitrations")
              ? {
                  items: [
                    {
                      id: "arb1",
                      batch_id: "b1",
                      unit_id: "u1",
                      confirmed: true,
                      final_gold: {
                        answer_points: ["已确认裁决要点"],
                        gold_doc_ids: [],
                        answerable: "answerable",
                      },
                    },
                  ],
                  total: 1,
                }
              : path.includes("/annotation-batches/")
                ? batch
                : { items: [], total: 0 },
          ),
          { status: 200 },
        ),
      ),
    ),
  );
  mount(<BatchPage canWrite />, "/batches/b1", "/batches/:id");
  await userEvent.click(
    await screen.findByRole("button", { name: "打开逐单元定稿" }),
  );
  expect(screen.getByDisplayValue("已确认裁决要点")).toBeInTheDocument();
  expect(screen.getByDisplayValue("已确认裁决要点")).toBeDisabled();
  expect(screen.getByLabelText("定稿理由")).toHaveValue("");
});
it("刷新任务后恢复服务端最新草稿并同步乐观版本", async () => {
  let version = 1;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            id: "a1",
            batch_id: "b1",
            unit_id: "u1",
            dataset: "QA-D1",
            phase: "BLIND",
            status: "PENDING",
            content_revision: "r1",
            profile_version: "v1",
            material: { question: "问题", contexts: [] },
            draft: {
              version,
              payload: {
                answer: version === 1 ? "旧草稿" : "另一窗口更新的草稿",
                reason: "依据",
              },
            },
          }),
          { status: 200 },
        ),
      ),
    ),
  );
  mount(<TaskPage />, "/tasks/a1", "/tasks/:id");
  expect(await screen.findByDisplayValue("旧草稿")).toBeInTheDocument();
  version = 2;
  await userEvent.click(screen.getByRole("button", { name: "刷新" }));
  expect(
    await screen.findByDisplayValue("另一窗口更新的草稿"),
  ).toBeInTheDocument();
});
