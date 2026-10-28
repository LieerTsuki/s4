import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, setCsrfToken } from "../api";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

describe("API边界", () => {
  it("写请求发送会话Cookie和CSRF令牌", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "one" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetcher);
    setCsrfToken("csrf-test");
    await api("/users", { method: "POST", body: { username: "a" } });
    const options = fetcher.mock.calls[0][1] as RequestInit;
    expect(options.credentials).toBe("include");
    expect(new Headers(options.headers).get("X-CSRF-Token")).toBe("csrf-test");
  });

  it("将后端拒绝保留为带请求标识的错误，禁止静默返回空数组", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error_code: "NO_ACCESS",
            message: "无权访问",
            request_id: "req-1",
          }),
          { status: 403 },
        ),
      ),
    );
    await expect(api("/audit")).rejects.toEqual(
      expect.objectContaining<ApiError>({
        name: "ApiError",
        message: "无权访问",
        status: 403,
        code: "NO_ACCESS",
        requestId: "req-1",
      }),
    );
  });

  it("清空CSRF后下一个身份不会沿用上一人的令牌", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    setCsrfToken("old-user");
    setCsrfToken(null);
    await api("/auth/login", {
      method: "POST",
      body: { username: "b", password: "new-password" },
    });
    expect(
      new Headers(fetcher.mock.calls[0][1].headers).has("X-CSRF-Token"),
    ).toBe(false);
  });
});
