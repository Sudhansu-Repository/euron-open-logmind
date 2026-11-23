"use client";

import { BellRingIcon, MailIcon, PlusIcon, SlackIcon, WebhookIcon } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { AlertEventChip, AlertStateChip } from "@/components/badges";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { GatedButton } from "@/components/gated";
import { PageHeader } from "@/components/page-header";
import { useProjectScope } from "@/components/project-select";
import { SecretOnceDialog } from "@/components/secret-once-dialog";
import { NoProject } from "@/components/send-first-log";
import { Surface, SurfaceHeader } from "@/components/surface";
import { TableSkeleton } from "@/components/table-skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useProjects } from "@/features/projects/api";
import { useNow } from "@/hooks/use-now";
import { formatRelative } from "@/lib/format";

import { useAlertHistory, useAlertRules } from "../api";
import { describeRule } from "../form";
import { AlertDialog } from "./alert-dialog";

export function Targets({
  emails,
  webhook,
  slack,
}: {
  emails: number;
  webhook: boolean;
  slack: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-2 text-subtle">
      {emails > 0 && (
        <span className="inline-flex items-center gap-1" title={`${emails} email address(es)`}>
          <MailIcon className="size-3.5" aria-label="Email" />
          {emails}
        </span>
      )}
      {webhook && <WebhookIcon className="size-3.5" aria-label="Webhook" />}
      {slack && <SlackIcon className="size-3.5" aria-label="Slack" />}
    </span>
  );
}

/**
 * Alert Management: threshold and anomaly rules evaluated against live data, notifying by
 * email (Mailpit locally), signed webhook and Slack. Below the rules, every recent firing
 * and recovery with the outcome of each delivery.
 */
export function AlertsScreen() {
  const projects = useProjects();
  const [projectId] = useProjectScope();
  const now = useNow(30_000);
  const rules = useAlertRules(projectId);
  const history = useAlertHistory(projectId);
  const [creating, setCreating] = React.useState(false);
  const [secret, setSecret] = React.useState<string | null>(null);

  if (projects.isSuccess && projects.data.length === 0) {
    return (
      <>
        <PageHeader title="Alerts" />
        <Surface>
          <NoProject />
        </Surface>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Alerts"
        description="Rules that watch live log data and notify by email, webhook or Slack when they fire."
        actions={
          <>
            <GatedButton
              need="manageAlerts"
              onClick={() => setCreating(true)}
              disabled={!projectId}
              data-qa="new-alert"
            >
              <PlusIcon />
              New rule
            </GatedButton>
          </>
        }
      />
      <div className="space-y-5">
        <Surface>
          {rules.isPending ? (
            <TableSkeleton rows={4} cols={4} />
          ) : rules.isError ? (
            <ErrorState
              compact
              error={rules.error}
              title="Could not load alert rules"
              onRetry={() => void rules.refetch()}
            />
          ) : rules.data.length === 0 ? (
            <EmptyState
              icon={BellRingIcon}
              title="No alert rules"
              description="A threshold rule fires when a number crosses a line (errors in checkout over 5 minutes); an anomaly rule fires when errors break from their own baseline."
              action={
                <GatedButton need="manageAlerts" size="sm" onClick={() => setCreating(true)}>
                  <PlusIcon />
                  Create the first rule
                </GatedButton>
              }
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Rule</TableHead>
                  <TableHead className="hidden md:table-cell">Targets</TableHead>
                  <TableHead className="hidden sm:table-cell">Last value</TableHead>
                  <TableHead>State</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rules.data.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="max-w-0">
                      <Link
                        href={`/alerts/${r.id}`}
                        className="block min-w-0 rounded focus-visible:outline-2 focus-visible:outline-ring"
                      >
                        <span className="block truncate font-medium">{r.name}</span>
                        <span className="block truncate text-[12px] text-muted-foreground">
                          {describeRule(r)}
                        </span>
                      </Link>
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      <Targets
                        emails={r.email_to.length}
                        webhook={r.has_webhook}
                        slack={r.has_slack}
                      />
                    </TableCell>
                    <TableCell className="hidden text-[12.5px] tabular sm:table-cell">
                      {r.last_value == null ? "Not evaluated yet" : r.last_value}
                      {r.last_evaluated_at && (
                        <span className="block text-[11.5px] text-subtle">
                          {formatRelative(r.last_evaluated_at, now)}
                        </span>
                      )}
                    </TableCell>
                    <TableCell>
                      <AlertStateChip state={r.state} enabled={r.enabled} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Surface>
        <Surface>
          <SurfaceHeader
            title="Recent firings"
            description="Every firing and recovery, with what each target answered"
          />
          {history.isPending ? (
            <TableSkeleton rows={4} cols={3} />
          ) : history.isError ? (
            <ErrorState compact error={history.error} title="Could not load history" />
          ) : history.data.length === 0 ? (
            <p className="px-5 pb-5 text-[13px] text-muted-foreground">
              Nothing has fired yet. When a rule fires, the notification and each target&apos;s
              answer appear here.
            </p>
          ) : (
            <ul className="divide-y divide-hairline px-5 pb-3" data-qa="alert-history">
              {history.data.map((h) => (
                <li
                  key={h.id}
                  className="flex flex-col gap-1 py-2.5 sm:flex-row sm:items-start sm:gap-3"
                >
                  <span className="w-20 shrink-0">
                    <AlertEventChip event={h.event} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <Link
                      href={`/alerts/${h.rule_id}`}
                      className="block truncate text-[13px] font-medium hover:underline"
                    >
                      {h.rule_name}
                    </Link>
                    <span className="block text-[12.5px] text-muted-foreground">{h.message}</span>
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
                    {formatRelative(h.at, now)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Surface>
      </div>
      <AlertDialog
        open={creating}
        rule={null}
        projectId={projectId}
        onClose={() => setCreating(false)}
        onCreated={setSecret}
      />
      <SecretOnceDialog
        value={secret}
        title="Webhook signing secret"
        description="Every webhook delivery carries X-LogMind-Signature: t=<time>,v1=<HMAC-SHA256 of time.body>. Verify it with this secret. It is shown once."
        label="Signing secret"
        onClose={() => setSecret(null)}
      />
    </>
  );
}
