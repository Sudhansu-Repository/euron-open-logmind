"use client";

import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { AlertIn, AlertUpdate } from "@/lib/api/types";
import { useInvalidating } from "@/lib/mutation";
import { qk, STALE } from "@/lib/query-keys";

export function useAlertRules(projectId: string) {
  return useQuery({
    queryKey: qk.alertList(projectId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/alerts", { params: { query: { project_id: projectId } } })),
    staleTime: STALE.list,
    enabled: !!projectId,
    refetchInterval: 20_000,
  });
}

export function useAlertRule(id: string) {
  return useQuery({
    queryKey: qk.alert(id),
    queryFn: () =>
      unwrap(api.GET("/api/v1/alerts/{rule_id}", { params: { path: { rule_id: id } } })),
    staleTime: STALE.list,
    enabled: !!id,
  });
}

/** Firings across the project, or of one rule when `ruleId` is set. */
export function useAlertHistory(projectId: string, ruleId = "") {
  return useQuery({
    queryKey: qk.alertHistory(projectId, ruleId),
    queryFn: () =>
      ruleId
        ? unwrap(
            api.GET("/api/v1/alerts/{rule_id}/history", {
              params: { path: { rule_id: ruleId }, query: { limit: 100 } },
            })
          )
        : unwrap(
            api.GET("/api/v1/alerts/history", {
              params: { query: { project_id: projectId, limit: 100 } },
            })
          ),
    staleTime: STALE.list,
    enabled: ruleId ? true : !!projectId,
    refetchInterval: 20_000,
  });
}

export function useCreateAlertRule() {
  return useInvalidating(
    (body: AlertIn) => unwrap(api.POST("/api/v1/alerts", { body })),
    [qk.alerts]
  );
}

export function useUpdateAlertRule() {
  return useInvalidating(
    ({ id, body }: { id: string; body: AlertUpdate }) =>
      unwrap(api.PATCH("/api/v1/alerts/{rule_id}", { params: { path: { rule_id: id } }, body })),
    [qk.alerts]
  );
}

export function useDeleteAlertRule() {
  return useInvalidating(
    (id: string) =>
      unwrap(api.DELETE("/api/v1/alerts/{rule_id}", { params: { path: { rule_id: id } } })),
    [qk.alerts]
  );
}

export function useTestAlertRule() {
  return useInvalidating(
    (id: string) =>
      unwrap(api.POST("/api/v1/alerts/{rule_id}/test", { params: { path: { rule_id: id } } })),
    [qk.alerts]
  );
}
