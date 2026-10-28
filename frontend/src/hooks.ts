import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import type { ListResult } from "./types";

export function useList<T>(path: string, enabled = true) {
  return useQuery({
    queryKey: [path],
    queryFn: async ({ signal }) => {
      const [base, query = ""] = path.split("?");
      const params = new URLSearchParams(query);
      // Pages with their own controls keep one server page in the cache.
      if (params.has("offset") || params.has("limit"))
        return api<ListResult<T>>(path, { signal });
      const items: T[] = [];
      let total = 0;
      do {
        params.set("offset", String(items.length));
        params.set("limit", "500");
        const page = await api<ListResult<T>>(`${base}?${params}`, { signal });
        if (
          !Array.isArray(page.items) ||
          !Number.isInteger(page.total) ||
          page.total < 0
        )
          throw new Error("服务返回的分页列表无效，请刷新后重试。");
        total = page.total;
        if (!page.items.length && items.length < total)
          throw new Error("分页范围已变化，请刷新后重试，当前未显示部分结果。");
        items.push(...page.items);
      } while (items.length < total);
      return { items, total };
    },
    enabled,
    refetchInterval: 15000,
  });
}

export function useCommand() {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [success, setSuccess] = useState("");
  async function run<T>(
    path: string,
    body: unknown = {},
    method = "POST",
    headers?: HeadersInit,
  ): Promise<T | undefined> {
    setPending(true);
    setError(null);
    setSuccess("");
    try {
      const value = await api<T>(path, { method, body, headers });
      await queryClient.invalidateQueries();
      return value;
    } catch (failure) {
      setError(failure instanceof Error ? failure : new Error("操作失败"));
      return undefined;
    } finally {
      setPending(false);
    }
  }
  return { run, pending, error, success, setSuccess };
}
