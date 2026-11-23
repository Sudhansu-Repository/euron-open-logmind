"use client";

import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import { qk, STALE } from "@/lib/query-keys";

export function useServices(projectId: string, hours = 24) {
  return useQuery({
    queryKey: qk.serviceList(projectId, hours),
    queryFn: () =>
      unwrap(api.GET("/api/v1/services", { params: { query: { project_id: projectId, hours } } })),
    staleTime: STALE.list,
    enabled: !!projectId,
    refetchInterval: 30_000,
  });
}
