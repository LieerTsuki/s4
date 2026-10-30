import { api } from "../api";

type Options = Parameters<typeof api>[1];
export function apiV2<T>(path: string, options: Options = {}): Promise<T> {
  return api<T>(path, { ...options, version: "v2" });
}

export async function listV2<T>(path: string, signal?: AbortSignal): Promise<{items: T[]; total: number}> {
  const items: T[] = [];
  let total = 0;
  do {
    const page = await apiV2<{items: T[]; total: number}>(`${path}${path.includes("?") ? "&" : "?"}limit=500&offset=${items.length}`, {signal});
    if (!Array.isArray(page.items) || !Number.isInteger(page.total) || page.total < 0)
      throw new Error("服务返回的分页结果无效，请刷新后重试。");
    total = page.total;
    if (!page.items.length && items.length < total)
      throw new Error("分页范围发生变化，请刷新；当前结果尚不完整。");
    items.push(...page.items);
    if (!page.items.length) break;
  } while (items.length < total);
  return {items,total};
}
