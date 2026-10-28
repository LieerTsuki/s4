import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, it, expect, vi } from "vitest";
import { ProfilesPage } from "../pages/Configuration";
import { TaskWorkspace } from "../pages/Tasks";
import { HealthPage } from "../pages/Operations";
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
afterEach(() => vi.unstubAllGlobals());
it("配置页可登记版本草案并保留审批入口", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve(new Response("[]", { status: 200 })),
      ),
  );
  mount(<ProfilesPage />);
  expect(await screen.findByText("创建配置草案")).toBeInTheDocument();
});
it("BLIND缺材料能上报本人任务问题且不展示草案", () => {
  mount(
    <TaskWorkspace
      task={{
        id: "a",
        batch_id: "b",
        unit_id: "u",
        dataset: "QA-D1",
        phase: "BLIND",
        status: "PENDING",
        content_revision: "r",
        profile_version: "p",
        material: { contexts: [] },
        draft: null,
      }}
    />,
  );
  expect(screen.getByText("报告材料问题")).toBeInTheDocument();
  expect(screen.queryByText("逐点核对正确性")).not.toBeInTheDocument();
});
it("健康页包含实际运维指标与触发对账入口", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve(new Response("{}", { status: 200 })),
      ),
  );
  mount(<HealthPage />);
  expect(await screen.findByText("运行对账")).toBeInTheDocument();
});
