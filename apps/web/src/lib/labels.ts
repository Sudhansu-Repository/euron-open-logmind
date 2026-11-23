import type { Spec } from "./tones";

/** Log levels as the API stores them (ingestion/normalize.py LEVELS). */
export const LEVELS = ["trace", "debug", "info", "warn", "error", "fatal"] as const;
export type Level = (typeof LEVELS)[number];

const LEVEL: Record<Level, Spec> = {
  trace: { label: "Trace", tone: "neutral", hint: "Very detailed diagnostic output." },
  debug: { label: "Debug", tone: "neutral", hint: "Diagnostic output for developers." },
  info: { label: "Info", tone: "info", hint: "Normal operation." },
  warn: {
    label: "Warn",
    tone: "warning",
    hint: "Something unexpected that did not fail the request.",
  },
  error: {
    label: "Error",
    tone: "danger",
    hint: "A failure. Lines like this are grouped on the Errors page.",
  },
  fatal: {
    label: "Fatal",
    tone: "fuchsia",
    hint: "A failure that stopped the process or the request entirely.",
  },
};

export function levelSpec(level: string | null | undefined): Spec {
  return LEVEL[level as Level] ?? { label: level || "Unknown", tone: "neutral" };
}

/** The CSS variable that colours a level in charts and the log list. */
export function levelColor(level: string): string {
  return `var(--level-${(LEVELS as readonly string[]).includes(level) ? level : "info"})`;
}

const GROUP_STATUS: Record<string, Spec> = {
  open: { label: "Open", tone: "danger", hint: "Still happening, or not looked at yet." },
  resolved: {
    label: "Resolved",
    tone: "success",
    hint: "Marked fixed. A new occurrence reopens it as a regression.",
  },
  ignored: {
    label: "Ignored",
    tone: "neutral",
    hint: "Known and accepted; hidden from the open list.",
  },
};

export function groupStatusSpec(status: string | null | undefined): Spec {
  return GROUP_STATUS[status ?? ""] ?? { label: status || "Unknown", tone: "neutral" };
}

const INVESTIGATION: Record<string, Spec> = {
  queued: { label: "Queued", tone: "neutral", hint: "Waiting for the worker." },
  running: {
    label: "Investigating",
    tone: "info",
    hint: "Collecting evidence and asking the model.",
  },
  completed: { label: "Completed", tone: "success", hint: "The report is ready." },
  failed: {
    label: "Failed",
    tone: "danger",
    hint: "The provider or the evidence step failed; the error says why.",
  },
};

export function investigationStatusSpec(status: string | null | undefined): Spec {
  return INVESTIGATION[status ?? ""] ?? { label: status || "Unknown", tone: "neutral" };
}

const SERVICE: Record<string, Spec> = {
  healthy: { label: "Healthy", tone: "success", hint: "Under 2% errors in the last 15 minutes." },
  degraded: {
    label: "Degraded",
    tone: "warning",
    hint: "2% or more errors in the last 15 minutes.",
  },
  critical: {
    label: "Critical",
    tone: "danger",
    hint: "10% or more errors in the last 15 minutes.",
  },
  silent: {
    label: "Silent",
    tone: "neutral",
    hint: "Sent logs earlier in the window but nothing in the last 15 minutes.",
  },
};

export function serviceStatusSpec(status: string | null | undefined): Spec {
  return SERVICE[status ?? ""] ?? { label: status || "Unknown", tone: "neutral" };
}

/** Why an evidence item is in the pack (investigations/evidence.py). */
const EVIDENCE: Record<string, Spec> = {
  first_occurrence: {
    label: "First failure",
    tone: "danger",
    hint: "The first occurrence of the current burst of this error.",
  },
  occurrence: { label: "Latest failure", tone: "danger", hint: "The most recent occurrence." },
  preceding: {
    label: "Earlier signal",
    tone: "warning",
    hint: "A warning or error from any service shortly before the first failure.",
  },
  correlated: {
    label: "Correlated",
    tone: "orange",
    hint: "An error in another service during the incident.",
  },
  change: {
    label: "Change",
    tone: "primary",
    hint: "A deploy, release, config change, migration or restart.",
  },
  trace: {
    label: "Same request",
    tone: "cyan",
    hint: "A line from the same trace or request as the first failure.",
  },
};

export function evidenceSpec(kind: string | null | undefined): Spec {
  return EVIDENCE[kind ?? ""] ?? { label: kind || "Evidence", tone: "neutral" };
}

export const ALERT_METRICS = ["error_count", "error_rate", "log_count", "matching_count"] as const;
export type AlertMetric = (typeof ALERT_METRICS)[number];

export const ALERT_METRIC: Record<AlertMetric, { label: string; unit: string; hint: string }> = {
  error_count: {
    label: "Error count",
    unit: "errors",
    hint: "Error and fatal lines in the window.",
  },
  error_rate: {
    label: "Error rate",
    unit: "percent",
    hint: "Error and fatal lines as a percentage of all lines in the window.",
  },
  log_count: {
    label: "Line count",
    unit: "lines",
    hint: "Every line in the window, for volume drops or floods.",
  },
  matching_count: {
    label: "Matching lines",
    unit: "lines",
    hint: "Lines containing all the keywords you enter.",
  },
};

const ALERT_STATE: Record<string, Spec> = {
  ok: { label: "OK", tone: "success", hint: "The condition is not met." },
  firing: { label: "Firing", tone: "danger", hint: "The condition is met; targets were notified." },
};

export function alertStateSpec(state: string | null | undefined, enabled = true): Spec {
  if (!enabled) return { label: "Off", tone: "neutral", hint: "Disabled: not evaluated." };
  return ALERT_STATE[state ?? ""] ?? { label: state || "Unknown", tone: "neutral" };
}

const ALERT_EVENT: Record<string, Spec> = {
  fired: { label: "Fired", tone: "danger" },
  resolved: { label: "Resolved", tone: "success" },
  test: { label: "Test", tone: "neutral" },
};

export function alertEventSpec(event: string | null | undefined): Spec {
  return ALERT_EVENT[event ?? ""] ?? { label: event || "Event", tone: "neutral" };
}

export const PROVIDER_KINDS = [
  "openai",
  "anthropic",
  "gemini",
  "ollama",
  "openai_compatible",
  "mock",
] as const;
export type ProviderKind = (typeof PROVIDER_KINDS)[number];

export const PROVIDER_KIND: Record<
  ProviderKind,
  { label: string; needsKey: boolean; needsUrl: boolean; model: string }
> = {
  openai: { label: "OpenAI", needsKey: true, needsUrl: false, model: "gpt-4.1-mini" },
  anthropic: { label: "Anthropic", needsKey: true, needsUrl: false, model: "claude-sonnet-4-5" },
  gemini: { label: "Google Gemini", needsKey: true, needsUrl: false, model: "gemini-2.5-flash" },
  ollama: { label: "Ollama (local)", needsKey: false, needsUrl: true, model: "llama3.1:8b" },
  openai_compatible: { label: "OpenAI-compatible", needsKey: false, needsUrl: true, model: "" },
  mock: {
    label: "Built-in mock (no key)",
    needsKey: false,
    needsUrl: false,
    model: "logmind-mock",
  },
};

export const REDACTION_CATEGORIES = [
  "credential",
  "email",
  "payment_card",
  "government_id",
  "phone",
  "bank_account",
  "ip_address",
] as const;
export type RedactionCategory = (typeof REDACTION_CATEGORIES)[number];

export const REDACTION_CATEGORY: Record<RedactionCategory, { label: string; hint: string }> = {
  credential: {
    label: "Credentials",
    hint: "API keys, tokens, JWTs, private keys, passwords in key=value form or URLs.",
  },
  email: { label: "Email addresses", hint: "Anything shaped like name@domain.tld." },
  payment_card: {
    label: "Card numbers",
    hint: "13 to 19 digits that pass the Luhn checksum (order ids that fail it stay).",
  },
  government_id: {
    label: "Government ids",
    hint: "US social security numbers and Aadhaar numbers (Verhoeff checksum).",
  },
  phone: {
    label: "Phone numbers",
    hint: "Numbers written with an international prefix or a bracketed area code.",
  },
  bank_account: {
    label: "IBANs",
    hint: "International bank account numbers that pass the mod 97 check.",
  },
  ip_address: {
    label: "IP addresses",
    hint: "IPv4 addresses. Off by default: usually wanted in logs.",
  },
};
