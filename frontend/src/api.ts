export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public requestId: string,
    public details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
let csrfToken: string | null = null;
export const API_ROOT = "/api/s4/v1";
export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export async function api<T>(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    headers?: HeadersInit;
    signal?: AbortSignal;
  } = {},
): Promise<T> {
  const method = options.method ?? "GET";
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (options.body !== undefined)
    headers.set("Content-Type", "application/json");
  if (method !== "GET" && method !== "HEAD" && csrfToken)
    headers.set("X-CSRF-Token", csrfToken);
  let response: Response;
  try {
    response = await fetch(`${API_ROOT}${path}`, {
      method,
      credentials: "include",
      headers,
      body:
        options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
      cache: "no-store",
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ApiError(
      0,
      "NETWORK_ERROR",
      "无法连接服务，请检查网络与后端状态。",
      "",
    );
  }
  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      throw new ApiError(
        response.status,
        "INVALID_RESPONSE",
        "服务返回了无法识别的响应。",
        response.headers.get("X-Request-Id") ?? "",
      );
    }
  }
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/auth/"))
      window.dispatchEvent(new Event("s4-session-expired"));
    const error =
      data && typeof data === "object" ? (data as Record<string, unknown>) : {};
    throw new ApiError(
      response.status,
      String(error.error_code ?? "REQUEST_FAILED"),
      typeof error.message === "string"
        ? error.message
        : `请求未完成（${response.status}）`,
      String(error.request_id ?? response.headers.get("X-Request-Id") ?? ""),
      error.details &&
        typeof error.details === "object" &&
        !Array.isArray(error.details)
        ? (error.details as Record<string, unknown>)
        : undefined,
    );
  }
  return data as T;
}
