"use client";

import { cn } from "@/lib/cn";

/** A tiny bar sparkline drawn as plain SVG (no axes), for table rows. */
export function Sparkline({
  values,
  className,
  tone = "danger",
  label,
}: {
  values: number[];
  className?: string;
  tone?: "danger" | "primary" | "warning";
  label: string;
}) {
  const max = Math.max(1, ...values);
  const w = 96;
  const h = 24;
  const step = values.length ? w / values.length : w;
  const fill = { danger: "fill-danger/70", primary: "fill-primary/70", warning: "fill-warning/70" }[
    tone
  ];
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      role="img"
      aria-label={label}
      className={cn("h-6 w-24", className)}
    >
      {values.map((v, i) => {
        const bh = v === 0 ? 1 : Math.max(2, (v / max) * h);
        return (
          <rect
            key={i}
            x={i * step + 0.5}
            y={h - bh}
            width={Math.max(1, step - 1)}
            height={bh}
            rx={1}
            className={v === 0 ? "fill-muted" : fill}
          />
        );
      })}
    </svg>
  );
}

/** Hourly points over the last `hours` hours, zero filled, oldest first. */
export function hourlySeries(
  points: { hour: string; count: number }[],
  hours = 24,
  now = Date.now()
): number[] {
  const end = Math.floor(now / 3_600_000) * 3_600_000;
  const byHour = new Map(
    points.map((p) => [Math.floor(new Date(p.hour).getTime() / 3_600_000) * 3_600_000, p.count])
  );
  return Array.from(
    { length: hours },
    (_, i) => byHour.get(end - (hours - 1 - i) * 3_600_000) ?? 0
  );
}
