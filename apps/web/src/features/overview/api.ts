"use client";

import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import { qk, STALE } from "@/lib/query-keys";

export function useOverview(projectId: string, hours: number) {
  return useQuery({
    queryKey: qk.overview(projectId, hours),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/analytics/overview", {
          params: { query: { project_id: projectId, hours } },
        })
      ),
    staleTime: STALE.list,
    enabled: !!projectId,
    refetchInterval: 30_000,
  });
}
