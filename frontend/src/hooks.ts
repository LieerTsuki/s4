import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api';
import type { ListResult } from './types';

export function useList<T>(path: string, enabled = true) {
  return useQuery({ queryKey: [path], queryFn: ({ signal }) => api<ListResult<T>>(path, { signal }), enabled, refetchInterval: 15000 });
}

export function useCommand() {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [success, setSuccess] = useState('');
  async function run<T>(path: string, body: unknown = {}, method = 'POST', headers?: HeadersInit): Promise<T | undefined> {
    setPending(true); setError(null); setSuccess('');
    try {
      const value = await api<T>(path, { method, body, headers });
      await queryClient.invalidateQueries();
      return value;
    } catch (failure) { setError(failure instanceof Error ? failure : new Error('操作失败')); return undefined; }
    finally { setPending(false); }
  }
  return { run, pending, error, success, setSuccess };
}
