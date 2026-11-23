"use client";

import { BugIcon } from "lucide-react";

import { LevelChip, RedactedCount } from "@/components/badges";
import { cn } from "@/lib/cn";
import { formatTime } from "@/lib/format";
import { levelColor } from "@/lib/labels";

export interface RowLine {
  event_id: string;
  timestamp: string;
  level: string;
  service: string;
  environment: string;
  message: string;
  redactions?: number;
  error_group_id?: string | null;
  fingerprint?: string;
}

/** One log line: time, level, service, message. A coloured edge marks the level. */
export function LogRow({
  line,
  onOpen,
  selected = false,
  fresh = false,
}: {
  line: RowLine;
  onOpen?: (line: RowLine) => void;
  selected?: boolean;
  fresh?: boolean;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={() => onOpen?.(line)}
        data-qa="log-row"
        className={cn(
          "group relative flex w-full items-start gap-3 px-5 py-1.5 text-left font-mono text-[12.5px] leading-5 hover:bg-muted/60 focus-visible:bg-muted focus-visible:outline-none",
          selected && "bg-primary-soft hover:bg-primary-soft",
          fresh && "animate-[flash_1.2s_ease-out]"
        )}
      >
        <span
          aria-hidden
          className="absolute inset-y-1 left-1.5 w-[3px] rounded-full"
          style={{ background: levelColor(line.level) }}
        />
        <time dateTime={line.timestamp} className="w-[74px] shrink-0 text-subtle tabular">
          {formatTime(line.timestamp)}
        </time>
        <span className="hidden w-14 shrink-0 sm:block">
          <LevelChip level={line.level} />
        </span>
        <span
          className="hidden w-32 shrink-0 truncate text-muted-foreground md:block"
          title={line.service}
        >
          {line.service}
        </span>
        <span className="min-w-0 flex-1 break-words text-foreground">
          {line.message}
          {(line.redactions ?? 0) > 0 && (
            <span className="ml-2 inline-flex align-middle font-sans">
              <RedactedCount count={line.redactions ?? 0} />
            </span>
          )}
        </span>
        {line.error_group_id && (
          <BugIcon
            className="mt-0.5 size-3.5 shrink-0 text-danger"
            aria-label="Part of an error group"
          />
        )}
      </button>
    </li>
  );
}
