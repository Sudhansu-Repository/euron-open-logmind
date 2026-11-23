"use client";

import * as React from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/error-state";
import { GatedButton, RoleNote } from "@/components/gated";
import { KeyValues } from "@/components/kv";
import { Surface, SurfaceHeader } from "@/components/surface";
import { ThemeSelector } from "@/components/theme-toggle";
import { Chip } from "@/components/ui/chip";
import { Input } from "@/components/ui/input";
import { Field, FieldError } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { usePermissions } from "@/features/auth/api";
import { useCan } from "@/hooks/use-can";
import { errorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { roleDescription, roleLabel } from "@/lib/roles";

import { useOrg, useReady, useUpdateOrg } from "../api";

function Readiness() {
  const ready = useReady();
  if (ready.isPending) return <Skeleton className="h-5 w-40" />;
  if (ready.isError)
    return (
      <span className="text-[12.5px] text-muted-foreground">
        The API readiness probe is not reachable from this page.
      </span>
    );
  const r = ready.data;
  const dep = (label: string, ok: boolean) => (
    <Chip tone={ok ? "success" : "danger"} dot>
      {label} {ok ? "up" : "down"}
    </Chip>
  );
  return (
    <span className="flex flex-wrap gap-1.5">
      {dep("Postgres", r.postgres)}
      {dep("Redis", r.redis)}
      {dep("ClickHouse", r.clickhouse)}
    </span>
  );
}

export function OrgPanel() {
  const org = useOrg();
  const update = useUpdateOrg();
  const { user } = usePermissions();
  const { allowed } = useCan("updateOrg");
  const [name, setName] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (org.data) setName(org.data.name);
  }, [org.data]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return setError("The organization needs a name.");
    setError(null);
    update.mutate(
      { name: name.trim() },
      {
        onSuccess: () => toast.success("Organization renamed."),
        onError: (err) => setError(errorMessage(err)),
      }
    );
  }

  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <Surface>
        <SurfaceHeader
          title="Organization"
          description="Every project, log line and person belongs to one organization; nothing crosses between organizations."
        />
        {org.isPending ? (
          <Skeleton className="mx-5 mb-5 h-24" />
        ) : org.isError ? (
          <ErrorState
            compact
            error={org.error}
            title="Could not load the organization"
            onRetry={() => void org.refetch()}
          />
        ) : (
          <form onSubmit={submit} className="space-y-4 px-5 pb-5" noValidate>
            <RoleNote need="updateOrg" />
            <Field label="Name" htmlFor="org-name" error={error}>
              <Input
                id="org-name"
                value={name}
                disabled={!allowed}
                onChange={(e) => setName(e.target.value)}
                maxLength={120}
              />
            </Field>
            <KeyValues
              columns={2}
              items={[
                {
                  label: "Short name",
                  value: <span className="font-mono text-[12px]">{org.data.slug}</span>,
                },
                { label: "Created", value: formatDate(org.data.created_at) },
              ]}
            />
            <div className="flex justify-end">
              <GatedButton
                need="updateOrg"
                type="submit"
                disabled={update.isPending || name.trim() === org.data.name}
              >
                {update.isPending ? "Saving..." : "Save name"}
              </GatedButton>
            </div>
            {update.isError && !error && <FieldError>{errorMessage(update.error)}</FieldError>}
          </form>
        )}
      </Surface>
      <div className="space-y-5">
        <Surface>
          <SurfaceHeader
            title="You"
            description="Your role decides which controls you can use; the API enforces the same rules."
          />
          <div className="space-y-2 px-5 pb-5">
            <div className="flex items-center gap-2">
              <span className="text-[13px] font-medium">{user?.name}</span>
              <Chip tone="primary">{roleLabel(user?.role)}</Chip>
            </div>
            <p className="text-[12.5px] text-muted-foreground">{roleDescription(user?.role)}</p>
          </div>
        </Surface>
        <Surface>
          <SurfaceHeader title="Appearance" description="Light, dark, or follow your system." />
          <div className="px-5 pb-5">
            <ThemeSelector />
          </div>
        </Surface>
        <Surface>
          <SurfaceHeader
            title="API status"
            description="The API's own readiness probe (/readyz)."
          />
          <div className="px-5 pb-5">
            <Readiness />
          </div>
        </Surface>
      </div>
    </div>
  );
}
