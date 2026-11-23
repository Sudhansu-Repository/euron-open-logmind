"use client";

import * as React from "react";

import { SimpleSelect } from "@/components/ui/select";
import { useProjects } from "@/features/projects/api";
import { cn } from "@/lib/cn";
import { useUiPrefs } from "@/lib/store";

/**
 * The project every view is scoped to. Log data always belongs to exactly one project, so
 * there is no "every project" option: a remembered project that was archived or deleted,
 * or none at all, falls back to the first project. Returns "" only while projects load or
 * when the organisation has none yet.
 */
export function useProjectScope(): [string, (id: string) => void] {
  const projects = useProjects();
  const stored = useUiPrefs((s) => s.projectId);
  const setProjectId = useUiPrefs((s) => s.setProjectId);
  const list = projects.data ?? [];
  const valid = list.some((p) => p.id === stored);
  const projectId = valid ? stored : (list[0]?.id ?? "");
  React.useEffect(() => {
    if (projects.isSuccess && !valid && projectId) setProjectId(projectId);
  }, [projects.isSuccess, valid, projectId, setProjectId]);
  return [projectId, setProjectId];
}

export function ProjectSelect({
  className,
  size = "sm",
  label = "Project",
}: {
  className?: string;
  size?: "sm" | "default";
  label?: string;
}) {
  const projects = useProjects();
  const [projectId, setProjectId] = useProjectScope();
  const list = projects.data ?? [];
  return (
    <SimpleSelect
      aria-label={label}
      size={size}
      className={cn("w-full sm:w-48", className)}
      value={projectId}
      onValueChange={setProjectId}
      disabled={projects.isPending || list.length === 0}
      placeholder={projects.isPending ? "Loading projects..." : "No projects yet"}
      options={list.map((p) => ({ value: p.id, label: p.name }))}
    />
  );
}
