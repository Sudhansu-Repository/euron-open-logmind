"use client";

import { FolderPlusIcon } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { GatedButton, GatedSwitch } from "@/components/gated";
import { useProjectScope } from "@/components/project-select";
import { Segmented } from "@/components/segmented";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field, FieldError } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useCreateProject,
  usePreviewRedaction,
  useProject,
  useUpdateProject,
} from "@/features/projects/api";
import { useUiPrefs } from "@/lib/store";
import { errorMessage } from "@/lib/api/errors";
import { REDACTION_CATEGORIES, REDACTION_CATEGORY, type RedactionCategory } from "@/lib/labels";

const SAMPLE =
  "login ok for jane.doe@example.com card 4111 1111 1111 1111 password=hunter2hunter2 from 10.0.4.7";

/** Projects: create one, and set a project's retention and redaction policy (A7). */
export function ProjectsPanel() {
  const [projectId] = useProjectScope();
  const setProjectId = useUiPrefs((s) => s.setProjectId);
  const project = useProject(projectId);
  const create = useCreateProject();
  const update = useUpdateProject(projectId);
  const preview = usePreviewRedaction(projectId);
  const [newName, setNewName] = React.useState("");
  const [retention, setRetention] = React.useState("14");
  const [sample, setSample] = React.useState(SAMPLE);
  const [error, setError] = React.useState<string | null>(null);
  const p = project.data;
  React.useEffect(() => {
    if (p) setRetention(String(p.retention_days));
  }, [p]);

  const save = (body: Parameters<typeof update.mutate>[0], ok = "Saved.") =>
    update.mutate(body, {
      onSuccess: () => {
        toast.success(ok);
        setError(null);
      },
      onError: (err) => setError(errorMessage(err)),
    });

  return (
    <div className="space-y-5">
      <Surface>
        <SurfaceHeader
          title="New project"
          description="One project per application or team: its own logs, keys, retention and redaction."
        />
        <form
          className="flex flex-col gap-2 px-5 pb-5 sm:flex-row"
          onSubmit={(e) => {
            e.preventDefault();
            if (!newName.trim()) return;
            create.mutate(
              { name: newName.trim(), description: "", retention_days: 14 },
              {
                onSuccess: (created) => {
                  toast.success(`Project ${created.name} created.`);
                  setNewName("");
                  setProjectId(created.id);
                },
                onError: (err) => toast.error(errorMessage(err)),
              }
            );
          }}
        >
          <Input
            aria-label="Project name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Project name"
            className="sm:flex-1"
          />
          <GatedButton
            need="createProject"
            type="submit"
            disabled={!newName.trim() || create.isPending}
          >
            <FolderPlusIcon />
            Create project
          </GatedButton>
        </form>
      </Surface>
      <Surface>
        <SurfaceHeader
          title="Retention and redaction"
          description="Applied to every line at ingestion, before anything is stored."
        />
        {!p ? (
          <Skeleton className="mx-5 mb-5 h-64" />
        ) : (
          <div className="space-y-5 px-5 pb-5">
            <form
              className="flex flex-col gap-2 sm:flex-row sm:items-start"
              onSubmit={(e) => {
                e.preventDefault();
                save({ retention_days: Number(retention) }, "Retention saved.");
              }}
            >
              <Field
                label="Keep logs for"
                htmlFor="retention"
                hint="days, 1 to 365; older lines are deleted hourly"
              >
                <Input
                  id="retention"
                  inputMode="numeric"
                  value={retention}
                  onChange={(e) => setRetention(e.target.value)}
                  className="sm:w-32"
                />
              </Field>
              <GatedButton
                need="updateProject"
                type="submit"
                variant="outline"
                className="sm:mt-6"
                disabled={Number(retention) === p.retention_days || update.isPending}
              >
                Save
              </GatedButton>
            </form>
            <div className="flex items-center justify-between rounded-xl bg-muted px-4 py-3">
              <label htmlFor="redact" className="text-[13px] font-medium">
                Redact PII and secrets
                <span className="block text-xs font-normal text-muted-foreground">
                  Matching values are replaced in messages, stack traces and attributes before
                  storage.
                </span>
              </label>
              <GatedSwitch
                need="updateProject"
                id="redact"
                checked={p.redaction_enabled}
                onCheckedChange={(redaction_enabled) => save({ redaction_enabled })}
              />
            </div>
            <fieldset disabled={!p.redaction_enabled} className="space-y-3 disabled:opacity-60">
              <legend className="mb-2 text-[13px] font-medium">Categories</legend>
              <div className="grid gap-2 sm:grid-cols-2">
                {REDACTION_CATEGORIES.map((c) => {
                  const on = p.redaction_categories.includes(c);
                  return (
                    <div
                      key={c}
                      className="flex items-start justify-between gap-3 rounded-lg bg-muted/60 px-3 py-2"
                    >
                      <span className="text-[13px]">
                        {REDACTION_CATEGORY[c].label}
                        <span className="block text-[11.5px] text-muted-foreground">
                          {REDACTION_CATEGORY[c].hint}
                        </span>
                      </span>
                      <GatedSwitch
                        need="updateProject"
                        aria-label={REDACTION_CATEGORY[c].label}
                        checked={on}
                        onCheckedChange={(v) =>
                          save({
                            redaction_categories: (v
                              ? [...p.redaction_categories, c]
                              : p.redaction_categories.filter(
                                  (x) => x !== c
                                )) as RedactionCategory[],
                          })
                        }
                      />
                    </div>
                  );
                })}
              </div>
              <Field label="Mode" htmlFor="mode">
                <Segmented
                  ariaLabel="Redaction mode"
                  value={p.redaction_mode as "mask" | "hash"}
                  onChange={(redaction_mode) => save({ redaction_mode })}
                  options={[
                    { value: "mask", label: "Mask", description: "[REDACTED:email]" },
                    {
                      value: "hash",
                      label: "Hash",
                      description: "[email:1a2b3c4d], equal values stay equal",
                    },
                  ]}
                  className="sm:w-64"
                />
              </Field>
            </fieldset>
            <div className="space-y-2">
              <Field label="Try it" htmlFor="sample" hint="Nothing you type here is stored">
                <Input id="sample" value={sample} onChange={(e) => setSample(e.target.value)} />
              </Field>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() =>
                  preview.mutate(sample, { onError: (err) => toast.error(errorMessage(err)) })
                }
                disabled={preview.isPending}
              >
                Preview redaction
              </Button>
              {preview.data && (
                <pre className="code-block whitespace-pre-wrap" data-qa="redaction-preview">
                  {preview.data.redacted}
                </pre>
              )}
            </div>
            {error && <FieldError>{error}</FieldError>}
          </div>
        )}
      </Surface>
    </div>
  );
}
