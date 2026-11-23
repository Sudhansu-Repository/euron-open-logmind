"use client";

import {
  ArrowLeftIcon,
  CheckIcon,
  EyeOffIcon,
  RotateCcwIcon,
  ScrollTextIcon,
  SparklesIcon,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { toast } from "sonner";

import { GroupStatusChip, InvestigationStatusChip, LevelChip } from "@/components/badges";
import { ChartTooltipCard } from "@/components/charts/chart-tooltip";
import { ErrorState } from "@/components/error-state";
import { GatedButton } from "@/components/gated";
import { KeyValues } from "@/components/kv";
import { PageHeader } from "@/components/page-header";
import { useProjectScope } from "@/components/project-select";
import { Stat } from "@/components/stat";
import { Surface, SurfaceHeader } from "@/components/surface";
import { TableSkeleton } from "@/components/table-skeleton";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useInvestigate, useInvestigations } from "@/features/investigations/api";
import { LogDetailSheet } from "@/features/logs/components/log-detail";
import { LogRow, type RowLine } from "@/features/logs/components/log-row";
import { useChartColors } from "@/hooks/use-chart-colors";
import { errorMessage } from "@/lib/api/errors";
import { formatDateTime, formatNumber, formatRelative } from "@/lib/format";

import { useErrorGroup, useGroupLines, useSetGroupStatus } from "../api";

function TrendChart({ points }: { points: { hour: string; count: number }[] }) {
  const c = useChartColors();
  const data = points.map((p) => ({ at: new Date(p.hour).getTime(), count: p.count }));
  const fmt = new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    hour12: false,
  });
  return (
    <div className="h-40 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
          <XAxis
            dataKey="at"
            tickFormatter={(v: number) => fmt.format(new Date(v))}
            tick={{ fill: c["chart-axis"], fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            minTickGap={30}
          />
          <YAxis
            allowDecimals={false}
            tick={{ fill: c["chart-axis"], fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={44}
          />
          <Tooltip
            cursor={{ fill: c["chart-grid"], opacity: 0.5 }}
            content={({ active, payload, label }) =>
              active && payload?.length ? (
                <ChartTooltipCard
                  title={fmt.format(new Date(Number(label)))}
                  rows={[
                    {
                      label: "Occurrences",
                      value: formatNumber(Number(payload[0]?.value ?? 0)),
                      color: c["level-error"],
                    },
                  ]}
                />
              ) : null
            }
          />
          <Bar
            dataKey="count"
            fill={c["level-error"]}
            radius={[3, 3, 0, 0]}
            maxBarSize={18}
            isAnimationActive={false}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ErrorDetail({ id }: { id: string }) {
  const [projectId] = useProjectScope();
  const router = useRouter();
  const params = useSearchParams();
  const group = useErrorGroup(projectId, id);
  const g = group.data;
  const lines = useGroupLines(
    projectId,
    id,
    g ? new Date(new Date(g.first_seen).getTime() - 1000).toISOString() : ""
  );
  const investigations = useInvestigations(projectId, id);
  const investigate = useInvestigate();
  const setStatus = useSetGroupStatus(projectId);
  const [open, setOpen] = React.useState<RowLine | null>(null);
  const autoStarted = React.useRef(false);

  const start = React.useCallback(() => {
    if (!projectId) return;
    investigate.mutate(
      { project_id: projectId, error_group_id: id },
      {
        onSuccess: (inv) => router.push(`/investigations/${inv.id}`),
        onError: (err) => toast.error(errorMessage(err)),
      }
    );
  }, [investigate, projectId, id, router]);

  React.useEffect(() => {
    if (params.get("investigate") === "1" && g && !autoStarted.current) {
      autoStarted.current = true;
      start();
    }
  }, [params, g, start]);

  if (group.isError) {
    return (
      <Surface>
        <ErrorState
          error={group.error}
          title="Could not load this error group"
          onRetry={() => void group.refetch()}
        />
      </Surface>
    );
  }

  const change = (status: "open" | "resolved" | "ignored") =>
    setStatus.mutate(
      { id, status },
      {
        onSuccess: () => toast.success(`Marked ${status}.`),
        onError: (err) => toast.error(errorMessage(err)),
      }
    );

  return (
    <>
      <PageHeader
        eyebrow={
          <Link
            href="/errors"
            className="inline-flex items-center gap-1 text-[12.5px] text-muted-foreground hover:text-foreground"
          >
            <ArrowLeftIcon className="size-3.5" />
            Errors
          </Link>
        }
        title={
          g ? (
            <span className="break-words">{g.title}</span>
          ) : (
            <Skeleton className="h-7 w-96 max-w-full" />
          )
        }
        description={g ? g.culprit || "No stack trace: grouped by message template." : undefined}
        actions={
          g && (
            <>
              <GatedButton
                need="investigate"
                onClick={start}
                disabled={investigate.isPending}
                data-qa="investigate"
              >
                <SparklesIcon />
                {investigate.isPending ? "Starting..." : "Investigate with AI"}
              </GatedButton>
              {g.status === "open" ? (
                <>
                  <GatedButton
                    need="triageErrors"
                    variant="outline"
                    onClick={() => change("resolved")}
                    disabled={setStatus.isPending}
                  >
                    <CheckIcon />
                    Resolve
                  </GatedButton>
                  <GatedButton
                    need="triageErrors"
                    variant="ghost"
                    onClick={() => change("ignored")}
                    disabled={setStatus.isPending}
                  >
                    <EyeOffIcon />
                    Ignore
                  </GatedButton>
                </>
              ) : (
                <GatedButton
                  need="triageErrors"
                  variant="outline"
                  onClick={() => change("open")}
                  disabled={setStatus.isPending}
                >
                  <RotateCcwIcon />
                  Reopen
                </GatedButton>
              )}
            </>
          )
        }
      />
      <div className="space-y-5">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat
            label="Occurrences"
            loading={!g}
            value={g ? formatNumber(g.occurrences) : ""}
            detail="Every line with this fingerprint"
          />
          <Stat
            label="First seen"
            loading={!g}
            value={g ? formatRelative(g.first_seen) : ""}
            detail={g ? formatDateTime(g.first_seen) : ""}
          />
          <Stat
            label="Last seen"
            loading={!g}
            value={g ? formatRelative(g.last_seen) : ""}
            detail={g ? formatDateTime(g.last_seen) : ""}
          />
          <Stat
            label="Status"
            loading={!g}
            value={g ? <GroupStatusChip status={g.status} /> : ""}
            detail={
              g?.regressed_at
                ? `Regressed ${formatRelative(g.regressed_at)}`
                : g?.resolved_at
                  ? `Resolved ${formatRelative(g.resolved_at)}`
                  : "Not resolved yet"
            }
          />
        </div>
        <div className="grid gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <Surface>
            <SurfaceHeader
              title="Occurrences per hour"
              description="From the first occurrence, up to the last seven days"
            />
            <div className="px-5 pb-5">
              {g ? <TrendChart points={g.trend ?? []} /> : <Skeleton className="h-40 w-full" />}
            </div>
          </Surface>
          <Surface>
            <SurfaceHeader title="Details" />
            <div className="px-5 pb-5">
              {g ? (
                <KeyValues
                  items={[
                    { label: "Level", value: <LevelChip level={g.level} /> },
                    { label: "Exception", value: g.exception_type || "n/a" },
                    { label: "Services", value: g.services.join(", ") },
                    { label: "Environments", value: g.environments.join(", ") },
                    {
                      label: "Fingerprint",
                      value: <span className="font-mono text-[12px]">{g.fingerprint}</span>,
                    },
                  ]}
                />
              ) : (
                <Skeleton className="h-32 w-full" />
              )}
            </div>
          </Surface>
        </div>
        <Surface>
          <SurfaceHeader
            title="AI investigations"
            description="Root cause reports for this group. Every claim cites real stored lines."
          />
          {investigations.isPending ? (
            <TableSkeleton rows={2} cols={3} />
          ) : (investigations.data ?? []).length === 0 ? (
            <p className="px-5 pb-5 text-[13px] text-muted-foreground">
              No investigation yet. Investigate with AI to get a root cause with cited evidence;
              search and grouping never need AI.
            </p>
          ) : (
            <ul className="px-2 pb-3">
              {(investigations.data ?? []).map((inv) => (
                <li key={inv.id}>
                  <Link
                    href={`/investigations/${inv.id}`}
                    className="flex items-center gap-3 rounded-lg px-3 py-2 hover:bg-muted/60"
                  >
                    <InvestigationStatusChip status={inv.status} />
                    <span className="min-w-0 flex-1 truncate text-[13px]">
                      {inv.root_cause || inv.error || "Investigating"}
                    </span>
                    <span className="text-[12px] whitespace-nowrap text-muted-foreground">
                      {formatRelative(inv.created_at)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Surface>
        <Surface>
          <SurfaceHeader
            title="Recent lines"
            description="The newest occurrences, with their full context one click away"
            action={
              <Link
                href={`/logs?error_group_id=${id}&range=7d`}
                className={buttonVariants({ variant: "ghost", size: "xs" })}
              >
                <ScrollTextIcon />
                All lines
              </Link>
            }
          />
          {lines.isPending ? (
            <TableSkeleton rows={5} cols={3} />
          ) : lines.isError ? (
            <ErrorState compact error={lines.error} title="Could not load lines" />
          ) : (
            <ul className="pb-2">
              {lines.data.items.map((l) => (
                <LogRow key={l.event_id} line={l} onOpen={setOpen} />
              ))}
            </ul>
          )}
        </Surface>
      </div>
      <LogDetailSheet
        projectId={projectId}
        eventId={open?.event_id ?? null}
        at={open?.timestamp ?? null}
        onClose={() => setOpen(null)}
      />
    </>
  );
}
