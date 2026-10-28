import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "../App";

afterEach(() => vi.unstubAllGlobals());
function mount(path = "/") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}
it("未登录只校验会话，不预加载批次、原文或统计", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(
      new Response(
        JSON.stringify({ error_code: "UNAUTHENTICATED", message: "请登录" }),
        { status: 401 },
      ),
    );
  vi.stubGlobal("fetch", fetcher);
  mount();
  expect(
    await screen.findByRole("button", { name: "登录工作台" }),
  ).toBeInTheDocument();
  expect(fetcher.mock.calls.map((call) => call[0])).toEqual([
    "/api/s4/v1/auth/me",
  ]);
});
it("标注员直接访问账号管理被拒绝，不发出账号列表请求", async () => {
  const fetcher = vi.fn().mockImplementation(() =>
    Promise.resolve(
      new Response(
        JSON.stringify({
          user: {
            id: "a",
            username: "a",
            display_name: "标注员甲",
            person_id: "person-a",
            roles: ["annotator"],
            active: true,
          },
          csrf_token: "token-a",
        }),
        { status: 200 },
      ),
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  mount("/users");
  expect(await screen.findByText("此账号无权访问该页面")).toBeInTheDocument();
  expect(
    fetcher.mock.calls.some((call) =>
      String(call[0]).split("?")[0].endsWith("/users"),
    ),
  ).toBe(false);
});
it("退出登录移除题目缓存并回到登录页", async () => {
  const fetcher = vi.fn().mockImplementation((path: string) =>
    Promise.resolve(
      new Response(
        JSON.stringify(
          path.endsWith("/auth/logout")
            ? {}
            : path.endsWith("/auth/me")
              ? {
                  user: {
                    id: "a",
                    username: "a",
                    display_name: "标注员甲",
                    person_id: "person-a",
                    roles: ["annotator"],
                    active: true,
                  },
                  csrf_token: "token-a",
                }
              : { items: [], total: 0 },
        ),
        { status: 200 },
      ),
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  const client = mount("/tasks");
  await screen.findByText("标注员甲");
  client.setQueryData(["secret-material"], { question: "受控原文" });
  await userEvent.click(screen.getByRole("button", { name: "退出登录" }));
  expect(
    await screen.findByRole("button", { name: "登录工作台" }),
  ).toBeInTheDocument();
  expect(client.getQueryData(["secret-material"])).toBeUndefined();
});
