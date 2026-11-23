"use client";

import { BugIcon, SearchIcon } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { GroupStatusChip, LevelChip } from "@/components/badges";
import { hourlySeries, Sparkline } from "@/components/charts/sparkline";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { useProjectScope } from "@/components/project-select";
import { NoProject } from "@/components/send-first-log";
import { Segmented } from "@/components/segmented";
import { Surface } from "@/components/surface";
import { TableSkeleton } from "@/components/table-skeleton";
import { Input } from "@/components/ui/input";
import { SimpleSelect } from "@/components/ui/select";
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
import { formatNumber, formatRelative } from "@/lib/format";

import { useErrorGroups, type ErrorFilters } from "../api";

const STATUS_OPTIONS: { value: ErrorFilters["status"]; label: string }[] = [
  { value: "open", label: "Open" },
  { value: "resolved", label: "Resolved" },
  { value: "ignored", label: "Ignored" },
  { value: "", label: "All" },
];

/**
 * Error Intelligence: every error line is fingerprinted at ingestion (exception type plus
 * the top in-app frames, or a message template), so repeats of the same bug are one row
 * with its first and last time, count, affected services and a 24 hour trend.
 */
export function ErrorsScreen() {
  const projects = useProjects();
  const [projectId] = useProjectScope();
  const now = useNow(60_000);
  const [f, setF] = React.useState<ErrorFilters>({
    status: "open",
    q: "",
    service: "",
    sort: "last_seen",
  });
  const [draft, setDraft] = React.useState("");
  const groups = useErrorGroups(projectId, f);
  const services = React.useMemo(
    () => [...new Set((groups.data?.items ?? []).flatMap((g) => g.services))].sort(),
    [groups.data]
  );

  if (projects.isSuccess && projects.data.length === 0) {
    return (
      <>
        <PageHeader title="Errors" />
        <Surface>
          <NoProject />
        </Surface>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Errors"
        description="Errors grouped by fingerprint: the same bug is one row however many times, services and line numbers it shows up with."
      />
      <div className="mb-4 flex flex-col gap-2 lg:flex-row lg:items-center">
        <Segmented
          ariaLabel="Status"
          value={f.status}
          onChange={(status) => setF({ ...f, status })}
          options={STATUS_OPTIONS}
          className="lg:w-80"
        />
        <form
          role="search"
          className="relative flex-1"
          onSubmit={(e) => {
            e.preventDefault();
            setF({ ...f, q: draft.trim() });
          }}
        >
          <SearchIcon
            className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle"
            aria-hidden
          />
          <Input
            aria-label="Search errors"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Search titles, culprits and messages"
            className="pl-9"
          />
        </form>
        <SimpleSelect
          aria-label="Service"
          className="lg:w-44"
          value={f.service}
          onValueChange={(service) => setF({ ...f, service })}
          options={[
            { value: "", label: "Every service" },
            ...services.map((s) => ({ value: s, label: s })),
          ]}
        />
        <SimpleSelect
          aria-label="Sort"
          className="lg:w-44"
          value={f.sort}
          onValueChange={(v) => setF({ ...f, sort: v as ErrorFilters["sort"] })}
          options={[
            { value: "last_seen", label: "Last seen" },
            { value: "first_seen", label: "Newest first" },
            { value: "occurrences", label: "Most frequent" },
          ]}
        />
      </div>
      <Surface>
        {groups.isPending ? (
          <TableSkeleton rows={8} cols={5} />
        ) : groups.isError ? (
          <ErrorState
            compact
            error={groups.error}
            title="Could not load errors"
            onRetry={() => void groups.refetch()}
          />
        ) : groups.data.items.length === 0 ? (
          <EmptyState
            icon={BugIcon}
            title={f.status === "open" && !f.q && !f.service ? "No open errors" : "No errors match"}
            description={
              f.status === "open" && !f.q && !f.service
                ? "Error and fatal lines, and any line with a stack trace, are grouped here automatically. Nothing is failing right now."
                : "Clear the search or pick another status to see more groups."
            }
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-1/2">Error</TableHead>
                <TableHead className="hidden md:table-cell">Services</TableHead>
                <TableHead className="hidden lg:table-cell">Last 24 h</TableHead>
                <TableHead className="text-right">Events</TableHead>
                <TableHead className="hidden sm:table-cell">Last seen</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {groups.data.items.map((g) => (
                <TableRow key={g.id}>
                  <TableCell className="w-1/2 max-w-0 min-w-0">
                    <Link
                      href={`/errors/${g.id}`}
                      className="block min-w-0 rounded focus-visible:outline-2 focus-visible:outline-ring"
                    >
                      <span className="flex items-center gap-2">
                        <LevelChip level={g.level} />
                        <GroupStatusChip status={g.status} />
                        {g.regressed_at && g.status === "open" && (
                          <span className="text-[11px] font-semibold text-warning">Regressed</span>
                        )}
                      </span>
                      <span
                        className="mt-1 block truncate font-medium text-foreground"
                        title={g.title}
                      >
                        {g.title}
                      </span>
                      <span className="block truncate font-mono text-[11.5px] text-subtle">
                        {g.culprit || g.sample_message}
                      </span>
                    </Link>
                  </TableCell>
                  <TableCell className="hidden text-[12.5px] text-muted-foreground md:table-cell">
                    {g.services.join(", ")}
                  </TableCell>
                  <TableCell className="hidden lg:table-cell">
                    <Sparkline
                      values={hourlySeries(g.trend ?? [], 24, now.getTime())}
                      label={`Hourly occurrences of ${g.title}`}
                    />
                  </TableCell>
                  <TableCell className="text-right font-medium tabular">
                    {formatNumber(g.occurrences)}
                  </TableCell>
                  <TableCell className="hidden text-[12.5px] whitespace-nowrap text-muted-foreground sm:table-cell">
                    {formatRelative(g.last_seen, now)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Surface>
    </>
  );
}
