"use client";

import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { Investigation } from "@/lib/api/types";
import { useInvalidating } from "@/lib/mutation";
import { qk, STALE } from "@/lib/query-keys";

/** Still being worked on: poll until the worker finishes. */
export function isPending(inv: Pick<Investigation, "status" | "turns"> | undefined): boolean {
  if (!inv) return false;
  return (
    inv.status === "queued" ||
    inv.status === "running" ||
    inv.turns.some((t) => t.status === "queued" || t.status === "running")
  );
}

export function useInvestigations(projectId: string, errorGroupId = "") {
  return useQuery({
    queryKey: qk.investigationList(projectId, errorGroupId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/ai/investigations", {
          params: {
            query: { project_id: projectId, error_group_id: errorGroupId || undefined, limit: 100 },
          },
        })
      ),
    staleTime: STALE.list,
    enabled: !!projectId,
    refetchInterval: (q) =>
      (q.state.data ?? []).some((i) => i.status === "queued" || i.status === "running")
        ? 2000
        : false,
  });
}

export function useInvestigation(id: string) {
  return useQuery({
    queryKey: qk.investigation(id),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/ai/investigations/{investigation_id}", {
          params: { path: { investigation_id: id } },
        })
      ),
    staleTime: STALE.report,
    enabled: !!id,
    refetchInterval: (q) => (isPending(q.state.data) ? 1500 : false),
  });
}

export function useVerify(id: string, enabled: boolean) {
  return useQuery({
    queryKey: qk.verify(id),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/ai/investigations/{investigation_id}/verify", {
          params: { path: { investigation_id: id } },
        })
      ),
    staleTime: STALE.report,
    enabled: !!id && enabled,
  });
}

export function useInvestigate() {
  return useInvalidating(
    (body: {
      project_id: string;
      error_group_id?: string;
      question?: string;
      window_minutes?: number;
    }) => unwrap(api.POST("/api/v1/ai/investigate", { body })),
    [qk.investigations]
  );
}

export function useFollowup(id: string) {
  return useInvalidating(
    (question: string) =>
      unwrap(
        api.POST("/api/v1/ai/investigations/{investigation_id}/followup", {
          params: { path: { investigation_id: id } },
          body: { question },
        })
      ),
    [qk.investigation(id), qk.verify(id)]
  );
}

export function useUsage(projectId: string, days = 30) {
  return useQuery({
    queryKey: qk.usage(projectId, days),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/usage", {
          params: { query: { project_id: projectId || undefined, days } },
        })
      ),
    staleTime: STALE.list,
  });
}
