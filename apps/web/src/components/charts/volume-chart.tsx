"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { ChartLegend, ChartTooltipCard } from "@/components/charts/chart-tooltip";
import { useChartColors } from "@/hooks/use-chart-colors";
import type { HistogramBucket } from "@/lib/api/types";
import { formatNumber } from "@/lib/format";

const SERIES = [
  { key: "debug", label: "Debug", token: "level-debug" },
  { key: "info", label: "Info", token: "level-info" },
  { key: "warn", label: "Warn", token: "level-warn" },
  { key: "error", label: "Error", token: "level-error" },
  { key: "fatal", label: "Fatal", token: "level-fatal" },
] as const;

export interface VolumePoint {
  at: number;
  debug: number;
  info: number;
  warn: number;
  error: number;
  fatal: number;
}

/** Histogram buckets as chart points; trace lines are counted with debug. */
export function toVolumePoints(buckets: HistogramBucket[]): VolumePoint[] {
  return buckets.map((b) => ({
    at: new Date(b.at).getTime(),
    debug: (b.debug ?? 0) + (b.trace ?? 0),
    info: b.info ?? 0,
    warn: b.warn ?? 0,
    error: b.error ?? 0,
    fatal: b.fatal ?? 0,
  }));
}

/** Stacked line counts per time bucket, by level. */
export function VolumeChart({
  data,
  spanMs,
  height = 220,
  onPick,
}: {
  data: VolumePoint[];
  spanMs: number;
  height?: number;
  onPick?: (at: number) => void;
}) {
  const c = useChartColors();
  const fmt = new Intl.DateTimeFormat(
    "en-US",
    spanMs <= 2 * 24 * 3600_000
      ? { hour: "2-digit", minute: "2-digit", hour12: false }
      : { month: "short", day: "numeric" }
  );
  return (
    <div className="space-y-3">
      <ChartLegend items={SERIES.map((s) => ({ label: s.label, color: c[s.token] }))} />
      <div className="w-full" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={data}
            margin={{ top: 4, right: 4, left: -18, bottom: 0 }}
            onClick={(e) => {
              const label = (e as { activeLabel?: number | string } | null)?.activeLabel;
              if (onPick && label != null) onPick(Number(label));
            }}
          >
            <CartesianGrid vertical={false} stroke={c["chart-grid"]} />
            <XAxis
              dataKey="at"
              tickFormatter={(v: number) => fmt.format(new Date(v))}
              tick={{ fill: c["chart-axis"], fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              minTickGap={28}
            />
            <YAxis
              allowDecimals={false}
              tick={{ fill: c["chart-axis"], fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              width={48}
            />
            <Tooltip
              cursor={{ fill: c["chart-grid"], opacity: 0.5 }}
              content={({ active, payload, label }) =>
                active && payload?.length ? (
                  <ChartTooltipCard
                    title={new Date(Number(label)).toLocaleString("en-US", {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                      hour12: false,
                    })}
                    rows={[...SERIES].reverse().map((s) => ({
                      label: s.label,
                      value: formatNumber(
                        Number(payload.find((p) => p.dataKey === s.key)?.value ?? 0)
                      ),
                      color: c[s.token],
                    }))}
                  />
                ) : null
              }
            />
            {SERIES.map((s, i) => (
              <Bar
                key={s.key}
                dataKey={s.key}
                stackId="v"
                fill={c[s.token]}
                radius={i === SERIES.length - 1 ? [3, 3, 0, 0] : 0}
                maxBarSize={22}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
