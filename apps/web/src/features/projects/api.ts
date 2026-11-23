"use client";

import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { ApiKey, ProjectIn, ProjectUpdate } from "@/lib/api/types";
import { useInvalidating } from "@/lib/mutation";
import { qk, STALE } from "@/lib/query-keys";

export function useProjects(includeArchived = false) {
  return useQuery({
    queryKey: qk.projectList(includeArchived),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/projects", { params: { query: { include_archived: includeArchived } } })
      ),
    staleTime: STALE.config,
  });
}

export function useProject(id: string) {
  return useQuery({
    queryKey: qk.project(id),
    queryFn: () =>
      unwrap(api.GET("/api/v1/projects/{project_id}", { params: { path: { project_id: id } } })),
    staleTime: STALE.config,
    enabled: !!id,
  });
}

export function useEnvironments(projectId: string) {
  return useQuery({
    queryKey: qk.environments(projectId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/environments", { params: { query: { project_id: projectId } } })),
    staleTime: STALE.config,
    enabled: !!projectId,
  });
}

export function useCreateProject() {
  return useInvalidating(
    (body: ProjectIn) => unwrap(api.POST("/api/v1/projects", { body })),
    [qk.projects]
  );
}

export function useUpdateProject(id: string) {
  return useInvalidating(
    (body: ProjectUpdate) =>
      unwrap(
        api.PATCH("/api/v1/projects/{project_id}", { params: { path: { project_id: id } }, body })
      ),
    [qk.projects]
  );
}

export function usePreviewRedaction(id: string) {
  return useInvalidating(
    (text: string) =>
      unwrap(
        api.POST("/api/v1/projects/{project_id}/redaction/preview", {
          params: { path: { project_id: id } },
          body: { text },
        })
      ),
    []
  );
}

export function useKeys(projectId: string, includeRevoked = false) {
  return useQuery({
    queryKey: qk.keyList(projectId, includeRevoked),
    queryFn: (): Promise<ApiKey[]> =>
      unwrap(
        api.GET("/api/v1/keys", {
          params: {
            query: { project_id: projectId || undefined, include_revoked: includeRevoked },
          },
        })
      ),
    staleTime: STALE.list,
  });
}

/** Creates a key. The response carries the plaintext `key` once; it is never fetched again. */
export function useCreateKey() {
  return useInvalidating(
    (body: { project_id: string; name: string }) => unwrap(api.POST("/api/v1/keys", { body })),
    [qk.keys]
  );
}

export function useRevokeKey() {
  return useInvalidating(
    (keyId: string) =>
      unwrap(api.DELETE("/api/v1/keys/{key_id}", { params: { path: { key_id: keyId } } })),
    [qk.keys]
  );
}
