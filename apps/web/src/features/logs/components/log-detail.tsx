"use client";

import { BugIcon, ExternalLinkIcon, FilterIcon, SparklesIcon } from "lucide-react";
import Link from "next/link";

import { LevelChip, RedactedCount } from "@/components/badges";
import { CopyButton } from "@/components/copy-button";
import { ErrorState } from "@/components/error-state";
import { JsonView } from "@/components/json-view";
import { KeyValues, Mono } from "@/components/kv";
import { buttonVariants } from "@/components/ui/button";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import type { LogEvent } from "@/lib/api/types";
import { formatDateTime, formatTime } from "@/lib/format";

import { useLogContext } from "../api";

function ContextList({
  title,
  lines,
  current,
}: {
  title: string;
  lines: LogEvent[];
  current?: string;
}) {
  if (!lines.length) return null;
  return (
    <div>
      <h3 className="mb-1.5 text-[11px] font-semibold tracking-[0.04em] text-subtle uppercase">
        {title}
      </h3>
      <ol className="overflow-hidden rounded-lg bg-muted/60 font-mono text-[12px]">
        {lines.map((l) => (
          <li
            key={l.event_id}
            className={l.event_id === current ? "bg-primary-soft px-3 py-1" : "px-3 py-1"}
          >
            <span className="mr-2 text-subtle tabular">{formatTime(l.timestamp)}</span>
            <span className="mr-2 text-muted-foreground">{l.service}</span>
            <span className="break-words">{l.message}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

/**
 * One line in full: its fields, attributes, stack trace, the lines around it from the same
 * service and the lines of the same trace or request.
 */
export function LogDetailSheet({
  projectId,
  eventId,
  at,
  onClose,
  onFilterTrace,
}: {
  projectId: string;
  eventId: string | null;
  at: string | null;
  onClose: () => void;
  onFilterTrace?: (traceId: string) => void;
}) {
  const ctx = useLogContext(projectId, eventId, at);
  const e = ctx.data?.event;
  return (
    <Sheet open={!!eventId} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            Log line {e && <LevelChip level={e.level} />}
            {e && <RedactedCount count={e.redactions} />}
          </SheetTitle>
          <SheetDescription>
            {e
              ? `${e.service} in ${e.environment}, ${formatDateTime(e.timestamp)}`
              : "Loading the line and its context"}
          </SheetDescription>
        </SheetHeader>
        <SheetBody className="space-y-5">
          {ctx.isPending ? (
            <div className="space-y-3">
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-40 w-full" />
            </div>
          ) : ctx.isError ? (
            <ErrorState
              compact
              error={ctx.error}
              title="Could not load this line"
              onRetry={() => void ctx.refetch()}
            />
          ) : e ? (
            <>
              <div
                className="relative rounded-lg bg-muted/60 p-3 pr-10 font-mono text-[12.5px] leading-relaxed break-words whitespace-pre-wrap"
                data-qa="log-message"
              >
                {e.message}
                <CopyButton
                  value={e.message}
                  iconOnly
                  label="Copy message"
                  variant="subtle"
                  className="absolute top-1.5 right-1.5"
                />
              </div>
              <div className="flex flex-wrap gap-2">
                {e.error_group_id && (
                  <Link
                    href={`/errors/${e.error_group_id}`}
                    className={buttonVariants({ size: "xs", variant: "outline" })}
                  >
                    <BugIcon />
                    Open error group
                  </Link>
                )}
                {e.error_group_id && (
                  <Link
                    href={`/errors/${e.error_group_id}?investigate=1`}
                    className={buttonVariants({ size: "xs", variant: "outline" })}
                  >
                    <SparklesIcon />
                    Investigate with AI
                  </Link>
                )}
                {e.trace_id && onFilterTrace && (
                  <button
                    type="button"
                    onClick={() => onFilterTrace(e.trace_id)}
                    className={buttonVariants({ size: "xs", variant: "outline" })}
                  >
                    <FilterIcon />
                    Show this trace
                  </button>
                )}
              </div>
              <KeyValues
                columns={2}
                items={[
                  { label: "Time", value: <Mono>{e.timestamp}</Mono> },
                  { label: "Received", value: <Mono>{e.received_at}</Mono> },
                  { label: "Service", value: e.service },
                  { label: "Environment", value: e.environment },
                  { label: "Host", value: e.host || "n/a", hidden: !e.host },
                  { label: "Source", value: e.source },
                  { label: "Trace id", value: <Mono>{e.trace_id}</Mono>, hidden: !e.trace_id },
                  { label: "Span id", value: <Mono>{e.span_id}</Mono>, hidden: !e.span_id },
                  {
                    label: "Request id",
                    value: <Mono>{e.request_id}</Mono>,
                    hidden: !e.request_id,
                  },
                  { label: "Exception", value: e.exception_type, hidden: !e.exception_type },
                  { label: "Event id", value: <Mono>{e.event_id}</Mono> },
                ]}
              />
              {e.stack_trace && (
                <div>
                  <h3 className="mb-1.5 text-[11px] font-semibold tracking-[0.04em] text-subtle uppercase">
                    Stack trace
                  </h3>
                  <pre className="code-block max-h-72">{e.stack_trace}</pre>
                </div>
              )}
              {Object.keys(e.attributes).length > 0 && (
                <div>
                  <h3 className="mb-1.5 text-[11px] font-semibold tracking-[0.04em] text-subtle uppercase">
                    Attributes
                  </h3>
                  <JsonView value={e.attributes} maxHeight={280} label="attributes" />
                </div>
              )}
              <ContextList title="Before, same service" lines={ctx.data.before} />
              <ContextList title="After, same service" lines={ctx.data.after} />
              <ContextList
                title={e.trace_id ? "Same trace" : "Same request"}
                lines={ctx.data.same_trace}
                current={e.event_id}
              />
              <a
                href={`/logs?q=${encodeURIComponent(e.message.slice(0, 40))}`}
                className="inline-flex items-center gap-1 text-[12.5px] text-primary hover:underline"
              >
                Search for similar lines
                <ExternalLinkIcon className="size-3.5" />
              </a>
            </>
          ) : null}
        </SheetBody>
      </SheetContent>
    </Sheet>
  );
}
