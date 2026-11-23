"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import { qk, STALE } from "@/lib/query-keys";

import { apiQuery, type LogFilters } from "./filters";

/** Search, newest first, keyset paginated ("load older" follows next_cursor). */
export function useLogSearch(projectId: string, f: LogFilters, now: number) {
  const query = apiQuery(projectId, f, now);
  return useInfiniteQuery({
    queryKey: qk.logSearch(query),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/logs", {
          params: { query: { ...query, cursor: pageParam ?? undefined, limit: 100 } },
        })
      ),
    getNextPageParam: (last) => last.next_cursor ?? null,
    staleTime: STALE.live,
    enabled: !!projectId,
  });
}

export function useHistogram(projectId: string, f: LogFilters, now: number) {
  const query = apiQuery(projectId, f, now);
  return useQuery({
    queryKey: qk.logHistogram(query),
    queryFn: () => unwrap(api.GET("/api/v1/logs/histogram", { params: { query } })),
    staleTime: STALE.live,
    enabled: !!projectId,
  });
}

export function useFacets(projectId: string, f: LogFilters, now: number) {
  const query = apiQuery(
    projectId,
    { ...f, q: "", levels: [], services: [], environments: [] },
    now
  );
  return useQuery({
    queryKey: qk.logFacets(projectId, f.range),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/logs/facets", {
          params: { query: { project_id: query.project_id, start: query.start, end: query.end } },
        })
      ),
    staleTime: STALE.list,
    enabled: !!projectId,
  });
}

export function useLogContext(projectId: string, eventId: string | null, at: string | null) {
  return useQuery({
    queryKey: qk.logContext(projectId, eventId ?? ""),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/logs/{event_id}/context", {
          params: {
            path: { event_id: eventId ?? "" },
            query: { project_id: projectId, at: at ?? undefined, size: 8 },
          },
        })
      ),
    staleTime: STALE.static,
    enabled: !!projectId && !!eventId,
  });
}
