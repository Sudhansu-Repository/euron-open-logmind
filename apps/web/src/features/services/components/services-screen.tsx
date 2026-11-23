"use client";

import { ActivityIcon, ScrollTextIcon } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { ServiceStatusChip } from "@/components/badges";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Hint } from "@/components/hint";
import { PageHeader } from "@/components/page-header";
import { useProjectScope } from "@/components/project-select";
import { NoProject } from "@/components/send-first-log";
import { Segmented } from "@/components/segmented";
import { Surface } from "@/components/surface";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useProjects } from "@/features/projects/api";
import type { ServiceHealth } from "@/lib/api/types";
import { formatNumber, formatPercent, formatRelative } from "@/lib/format";

import { useServices } from "../api";

const HOURS = [
  { value: "6", label: "6h" },
  { value: "24", label: "24h" },
  { value: "168", label: "7d" },
] as const;

function Bars({ s }: { s: ServiceHealth }) {
  const max = Math.max(1, ...s.series.map((p) => p.total));
  return (
    <div
      className="flex h-10 items-end gap-[2px]"
      role="img"
      aria-label={`Hourly volume and errors for ${s.name}`}
    >
      {s.series.slice(-48).map((p) => (
        <span
          key={p.at}
          className="relative w-1.5 flex-1 rounded-sm bg-info/25"
          style={{ height: `${Math.max(6, (p.total / max) * 100)}%` }}
        >
          {p.errors > 0 && (
            <span
              className="absolute inset-x-0 bottom-0 rounded-sm bg-danger"
              style={{ height: `${Math.max(12, (p.errors / Math.max(1, p.total)) * 100)}%` }}
            />
          )}
        </span>
      ))}
    </div>
  );
}

/**
 * Service Health from ingested logs alone: volume, errors, error rate, availability and
 * status per service, from the ClickHouse per-minute rollup. No APM agent needed.
 */
export function ServicesScreen() {
  const projects = useProjects();
  const [projectId] = useProjectScope();
  const [hours, setHours] = React.useState<(typeof HOURS)[number]["value"]>("24");
  const services = useServices(projectId, Number(hours));

  if (projects.isSuccess && projects.data.length === 0) {
    return (
      <>
        <PageHeader title="Services" />
        <Surface>
          <NoProject />
        </Surface>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Services"
        description="Health of every service that sends logs, worked out from the logs themselves: volume, errors, error rate and how often it stayed under 5% errors."
        actions={
          <Segmented
            ariaLabel="Window"
            value={hours}
            onChange={setHours}
            options={[...HOURS]}
            className="w-40"
          />
        }
      />
      {services.isPending ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-44 w-full rounded-xl" />
          ))}
        </div>
      ) : services.isError ? (
        <Surface>
          <ErrorState
            error={services.error}
            title="Could not load services"
            onRetry={() => void services.refetch()}
          />
        </Surface>
      ) : services.data.services.length === 0 ? (
        <Surface>
          <EmptyState
            icon={ActivityIcon}
            title="No services yet"
            description="Every service name on an ingested line shows up here with its health. Send a line with a service field to start."
          />
        </Surface>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" data-qa="service-grid">
          {services.data.services.map((s) => (
            <section key={s.name} className="surface flex flex-col gap-3 p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <h2 className="truncate text-[14px] font-semibold">{s.name}</h2>
                  <p className="text-[12px] text-muted-foreground">
                    Last line {formatRelative(s.last_seen_at)}
                  </p>
                </div>
                <ServiceStatusChip status={s.status} />
              </div>
              <Bars s={s} />
              <dl className="grid grid-cols-3 gap-2 text-[12px]">
                <div>
                  <dt className="text-subtle">Lines</dt>
                  <dd className="text-[15px] font-semibold tabular">{formatNumber(s.total)}</dd>
                </div>
                <div>
                  <dt className="text-subtle">Error rate</dt>
                  <dd
                    className={
                      s.error_rate >= 0.05
                        ? "text-[15px] font-semibold text-danger tabular"
                        : "text-[15px] font-semibold tabular"
                    }
                  >
                    {formatPercent(s.error_rate)}
                  </dd>
                </div>
                <div>
                  <dt className="flex items-center gap-1 text-subtle">
                    Availability{" "}
                    <Hint text="The share of five-minute windows with logs in which this service's error rate stayed under 5%." />
                  </dt>
                  <dd className="text-[15px] font-semibold tabular">
                    {formatPercent(s.availability)}
                  </dd>
                </div>
              </dl>
              <div className="mt-auto flex items-center justify-between gap-2 text-[12px] text-muted-foreground">
                <span>
                  {s.open_error_groups > 0 ? (
                    <Link href="/errors" className="font-medium text-danger hover:underline">
                      {s.open_error_groups} open error group{s.open_error_groups === 1 ? "" : "s"}
                    </Link>
                  ) : (
                    "No open errors"
                  )}
                  {s.anomalies > 0 && (
                    <span className="ml-2 font-medium text-warning">
                      {s.anomalies} spike{s.anomalies === 1 ? "" : "s"}
                    </span>
                  )}
                </span>
                <Link
                  href={`/logs?service=${encodeURIComponent(s.name)}&range=24h`}
                  className={buttonVariants({ variant: "ghost", size: "xs" })}
                >
                  <ScrollTextIcon />
                  Logs
                </Link>
              </div>
            </section>
          ))}
        </div>
      )}
    </>
  );
}
