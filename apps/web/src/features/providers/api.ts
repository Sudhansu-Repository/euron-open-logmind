"use client";

import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { ProviderCreate, ProviderUpdate } from "@/lib/api/types";
import { useInvalidating } from "@/lib/mutation";
import { qk, STALE } from "@/lib/query-keys";

export function useProviders() {
  return useQuery({
    queryKey: qk.providers,
    queryFn: () => unwrap(api.GET("/api/v1/ai/providers")),
    staleTime: STALE.config,
  });
}

export function useCreateProvider() {
  return useInvalidating(
    (body: ProviderCreate) => unwrap(api.POST("/api/v1/ai/providers", { body })),
    [qk.providers]
  );
}

export function useUpdateProvider() {
  return useInvalidating(
    ({ id, body }: { id: string; body: ProviderUpdate }) =>
      unwrap(
        api.PATCH("/api/v1/ai/providers/{provider_id}", {
          params: { path: { provider_id: id } },
          body,
        })
      ),
    [qk.providers]
  );
}

export function useDeleteProvider() {
  return useInvalidating(
    (id: string) =>
      unwrap(
        api.DELETE("/api/v1/ai/providers/{provider_id}", { params: { path: { provider_id: id } } })
      ),
    [qk.providers]
  );
}

export function useTestProvider() {
  return useInvalidating(
    (id: string) =>
      unwrap(
        api.POST("/api/v1/ai/providers/{provider_id}/test", {
          params: { path: { provider_id: id } },
        })
      ),
    [qk.providers]
  );
}
