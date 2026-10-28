import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { TasksPage } from "../pages/Tasks";
import type { Task } from "../types";
afterEach(() => vi.unstubAllGlobals());
it("超过500条的本人任务真实读取后续页，第二页任务保持可访问", async () => {
  const calls: string[] = [];
  const makeTask = (i: number): Task => ({
    id: `a${i}`,
    unit_id: `unit-${i}`,
    batch_id: "batch",
    dataset: "QA-D1",
    phase: "BLIND",
    status: "PENDING",
    content_revision: "r",
    profile_version: "v2",
  });
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      calls.push(url);
      const offset = Number(
        new URL(url, "http://test").searchParams.get("offset") ?? 0,
      );
      return Promise.resolve(
        new Response(
          JSON.stringify({
            items:
              offset === 0
                ? Array.from({ length: 500 }, (_, i) => makeTask(i))
                : [makeTask(500)],
            total: 501,
            offset,
            limit: 500,
          }),
          { status: 200 },
        ),
      );
    }),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <TasksPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByText("unit-500")).toBeInTheDocument();
  expect(
    calls.some(
      (url) => new URL(url, "http://test").searchParams.get("offset") === "500",
    ),
  ).toBe(true);
  expect(screen.getAllByRole("link", { name: "进入作业" })).toHaveLength(501);
});
