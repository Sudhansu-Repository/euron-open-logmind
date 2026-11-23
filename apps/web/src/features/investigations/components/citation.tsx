"use client";

import { cn } from "@/lib/cn";

/** A citation chip: the evidence id, which highlights and scrolls to that evidence item. */
export function CitationChips({
  refs,
  onPick,
  className,
}: {
  refs: string[];
  onPick: (ref: string) => void;
  className?: string;
}) {
  if (!refs.length) return null;
  return (
    <span className={cn("inline-flex flex-wrap gap-1 align-middle", className)}>
      {refs.map((r) => (
        <button
          key={r}
          type="button"
          onClick={() => onPick(r)}
          data-qa="citation"
          className="inline-flex h-5 items-center rounded-md bg-primary-soft px-1.5 font-mono text-[11px] font-semibold text-primary hover:brightness-95 focus-visible:outline-2 focus-visible:outline-ring dark:hover:brightness-125"
          aria-label={`Show evidence ${r}`}
        >
          {r}
        </button>
      ))}
    </span>
  );
}
