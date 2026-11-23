"use client";

import { FilterXIcon, SearchIcon, XIcon } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { VolumeChart, toVolumePoints } from "@/components/charts/volume-chart";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { useProjectScope } from "@/components/project-select";
import { NoProject, SendFirstLog } from "@/components/send-first-log";
import { Segmented } from "@/components/segmented";
import { Surface, SurfaceHeader } from "@/components/surface";
import { TableSkeleton } from "@/components/table-skeleton";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useProjects } from "@/features/projects/api";
import { cn } from "@/lib/cn";
import { formatNumber, plural } from "@/lib/format";
import { LEVELS, levelColor } from "@/lib/labels";

import { useFacets, useHistogram, useLogSearch } from "../api";
import {
  activeCount,
  EMPTY_FILTERS,
  filtersFromParams,
  filtersToParams,
  RANGES,
  toggle,
  type LogFilters,
  type RangeKey,
} from "../filters";
import { LogDetailSheet } from "./log-detail";
import { LogRow, type RowLine } from "./log-row";

const RANGE_OPTIONS: { value: RangeKey; label: string }[] = (Object.keys(RANGES) as RangeKey[]).map(
  (r) => ({ value: r, label: r })
);

function FacetGroup({
  title,
  values,
  selected,
  onToggle,
  color,
}: {
  title: string;
  values: { value: string; count: number }[];
  selected: string[];
  onToggle: (v: string) => void;
  color?: (v: string) => string;
}) {
  if (!values.length) return null;
  return (
    <div>
      <h3 className="mb-1.5 px-2 text-[11px] font-semibold tracking-[0.04em] text-subtle uppercase">
        {title}
      </h3>
      <ul className="space-y-0.5">
        {values.map((v) => {
          const on = selected.includes(v.value);
          return (
            <li key={v.value}>
              <button
                type="button"
                aria-pressed={on}
                onClick={() => onToggle(v.value)}
                className={cn(
                  "flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-[12.5px] hover:bg-muted",
                  on && "bg-primary-soft font-medium text-foreground hover:bg-primary-soft"
                )}
              >
                {color && (
                  <span
                    aria-hidden
                    className="size-2 rounded-full"
                    style={{ background: color(v.value) }}
                  />
                )}
                <span className="min-w-0 flex-1 truncate">{v.value}</span>
                <span className="text-[11.5px] text-subtle tabular">{formatNumber(v.count)}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/**
 * The Log Explorer: keyword search, service, environment and level filters, a time range,
 * a level histogram and the matching lines newest first. Filters live in the URL, so a
 * search is a shareable link. Works with no AI configured (A5).
 */
export function LogExplorer() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const projects = useProjects();
  const [projectId] = useProjectScope();
  const filters = React.useMemo(
    () => filtersFromParams(new URLSearchParams(params.toString())),
    [params]
  );
  const [now, setNow] = React.useState(() => Date.now());
  const [draft, setDraft] = React.useState(filters.q);
  const [open, setOpen] = React.useState<RowLine | null>(null);
  React.useEffect(() => setDraft(filters.q), [filters.q]);

  const setFilters = React.useCallback(
    (next: LogFilters) => {
      const qs = filtersToParams(next).toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
      setNow(Date.now());
    },
    [router, pathname]
  );

  const search = useLogSearch(projectId, filters, now);
  const histogram = useHistogram(projectId, filters, now);
  const facets = useFacets(projectId, filters, now);
  const lines = React.useMemo(
    () => (search.data?.pages ?? []).flatMap((p) => p.items),
    [search.data]
  );
  const points = React.useMemo(
    () => toVolumePoints(histogram.data?.buckets ?? []),
    [histogram.data]
  );
  const count = activeCount(filters);

  if (projects.isSuccess && projects.data.length === 0) {
    return (
      <>
        <PageHeader title="Log explorer" description="Search every line your services sent." />
        <Surface>
          <NoProject />
        </Surface>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Log explorer"
        description="Search every stored line by keyword, service, environment, level and time. Click a line for its fields, stack trace and the lines around it."
        actions={
          <Segmented
            ariaLabel="Time range"
            value={filters.range}
            onChange={(range) => setFilters({ ...filters, range })}
            options={RANGE_OPTIONS}
            className="w-64"
          />
        }
      />
      <form
        className="mb-4 flex gap-2"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          setFilters({ ...filters, q: draft.trim() });
        }}
      >
        <div className="relative flex-1">
          <SearchIcon
            className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle"
            aria-hidden
          />
          <Input
            aria-label="Search logs"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Search messages and stack traces, for example: timeout payments"
            className="pl-9"
            data-qa="log-search"
          />
        </div>
        <Button type="submit">Search</Button>
        {count > 0 && (
          <Button
            type="button"
            variant="ghost"
            onClick={() => setFilters({ ...EMPTY_FILTERS, range: filters.range })}
          >
            <FilterXIcon />
            <span className="hidden sm:inline">Clear</span>
          </Button>
        )}
      </form>
      {(filters.traceId || filters.requestId || filters.errorGroupId) && (
        <div className="mb-4 flex flex-wrap gap-2">
          {filters.traceId && (
            <Chip tone="cyan">
              trace {filters.traceId.slice(0, 12)}
              <button
                type="button"
                aria-label="Remove trace filter"
                onClick={() => setFilters({ ...filters, traceId: "" })}
              >
                <XIcon />
              </button>
            </Chip>
          )}
          {filters.requestId && (
            <Chip tone="cyan">
              request {filters.requestId}
              <button
                type="button"
                aria-label="Remove request filter"
                onClick={() => setFilters({ ...filters, requestId: "" })}
              >
                <XIcon />
              </button>
            </Chip>
          )}
          {filters.errorGroupId && (
            <Chip tone="danger">
              one error group
              <button
                type="button"
                aria-label="Remove error group filter"
                onClick={() => setFilters({ ...filters, errorGroupId: "" })}
              >
                <XIcon />
              </button>
            </Chip>
          )}
        </div>
      )}
      <div className="grid gap-5 lg:grid-cols-[220px_minmax(0,1fr)]">
        <aside className="surface h-fit space-y-4 p-3" aria-label="Filters">
          {facets.isPending ? (
            <Skeleton className="h-40 w-full" />
          ) : facets.isError ? (
            <ErrorState compact error={facets.error} title="Could not load filters" />
          ) : (
            <>
              <FacetGroup
                title="Level"
                values={LEVELS.map((l) => ({
                  value: l,
                  count: facets.data.levels.find((f) => f.value === l)?.count ?? 0,
                })).filter((v) => v.count > 0 || filters.levels.includes(v.value))}
                selected={filters.levels}
                onToggle={(v) => setFilters({ ...filters, levels: toggle(filters.levels, v) })}
                color={levelColor}
              />
              <FacetGroup
                title="Service"
                values={facets.data.services}
                selected={filters.services}
                onToggle={(v) => setFilters({ ...filters, services: toggle(filters.services, v) })}
              />
              <FacetGroup
                title="Environment"
                values={facets.data.environments}
                selected={filters.environments}
                onToggle={(v) =>
                  setFilters({ ...filters, environments: toggle(filters.environments, v) })
                }
              />
              {facets.data.services.length === 0 && (
                <p className="px-2 text-[12px] text-muted-foreground">
                  No lines in the last {filters.range}.
                </p>
              )}
            </>
          )}
        </aside>
        <div className="min-w-0 space-y-5">
          <Surface>
            <SurfaceHeader
              title="Volume"
              description={
                histogram.data
                  ? `${plural(histogram.data.total, "line")} in the last ${filters.range}${count ? " matching the filters" : ""}`
                  : "Lines per bucket, by level"
              }
            />
            <div className="px-5 pb-4">
              {histogram.isPending ? (
                <Skeleton className="h-40 w-full" />
              ) : histogram.isError ? (
                <ErrorState compact error={histogram.error} title="Could not load the histogram" />
              ) : (
                <VolumeChart data={points} spanMs={RANGES[filters.range]} height={150} />
              )}
            </div>
          </Surface>
          <Surface>
            <SurfaceHeader
              title="Lines"
              description={
                search.data
                  ? `Newest first. ${search.data.pages[0]?.took_ms ?? 0} ms in ClickHouse.`
                  : "Newest first"
              }
              action={
                <Button variant="ghost" size="xs" onClick={() => setNow(Date.now())}>
                  Refresh
                </Button>
              }
            />
            {search.isPending ? (
              <TableSkeleton rows={10} cols={3} />
            ) : search.isError ? (
              <ErrorState
                compact
                error={search.error}
                title="Could not search logs"
                onRetry={() => void search.refetch()}
              />
            ) : lines.length === 0 ? (
              count > 0 ? (
                <div className="px-5 pb-8 text-center text-[13px] text-muted-foreground">
                  Nothing matches these filters in the last {filters.range}. Widen the time range or
                  clear a filter.
                </div>
              ) : (
                <SendFirstLog />
              )
            ) : (
              <>
                <ul className="pb-2" data-qa="log-list">
                  {lines.map((l) => (
                    <LogRow
                      key={l.event_id}
                      line={l}
                      selected={open?.event_id === l.event_id}
                      onOpen={setOpen}
                    />
                  ))}
                </ul>
                {search.hasNextPage && (
                  <div className="flex justify-center px-5 pb-4">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => void search.fetchNextPage()}
                      disabled={search.isFetchingNextPage}
                    >
                      {search.isFetchingNextPage ? "Loading..." : "Load older lines"}
                    </Button>
                  </div>
                )}
              </>
            )}
          </Surface>
        </div>
      </div>
      <LogDetailSheet
        projectId={projectId}
        eventId={open?.event_id ?? null}
        at={open?.timestamp ?? null}
        onClose={() => setOpen(null)}
        onFilterTrace={(traceId) => {
          setOpen(null);
          setFilters({ ...EMPTY_FILTERS, range: "24h", traceId });
        }}
      />
    </>
  );
}
