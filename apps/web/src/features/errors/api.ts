"use client";

import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import { useInvalidating } from "@/lib/mutation";
import { qk, STALE } from "@/lib/query-keys";

export interface ErrorFilters {
  status: "" | "open" | "resolved" | "ignored";
  q: string;
  service: string;
  sort: "last_seen" | "first_seen" | "occurrences";
}

export function useErrorGroups(projectId: string, f: ErrorFilters) {
  const query = {
    project_id: projectId,
    status: f.status || undefined,
    q: f.q || undefined,
    service: f.service || undefined,
    sort: f.sort,
    limit: 100,
  };
  return useQuery({
    queryKey: qk.errorList(query),
    queryFn: () => unwrap(api.GET("/api/v1/errors", { params: { query } })),
    staleTime: STALE.list,
    enabled: !!projectId,
  });
}

export function useErrorGroup(projectId: string, id: string) {
  return useQuery({
    queryKey: qk.error(projectId, id),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/errors/{group_id}", {
          params: { path: { group_id: id }, query: { project_id: projectId } },
        })
      ),
    staleTime: STALE.list,
    enabled: !!projectId && !!id,
  });
}

export function useGroupLines(projectId: string, groupId: string, sinceIso: string) {
  return useQuery({
    queryKey: ["errors", "lines", projectId, groupId, sinceIso],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/logs", {
          params: {
            query: {
              project_id: projectId,
              error_group_id: groupId,
              start: sinceIso,
              end: new Date(Date.now() + 60_000).toISOString(),
              limit: 20,
            },
          },
        })
      ),
    staleTime: STALE.list,
    enabled: !!projectId && !!groupId && !!sinceIso,
  });
}

export function useSetGroupStatus(projectId: string) {
  return useInvalidating(
    ({ id, status }: { id: string; status: "open" | "resolved" | "ignored" }) =>
      unwrap(
        api.PATCH("/api/v1/errors/{group_id}", {
          params: { path: { group_id: id }, query: { project_id: projectId } },
          body: { status },
        })
      ),
    [qk.errors]
  );
}
