"use client";

import {
  ActivityIcon,
  AlertTriangleIcon,
  ArrowRightIcon,
  BellRingIcon,
  BugIcon,
  EyeOffIcon,
  ScrollTextIcon,
  SparklesIcon,
  TrendingUpIcon,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";

import {
  AlertEventChip,
  InvestigationStatusChip,
  LevelChip,
  ServiceStatusChip,
} from "@/components/badges";
import { VolumeChart, toVolumePoints } from "@/components/charts/volume-chart";
import { hourlySeries, Sparkline } from "@/components/charts/sparkline";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { useProjectScope } from "@/components/project-select";
import { NoProject, SendFirstLog } from "@/components/send-first-log";
import { Segmented } from "@/components/segmented";
import { Stat } from "@/components/stat";
import { Surface, SurfaceHeader } from "@/components/surface";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useProjects } from "@/features/projects/api";
import { useNow } from "@/hooks/use-now";
import {
  formatNumber,
  formatPercent,
  formatRelative,
  formatTime,
  formatTokenCount,
  plural,
} from "@/lib/format";

import { groupSpikes } from "../anomalies";
import { useOverview } from "../api";

const WINDOWS = [
  { value: "6", label: "6h" },
  { value: "24", label: "24h" },
  { value: "168", label: "7d" },
] as const;

function delta(now: number, before: number): string {
  if (!before) return now ? "Nothing in the previous window" : "No change";
  // Under a twentieth of now: a percentage would only say the history is short.
  if (before * 20 < now) return `${formatNumber(before)} in the previous window`;
  const pct = (now - before) / before;
  return `${pct >= 0 ? "+" : ""}${formatPercent(pct)} vs the previous window`;
}

export function OverviewScreen() {
  const projects = useProjects();
  const [projectId] = useProjectScope();
  const [hours, setHours] = React.useState<(typeof WINDOWS)[number]["value"]>("24");
  const overview = useOverview(projectId, Number(hours));
  const now = useNow(60_000);
  const o = overview.data;

  if (projects.isSuccess && projects.data.length === 0) {
    return (
      <>
        <PageHeader title="Overview" description="Your logs at a glance." />
        <Surface>
          <NoProject />
        </Surface>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Overview"
        description="Volume, errors, service health, anomalies and what the AI investigator found, for one project."
        actions={
          <Segmented
            ariaLabel="Time window"
            value={hours}
            onChange={setHours}
            options={[...WINDOWS]}
            className="w-40"
          />
        }
      />
      {overview.isError ? (
        <Surface>
          <ErrorState
            error={overview.error}
            title="Could not load the overview"
            onRetry={() => void overview.refetch()}
          />
        </Surface>
      ) : o && o.lines === 0 && o.lines_previous === 0 ? (
        <Surface>
          <SendFirstLog />
        </Surface>
      ) : (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat
              label="Log lines"
              icon={ScrollTextIcon}
              loading={!o}
              value={formatNumber(o?.lines)}
              detail={o ? delta(o.lines, o.lines_previous) : undefined}
            />
            <Stat
              label="Errors"
              icon={AlertTriangleIcon}
              loading={!o}
              tone={o && o.error_rate > 0.02 ? "danger" : "default"}
              value={formatNumber(o?.errors)}
              detail={
                o
                  ? `${formatPercent(o.error_rate)} of lines; ${delta(o.errors, o.errors_previous)}`
                  : undefined
              }
            />
            <Stat
              label="Open error groups"
              icon={BugIcon}
              loading={!o}
              value={formatNumber(o?.open_error_groups)}
              detail={o ? `${plural(o.new_error_groups, "new group")} in this window` : undefined}
            />
            <Stat
              label="Redacted values"
              icon={EyeOffIcon}
              loading={!o}
              value={formatNumber(o?.redactions)}
              detail="PII and secrets removed before storage"
            />
          </div>
          <div className="grid gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <Surface>
              <SurfaceHeader
                title="Log volume"
                description={`Lines per bucket by level, last ${WINDOWS.find((w) => w.value === hours)?.label}`}
              />
              <div className="px-5 pb-5">
                {o ? (
                  <VolumeChart
                    data={toVolumePoints(o.histogram.buckets)}
                    spanMs={Number(hours) * 3_600_000}
                    height={220}
                  />
                ) : (
                  <Skeleton className="h-56 w-full" />
                )}
              </div>
            </Surface>
            <Surface>
              <SurfaceHeader
                title="Anomalies"
                description="Error spikes against each service's own baseline"
                action={
                  o && o.firing_alerts > 0 ? (
                    <span className="text-[12px] font-semibold text-danger">
                      {plural(o.firing_alerts, "alert")} firing
                    </span>
                  ) : null
                }
              />
              {!o ? (
                <Skeleton className="mx-5 mb-5 h-40" />
              ) : o.anomalies.length === 0 ? (
                <EmptyState
                  compact
                  icon={TrendingUpIcon}
                  title="No spikes"
                  description="Every service's errors stayed within its usual range for this window."
                />
              ) : (
                <ul className="space-y-1 px-3 pb-4" data-qa="anomalies">
                  {groupSpikes(o.anomalies)
                    .slice(0, 5)
                    .map((sp) => (
                      <li
                        key={`${sp.service}-${sp.start}`}
                        className="flex items-center gap-3 rounded-lg px-2 py-2"
                      >
                        <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-danger-soft text-danger">
                          <TrendingUpIcon className="size-4" />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13px] font-medium">
                            {sp.service}
                          </span>
                          <span className="block text-[12px] text-muted-foreground">
                            Peak {formatNumber(sp.peak)} errors in 5 min, usually{" "}
                            {sp.expected.toFixed(1)} ({sp.zscore.toFixed(1)} sigma)
                            {sp.windows > 1 ? `, ${sp.windows} windows in a row` : ""}
                          </span>
                        </span>
                        <span className="text-[12px] whitespace-nowrap text-subtle">
                          {formatTime(sp.start).slice(0, 5)}
                          {sp.windows > 1 ? ` to ${formatTime(sp.end).slice(0, 5)}` : ""}
                        </span>
                      </li>
                    ))}
                </ul>
              )}
            </Surface>
          </div>
          <div className="grid gap-5 xl:grid-cols-2">
            <Surface>
              <SurfaceHeader
                title="Noisiest open errors"
                action={
                  <Link href="/errors" className={buttonVariants({ variant: "ghost", size: "xs" })}>
                    All errors
                  </Link>
                }
              />
              {!o ? (
                <Skeleton className="mx-5 mb-5 h-40" />
              ) : o.top_errors.length === 0 ? (
                <EmptyState
                  compact
                  icon={BugIcon}
                  title="No open errors"
                  description="Error lines are fingerprinted and grouped as they arrive. None are open right now."
                />
              ) : (
                <ul className="px-2 pb-3">
                  {o.top_errors.map((g) => (
                    <li key={g.id}>
                      <Link
                        href={`/errors/${g.id}`}
                        className="flex items-center gap-3 rounded-lg px-3 py-2 hover:bg-muted/60"
                      >
                        <LevelChip level={g.level} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13px] font-medium">{g.title}</span>
                          <span className="block truncate text-[12px] text-muted-foreground">
                            {g.services.join(", ")}, last {formatRelative(g.last_seen, now)}
                          </span>
                        </span>
                        <Sparkline
                          values={hourlySeries(g.trend ?? [], 24, now.getTime())}
                          label={`Trend of ${g.title}`}
                          className="hidden sm:block"
                        />
                        <span className="w-14 text-right text-[13px] font-semibold tabular">
                          {formatNumber(g.occurrences)}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Surface>
            <Surface>
              <SurfaceHeader
                title="Services"
                action={
                  <Link
                    href="/services"
                    className={buttonVariants({ variant: "ghost", size: "xs" })}
                  >
                    Health
                  </Link>
                }
              />
              {!o ? (
                <Skeleton className="mx-5 mb-5 h-40" />
              ) : o.services.length === 0 ? (
                <EmptyState
                  compact
                  icon={ActivityIcon}
                  title="No services yet"
                  description="Services appear as soon as they send a line."
                />
              ) : (
                <ul className="px-2 pb-3">
                  {o.services.slice(0, 7).map((s) => (
                    <li key={s.name} className="flex items-center gap-3 rounded-lg px-3 py-2">
                      <ServiceStatusChip status={s.status} />
                      <span className="min-w-0 flex-1 truncate text-[13px] font-medium">
                        {s.name}
                      </span>
                      <span className="text-[12px] text-muted-foreground tabular">
                        {formatNumber(s.total)} lines
                      </span>
                      <span
                        className={
                          s.error_rate >= 0.05
                            ? "w-14 text-right text-[12px] font-semibold text-danger tabular"
                            : "w-14 text-right text-[12px] tabular"
                        }
                      >
                        {formatPercent(s.error_rate)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Surface>
          </div>
          <div className="grid gap-5 xl:grid-cols-2">
            <Surface>
              <SurfaceHeader
                title="AI investigations"
                description={
                  o
                    ? `${formatTokenCount(o.ai_tokens_30d)} model tokens in the last 30 days`
                    : undefined
                }
                action={
                  <Link
                    href="/investigations"
                    className={buttonVariants({ variant: "ghost", size: "xs" })}
                  >
                    All
                  </Link>
                }
              />
              {!o ? (
                <Skeleton className="mx-5 mb-5 h-32" />
              ) : o.investigations.length === 0 ? (
                <EmptyState
                  compact
                  icon={SparklesIcon}
                  title={o.ai_provider_configured ? "No investigations yet" : "AI is optional"}
                  description={
                    o.ai_provider_configured
                      ? "Open an error group and choose Investigate with AI."
                      : "Everything above works without AI. Add a provider in Settings to get cited root cause reports."
                  }
                  action={
                    <Link
                      href={o.ai_provider_configured ? "/errors" : "/settings?tab=ai"}
                      className={buttonVariants({ size: "sm", variant: "outline" })}
                    >
                      {o.ai_provider_configured ? "Pick an error" : "Add a provider"}
                      <ArrowRightIcon />
                    </Link>
                  }
                />
              ) : (
                <ul className="px-2 pb-3">
                  {o.investigations.map((inv) => (
                    <li key={inv.id}>
                      <Link
                        href={`/investigations/${inv.id}`}
                        className="flex items-start gap-3 rounded-lg px-3 py-2 hover:bg-muted/60"
                      >
                        <InvestigationStatusChip status={inv.status} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13px] font-medium">
                            {inv.title}
                          </span>
                          <span className="line-clamp-2 text-[12px] text-muted-foreground">
                            {inv.root_cause || inv.error || "Working"}
                          </span>
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Surface>
            <Surface>
              <SurfaceHeader
                title="Recent alerts"
                action={
                  <Link href="/alerts" className={buttonVariants({ variant: "ghost", size: "xs" })}>
                    Rules
                  </Link>
                }
              />
              {!o ? (
                <Skeleton className="mx-5 mb-5 h-32" />
              ) : o.alerts.length === 0 ? (
                <EmptyState
                  compact
                  icon={BellRingIcon}
                  title="No alerts fired"
                  description="Threshold and anomaly rules notify by email, webhook or Slack when live data crosses them."
                />
              ) : (
                <ul className="px-2 pb-3">
                  {o.alerts.map((h) => (
                    <li key={h.id}>
                      <Link
                        href={`/alerts/${h.rule_id}`}
                        className="flex items-start gap-3 rounded-lg px-3 py-2 hover:bg-muted/60"
                      >
                        <AlertEventChip event={h.event} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13px] font-medium">
                            {h.rule_name}
                          </span>
                          <span className="line-clamp-2 text-[12px] text-muted-foreground">
                            {h.message}
                          </span>
                        </span>
                        <span className="text-[12px] whitespace-nowrap text-subtle">
                          {formatRelative(h.at, now)}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Surface>
          </div>
        </div>
      )}
    </>
  );
}
