"use client";

import { ArrowLeftIcon, PencilIcon, SendIcon, Trash2Icon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { AlertEventChip, AlertStateChip } from "@/components/badges";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { ErrorState } from "@/components/error-state";
import { GatedButton, GatedSwitch } from "@/components/gated";
import { KeyValues } from "@/components/kv";
import { PageHeader } from "@/components/page-header";
import { Surface, SurfaceHeader } from "@/components/surface";
import { TableSkeleton } from "@/components/table-skeleton";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api/errors";
import { formatDateTime, formatRelative } from "@/lib/format";

import {
  useAlertHistory,
  useAlertRule,
  useDeleteAlertRule,
  useTestAlertRule,
  useUpdateAlertRule,
} from "../api";
import { describeRule } from "../form";
import { AlertDialog } from "./alert-dialog";
import { Targets } from "./alerts-screen";

export function AlertDetail({ id }: { id: string }) {
  const router = useRouter();
  const rule = useAlertRule(id);
  const r = rule.data;
  const history = useAlertHistory(r?.project_id ?? "", id);
  const update = useUpdateAlertRule();
  const del = useDeleteAlertRule();
  const test = useTestAlertRule();
  const [editing, setEditing] = React.useState(false);
  const [confirm, setConfirm] = React.useState(false);

  if (rule.isError) {
    return (
      <Surface>
        <ErrorState
          error={rule.error}
          title="Could not load this rule"
          onRetry={() => void rule.refetch()}
        />
      </Surface>
    );
  }

  return (
    <>
      <PageHeader
        eyebrow={
          <Link
            href="/alerts"
            className="inline-flex items-center gap-1 text-[12.5px] text-muted-foreground hover:text-foreground"
          >
            <ArrowLeftIcon className="size-3.5" />
            Alerts
          </Link>
        }
        title={r ? r.name : <Skeleton className="h-7 w-64" />}
        description={r ? describeRule(r) : undefined}
        actions={
          r && (
            <>
              <AlertStateChip state={r.state} enabled={r.enabled} />
              <GatedButton
                need="manageAlerts"
                variant="outline"
                onClick={() =>
                  test.mutate(id, {
                    onSuccess: (h) =>
                      toast.success(
                        h.deliveries.every((d) => d.ok)
                          ? "Test sent to every target."
                          : "Test sent; some targets failed, see the history."
                      ),
                    onError: (e) => toast.error(errorMessage(e)),
                  })
                }
                disabled={test.isPending}
              >
                <SendIcon />
                {test.isPending ? "Sending..." : "Send test"}
              </GatedButton>
              <GatedButton need="manageAlerts" variant="outline" onClick={() => setEditing(true)}>
                <PencilIcon />
                Edit
              </GatedButton>
              <GatedButton
                need="manageAlerts"
                variant="destructive-soft"
                onClick={() => setConfirm(true)}
              >
                <Trash2Icon />
                Delete
              </GatedButton>
            </>
          )
        }
      />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <Surface className="h-fit">
          <SurfaceHeader title="Rule" />
          <div className="space-y-4 px-5 pb-5">
            {r ? (
              <>
                <KeyValues
                  items={[
                    { label: "Type", value: r.kind === "anomaly" ? "Anomaly" : "Threshold" },
                    {
                      label: "Targets",
                      value: (
                        <Targets
                          emails={r.email_to.length}
                          webhook={r.has_webhook}
                          slack={r.has_slack}
                        />
                      ),
                    },
                    {
                      label: "Email",
                      value: r.email_to.join(", ") || "None",
                      hidden: !r.email_to.length,
                    },
                    { label: "Cooldown", value: `${r.cooldown_minutes} min` },
                    {
                      label: "Last value",
                      value: r.last_value == null ? "Not evaluated yet" : String(r.last_value),
                    },
                    {
                      label: "Last evaluated",
                      value: r.last_evaluated_at ? formatRelative(r.last_evaluated_at) : "Never",
                    },
                    {
                      label: "Last fired",
                      value: r.last_fired_at ? formatDateTime(r.last_fired_at) : "Never",
                    },
                  ]}
                />
                <div className="flex items-center justify-between rounded-xl bg-muted px-4 py-3">
                  <label htmlFor="rule-enabled" className="text-[13px] font-medium">
                    Enabled
                  </label>
                  <GatedSwitch
                    need="manageAlerts"
                    id="rule-enabled"
                    checked={r.enabled}
                    onCheckedChange={(enabled) =>
                      update.mutate(
                        { id, body: { enabled } },
                        { onError: (e) => toast.error(errorMessage(e)) }
                      )
                    }
                  />
                </div>
              </>
            ) : (
              <Skeleton className="h-48 w-full" />
            )}
          </div>
        </Surface>
        <Surface>
          <SurfaceHeader
            title="History"
            description="Firings, recoveries and tests, with each delivery outcome"
          />
          {history.isPending ? (
            <TableSkeleton rows={5} cols={3} />
          ) : history.isError ? (
            <ErrorState compact error={history.error} title="Could not load history" />
          ) : history.data.length === 0 ? (
            <p className="px-5 pb-5 text-[13px] text-muted-foreground">
              This rule has not fired. Send a test to check every target now.
            </p>
          ) : (
            <ul className="divide-y divide-hairline px-5 pb-3">
              {history.data.map((h) => (
                <li key={h.id} className="flex flex-col gap-1 py-2.5 sm:flex-row sm:gap-3">
                  <span className="w-20 shrink-0">
                    <AlertEventChip event={h.event} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px]">{h.message}</span>
                    <span className="mt-1 flex flex-wrap gap-2 text-[11.5px]">
                      {h.deliveries.map((d, i) => (
                        <span key={i} className={d.ok ? "text-success" : "text-danger"}>
                          {String(d.channel)}{" "}
                          {d.ok ? "delivered" : `failed: ${String(d.error ?? "")}`}
                        </span>
                      ))}
                    </span>
                  </span>
                  <span className="text-[12px] whitespace-nowrap text-subtle">
                    {formatDateTime(h.at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Surface>
      </div>
      <AlertDialog
        open={editing}
        rule={r ?? null}
        projectId={r?.project_id ?? ""}
        onClose={() => setEditing(false)}
      />
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title="Delete this rule?"
        description="It stops being evaluated and its history is deleted with it."
        confirmLabel="Delete rule"
        pending={del.isPending}
        onConfirm={() =>
          del.mutate(id, {
            onSuccess: () => {
              toast.success("Rule deleted.");
              router.push("/alerts");
            },
            onError: (e) => toast.error(errorMessage(e)),
          })
        }
      />
    </>
  );
}
