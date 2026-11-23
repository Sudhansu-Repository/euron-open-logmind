"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { useCan } from "@/hooks/use-can";
import { api, unwrap } from "@/lib/api/client";
import type { UserIn, UserUpdate } from "@/lib/api/types";
import { useInvalidating } from "@/lib/mutation";
import { qk, STALE } from "@/lib/query-keys";

export function useOrg() {
  return useQuery({
    queryKey: qk.org,
    queryFn: () => unwrap(api.GET("/api/v1/org")),
    staleTime: STALE.config,
  });
}

export function useUpdateOrg() {
  return useInvalidating(
    (body: { name: string }) => unwrap(api.PATCH("/api/v1/org", { body })),
    [qk.org]
  );
}

/** People in the organization. Owner only on the API, so the query only runs for owners. */
export function useUsers() {
  const { allowed } = useCan("manageUsers");
  return useQuery({
    queryKey: qk.users,
    queryFn: () => unwrap(api.GET("/api/v1/users")),
    staleTime: STALE.config,
    enabled: allowed,
  });
}

export function useCreateUser() {
  return useInvalidating((body: UserIn) => unwrap(api.POST("/api/v1/users", { body })), [qk.users]);
}

export function useUpdateUser() {
  return useInvalidating(
    ({ id, body }: { id: string; body: UserUpdate }) =>
      unwrap(api.PATCH("/api/v1/users/{user_id}", { params: { path: { user_id: id } }, body })),
    [qk.users, qk.me]
  );
}

/** The append-only audit log, cursor paginated ("load more" follows next_cursor). */
export function useAuditLog(action: string) {
  return useInfiniteQuery({
    queryKey: qk.auditList(action),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/audit-log", {
          params: {
            query: { cursor: pageParam ?? undefined, limit: 50, action: action || undefined },
          },
        })
      ),
    getNextPageParam: (last) => last.next_cursor ?? null,
    staleTime: STALE.list,
  });
}

/** API readiness (the /readyz probe, rewritten to the API by next.config.ts). */
export function useReady() {
  return useQuery({
    queryKey: qk.ready,
    queryFn: async () => {
      const res = await fetch("/readyz", { cache: "no-store" });
      if (!res.ok && res.status !== 503)
        throw new Error(`Readiness probe answered HTTP ${res.status}.`);
      return (await res.json()) as {
        status: string;
        postgres: boolean;
        redis: boolean;
        clickhouse: boolean;
      };
    },
    staleTime: STALE.live,
    refetchInterval: 30_000,
    retry: false,
  });
}
