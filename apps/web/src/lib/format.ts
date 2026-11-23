/**
 * Number, token, cost, duration and date formatting used everywhere a figure is shown.
 * Every function is total: a missing or non-finite value renders as "n/a", never throws.
 */

const intFmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

function trim(n: number): string {
  const fixed = n >= 100 ? n.toFixed(0) : n.toFixed(1);
  return fixed.replace(/\.0$/, "");
}

/** 14,923. */
export function formatNumber(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "n/a";
  return intFmt.format(value);
}

/** 812 B, 4.2 KB, 12 MB. */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes)) return "n/a";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${trim(bytes / 1024)} KB`;
  return `${trim(bytes / (1024 * 1024))} MB`;
}

/** Token counts: 812, 4.2k, 1.3M. Exact below a thousand. */
export function formatTokenCount(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "n/a";
  const n = Math.round(value);
  const abs = Math.abs(n);
  if (abs < 1000) return intFmt.format(n);
  if (abs < 1_000_000) return `${trim(n / 1000)}k`;
  if (abs < 1_000_000_000) return `${trim(n / 1_000_000)}M`;
  return `${trim(n / 1_000_000_000)}B`;
}

const usd2 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const usd4 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});
const usd6 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 6,
});

/**
 * US dollars with as many decimals as the amount needs: $12.40, $0.0123, $0.000042.
 * Model calls often cost fractions of a cent, so two decimals would read as $0.00.
 */
export function formatCurrency(usd: number | null | undefined): string {
  if (usd == null || !Number.isFinite(usd)) return "n/a";
  const abs = Math.abs(usd);
  if (abs === 0 || abs >= 1) return usd2.format(usd);
  if (abs >= 0.0001) return usd4.format(usd);
  return usd6.format(usd);
}

/** The word shown instead of a price when a model has no entry in the pricing table. */
export const UNPRICED_LABEL = "Unpriced";

/**
 * A cost that may come from unpriced model calls (AC3: unpriced is flagged, never silently
 * free). A fully unpriced amount reads "Unpriced", never "$0.00"; a partly unpriced one
 * keeps the priced part and says the rest is missing.
 */
export function formatCost(
  usd: number | null | undefined,
  opts: { unpriced?: boolean; partial?: boolean } = {}
): string {
  if (opts.unpriced && (usd == null || usd === 0)) return UNPRICED_LABEL;
  const base = formatCurrency(usd);
  if (opts.unpriced || opts.partial) return `${base} + unpriced`;
  return base;
}

const dateTimeFmt = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});
const timeFmt = new Intl.DateTimeFormat("en-US", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});
const dateFmt = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
});

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "n/a";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "n/a" : dateTimeFmt.format(d);
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "n/a";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "n/a" : timeFmt.format(d);
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "n/a";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "n/a" : dateFmt.format(d);
}

/** "just now", "5m ago", "3h ago", "2d ago", then a date. */
export function formatRelative(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "Never";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "n/a";
  const diff = Math.round((now.getTime() - d.getTime()) / 1000);
  const future = diff < 0;
  const s = Math.abs(diff);
  const wrap = (v: string) => (future ? `in ${v}` : `${v} ago`);
  // A few seconds "in the future" is clock skew between the server and this browser.
  if (s < 45 || (future && s < 120)) return "just now";
  if (s < 3600) return wrap(`${Math.max(1, Math.round(s / 60))}m`);
  if (s < 86_400) return wrap(`${Math.round(s / 3600)}h`);
  if (s < 86_400 * 14) return wrap(`${Math.round(s / 86_400)}d`);
  return formatDate(iso);
}

/** Initials for an avatar: "Avery Chen" becomes "AC". */
export function initials(name: string | null | undefined): string {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const first = parts[0]?.[0] ?? "";
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? "") : "";
  return (first + last).toUpperCase() || "?";
}

/** A span in seconds as "45s", "4m", "1h 20m", "2d 3h". */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "n/a";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) {
    const rest = m % 60;
    return rest ? `${h}h ${rest}m` : `${h}h`;
  }
  const d = Math.floor(h / 24);
  const restH = h % 24;
  return restH ? `${d}d ${restH}h` : `${d}d`;
}

/** Milliseconds as "0.4 ms", "320 ms", "1.4 s" or "2m 5s". */
export function formatMs(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return "n/a";
  if (ms < 0) return "n/a";
  if (ms < 1) return `${ms.toFixed(1)} ms`;
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${trim(ms / 1000)} s`;
  const totalS = Math.round(ms / 1000);
  const m = Math.floor(totalS / 60);
  const s = totalS % 60;
  return s ? `${m}m ${s}s` : `${m}m`;
}

/** 0.0423 as "4.2%". */
export function formatPercent(ratio: number | null | undefined): string {
  if (ratio == null || !Number.isFinite(ratio)) return "n/a";
  const pct = ratio * 100;
  if (pct === 0) return "0%";
  if (Math.abs(pct) < 0.1) return "<0.1%";
  return `${pct >= 10 ? pct.toFixed(0) : pct.toFixed(1).replace(/\.0$/, "")}%`;
}

/** "1 span", "3 spans". */
export function plural(n: number, word: string, many = `${word}s`): string {
  return `${intFmt.format(n)} ${n === 1 ? word : many}`;
}

/** "a1b2c3d4...9f0e" for long identifiers. */
export function shortId(value: string | null | undefined, head = 8, tail = 4): string {
  if (!value) return "";
  return value.length <= head + tail + 3
    ? value
    : `${value.slice(0, head)}...${value.slice(-tail)}`;
}
