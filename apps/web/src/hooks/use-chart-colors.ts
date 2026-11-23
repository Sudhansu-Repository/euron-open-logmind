"use client";

import { useTheme } from "next-themes";
import * as React from "react";

const TOKENS = [
  "chart-1",
  "chart-2",
  "chart-3",
  "chart-4",
  "chart-5",
  "chart-6",
  "chart-grid",
  "chart-axis",
  "level-trace",
  "level-debug",
  "level-info",
  "level-warn",
  "level-error",
  "level-fatal",
  "danger",
  "success",
  "warning",
  "info",
  "primary",
] as const;
export type ChartToken = (typeof TOKENS)[number];

/**
 * The chart tokens from globals.css as concrete colours. SVG presentation attributes
 * (stroke, fill) do not resolve CSS variables in every renderer, so recharts gets real
 * values; they are re-read whenever the theme changes, so both themes stay on the tokens.
 */
export function useChartColors(): Record<ChartToken, string> {
  const { resolvedTheme } = useTheme();
  const read = React.useCallback(() => {
    const out = {} as Record<ChartToken, string>;
    const style = typeof window === "undefined" ? null : getComputedStyle(document.documentElement);
    for (const t of TOKENS) out[t] = style?.getPropertyValue(`--${t}`).trim() || "currentColor";
    return out;
  }, []);
  const [colors, setColors] = React.useState<Record<ChartToken, string>>(read);
  React.useEffect(() => {
    const id = requestAnimationFrame(() => setColors(read()));
    return () => cancelAnimationFrame(id);
  }, [resolvedTheme, read]);
  return colors;
}
