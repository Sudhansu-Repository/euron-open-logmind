"use client";

import { ScrollTextIcon, SearchIcon } from "lucide-react";
import * as React from "react";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { JsonView } from "@/components/json-view";
import { Surface, SurfaceHeader } from "@/components/surface";
import { TableSkeleton } from "@/components/table-skeleton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatDateTime } from "@/lib/format";

import { useAuditLog } from "../api";

/** The append-only audit log, newest first, with cursor "load more" (next_cursor). */
export function AuditPanel() {
  const [draft, setDraft] = React.useState("");
  const [action, setAction] = React.useState("");
  const [open, setOpen] = React.useState<number | null>(null);
  const log = useAuditLog(action);
  const items = log.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <Surface>
      <SurfaceHeader
        title="Audit log"
        description="Every change to projects, keys, redaction, AI providers, alerts, error statuses and people: who did it, when, and from where."
      />
      <form
        className="flex gap-2 px-5 pb-3"
        onSubmit={(e) => {
          e.preventDefault();
          setAction(draft.trim());
        }}
      >
        <div className="relative flex-1 sm:max-w-xs">
          <SearchIcon
            className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle"
            aria-hidden
          />
          <Input
            aria-label="Filter by action"
            className="pl-9"
            placeholder="Exact action, e.g. project.updated"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
        </div>
        <Button type="submit" variant="outline">
          Filter
        </Button>
        {action && (
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              setDraft("");
              setAction("");
            }}
          >
            Clear
          </Button>
        )}
      </form>
      {log.isPending ? (
        <TableSkeleton rows={6} cols={4} />
      ) : log.isError ? (
        <ErrorState
          compact
          error={log.error}
          title="Could not load the audit log"
          onRetry={() => void log.refetch()}
        />
      ) : items.length === 0 ? (
        <EmptyState
          compact
          icon={ScrollTextIcon}
          title={action ? `No ${action} entries` : "No audit entries yet"}
          description={
            action
              ? "Actions are matched exactly. Clear the filter to see everything."
              : "Changes made from the dashboard or the API are recorded here as they happen."
          }
        />
      ) : (
        <ul className="px-2 pb-2">
          {items.map((e) => (
            <li key={e.id}>
              <button
                type="button"
                aria-expanded={open === e.id}
                onClick={() => setOpen(open === e.id ? null : e.id)}
                className="grid w-full grid-cols-[1fr_auto] gap-x-3 gap-y-0.5 rounded-lg px-3 py-2 text-left hover:bg-muted/60 focus-visible:outline-2 focus-visible:outline-ring sm:grid-cols-[11rem_1fr_auto]"
              >
                <span className="text-[12px] text-muted-foreground sm:order-none">
                  {formatDateTime(e.at)}
                </span>
                <span className="col-span-2 min-w-0 truncate text-[13px] sm:col-span-1">
                  <span className="font-mono text-[12px] font-medium">{e.action}</span>
                  <span className="text-muted-foreground"> by {e.actor_name ?? e.actor_type}</span>
                  {e.target_type && <span className="text-subtle"> on {e.target_type}</span>}
                </span>
                <span className="hidden text-right font-mono text-[11px] text-subtle sm:block">
                  {e.ip ?? ""}
                </span>
              </button>
              {open === e.id && (
                <div className="px-3 pb-3">
                  <JsonView
                    value={{ actor_id: e.actor_id, target_id: e.target_id, ...e.details }}
                    maxHeight={220}
                    label="Audit details"
                  />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {log.hasNextPage && (
        <div className="flex justify-center px-5 pb-4">
          <Button
            variant="outline"
            size="sm"
            disabled={log.isFetchingNextPage}
            onClick={() => void log.fetchNextPage()}
          >
            {log.isFetchingNextPage ? "Loading..." : "Load older entries"}
          </Button>
        </div>
      )}
    </Surface>
  );
}
