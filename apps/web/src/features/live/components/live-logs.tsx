"use client";

import { PauseIcon, PlayIcon, RadioIcon, Trash2Icon } from "lucide-react";
import * as React from "react";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { useProjectScope } from "@/components/project-select";
import { NoProject } from "@/components/send-first-log";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Input } from "@/components/ui/input";
import { LogDetailSheet } from "@/features/logs/components/log-detail";
import { LogRow, type RowLine } from "@/features/logs/components/log-row";
import { useProjects } from "@/features/projects/api";
import { appFetch } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { cn } from "@/lib/cn";
import { formatNumber } from "@/lib/format";
import { LEVELS, levelColor } from "@/lib/labels";
import { appendLines, socketUrl, type LiveEvent, type LiveLine } from "@/lib/live-events";
import { useSocket } from "@/hooks/use-socket";

const STATUS_TEXT = {
  idle: "Not connected",
  connecting: "Connecting",
  open: "Streaming",
  closed: "Reconnecting",
  refused: "Disconnected",
} as const;

/**
 * Live Logs: lines appear the moment ingestion stores them, over a WebSocket. Filters
 * (level, service, keyword) are applied on the server, so a busy project does not flood
 * the browser. Pausing keeps the socket open and holds new lines back.
 */
export function LiveLogs() {
  const projects = useProjects();
  const [projectId] = useProjectScope();
  const [levels, setLevels] = React.useState<string[]>([]);
  const [service, setService] = React.useState("");
  const [q, setQ] = React.useState("");
  const [applied, setApplied] = React.useState({ service: "", q: "" });
  const [lines, setLines] = React.useState<LiveLine[]>([]);
  const [held, setHeld] = React.useState<LiveLine[]>([]);
  const [paused, setPaused] = React.useState(false);
  const [received, setReceived] = React.useState(0);
  const [fresh, setFresh] = React.useState<Set<string>>(new Set());
  const [open, setOpen] = React.useState<RowLine | null>(null);
  const pausedRef = React.useRef(paused);
  pausedRef.current = paused;

  const resolveUrl = React.useMemo(() => {
    if (!projectId) return null;
    return async () => {
      try {
        const { token } = await appFetch<{ token: string }>("/api/session/ws-token");
        return socketUrl(window.location, token, {
          projectId,
          levels,
          services: applied.service ? [applied.service] : [],
          q: applied.q,
        });
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) return null;
        throw err;
      }
    };
  }, [projectId, levels, applied]);

  const onEvent = React.useCallback((event: LiveEvent) => {
    if (event.type !== "logs") return;
    setReceived((n) => n + event.items.length);
    if (pausedRef.current) {
      setHeld((h) => appendLines(h, event.items));
      return;
    }
    setLines((prev) => appendLines(prev, event.items));
    setFresh(new Set(event.items.map((l) => l.event_id)));
  }, []);

  const { status } = useSocket(resolveUrl, onEvent);

  React.useEffect(() => {
    setLines([]);
    setHeld([]);
    setReceived(0);
  }, [projectId]);

  function resume() {
    setLines((prev) => appendLines(prev, held));
    setHeld([]);
    setPaused(false);
  }

  if (projects.isSuccess && projects.data.length === 0) {
    return (
      <>
        <PageHeader title="Live logs" description="Lines as they arrive." />
        <Surface>
          <NoProject />
        </Surface>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Live logs"
        description="Lines appear here the moment they are stored, already redacted. Filter on the server by level, service or keyword."
      />
      <Surface className="mb-4 p-4">
        <form
          className="flex flex-col gap-3 lg:flex-row lg:items-center"
          onSubmit={(e) => {
            e.preventDefault();
            setApplied({ service: service.trim(), q: q.trim().toLowerCase() });
          }}
        >
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Levels">
            {LEVELS.map((l) => {
              const on = levels.includes(l);
              return (
                <button
                  key={l}
                  type="button"
                  aria-pressed={on}
                  onClick={() =>
                    setLevels((cur) => (on ? cur.filter((x) => x !== l) : [...cur, l]))
                  }
                  className={cn(
                    "inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[12.5px] font-medium text-muted-foreground hover:bg-muted",
                    on && "bg-primary-soft text-foreground hover:bg-primary-soft"
                  )}
                >
                  <span
                    aria-hidden
                    className="size-2 rounded-full"
                    style={{ background: levelColor(l) }}
                  />
                  {l}
                </button>
              );
            })}
          </div>
          <Input
            aria-label="Service"
            value={service}
            onChange={(e) => setService(e.target.value)}
            placeholder="Service, e.g. checkout"
            className="lg:w-48"
          />
          <Input
            aria-label="Keyword"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Keyword"
            className="lg:flex-1"
          />
          <Button type="submit" variant="secondary">
            Apply
          </Button>
        </form>
      </Surface>
      <Surface>
        <SurfaceHeader
          title={
            <span className="flex items-center gap-2">
              <span
                aria-hidden
                className={cn(
                  "size-2 rounded-full",
                  status === "open"
                    ? "animate-pulse bg-success"
                    : status === "refused"
                      ? "bg-danger"
                      : "bg-warning"
                )}
              />
              {STATUS_TEXT[status]}
            </span>
          }
          description={`${formatNumber(received)} lines received this session${held.length ? `, ${formatNumber(held.length)} held while paused` : ""}`}
          action={
            <>
              {paused ? (
                <Button size="xs" onClick={resume}>
                  <PlayIcon />
                  Resume{held.length ? ` (${held.length})` : ""}
                </Button>
              ) : (
                <Button size="xs" variant="outline" onClick={() => setPaused(true)}>
                  <PauseIcon />
                  Pause
                </Button>
              )}
              <Button
                size="xs"
                variant="ghost"
                onClick={() => setLines([])}
                disabled={!lines.length}
              >
                <Trash2Icon />
                Clear
              </Button>
            </>
          }
        />
        {lines.length === 0 ? (
          <EmptyState
            compact
            icon={RadioIcon}
            title={
              status === "open" ? "Waiting for the next line" : "Connecting to the live stream"
            }
            description={
              status === "refused"
                ? "The live stream refused this session. Sign in again, or pick a project you belong to."
                : "Send a line with an SDK, an OpenTelemetry exporter or curl and it shows up here within a second. Older lines are in the Log explorer."
            }
          />
        ) : (
          <ul className="pb-2" data-qa="live-list">
            {lines.map((l) => (
              <LogRow key={l.event_id} line={l} fresh={fresh.has(l.event_id)} onOpen={setOpen} />
            ))}
          </ul>
        )}
      </Surface>
      {applied.service || applied.q ? (
        <p className="mt-3 text-[12px] text-muted-foreground">
          Filtering on the server: {applied.service && <Chip>service {applied.service}</Chip>}{" "}
          {applied.q && <Chip>keyword {applied.q}</Chip>}
        </p>
      ) : null}
      <LogDetailSheet
        projectId={projectId}
        eventId={open?.event_id ?? null}
        at={open?.timestamp ?? null}
        onClose={() => setOpen(null)}
      />
    </>
  );
}
