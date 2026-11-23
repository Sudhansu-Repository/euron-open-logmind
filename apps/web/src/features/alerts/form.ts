/**
 * The alert rule form: a string draft, its validation and its conversion to API bodies.
 * Pure, unit tested.
 */
import type { AlertIn, AlertRule, AlertUpdate } from "@/lib/api/types";
import type { AlertMetric } from "@/lib/labels";

export interface AlertDraft {
  name: string;
  kind: "threshold" | "anomaly";
  metric: AlertMetric;
  query: string;
  service: string;
  environment: string;
  threshold: string;
  window: string;
  sensitivity: string;
  minCount: string;
  baselineHours: string;
  emails: string;
  webhookUrl: string;
  slackUrl: string;
  cooldown: string;
}

export const EMPTY_DRAFT: AlertDraft = {
  name: "",
  kind: "threshold",
  metric: "error_count",
  query: "",
  service: "",
  environment: "",
  threshold: "10",
  window: "5",
  sensitivity: "3",
  minCount: "10",
  baselineHours: "24",
  emails: "",
  webhookUrl: "",
  slackUrl: "",
  cooldown: "30",
};

export function draftFromRule(r: AlertRule): AlertDraft {
  return {
    name: r.name,
    kind: r.kind === "anomaly" ? "anomaly" : "threshold",
    metric: r.metric as AlertMetric,
    query: r.query,
    service: r.service,
    environment: r.environment,
    threshold: String(r.threshold),
    window: String(r.window_minutes),
    sensitivity: String(r.sensitivity),
    minCount: String(r.min_count),
    baselineHours: String(r.baseline_hours),
    emails: r.email_to.join(", "),
    webhookUrl: "",
    slackUrl: "",
    cooldown: String(r.cooldown_minutes),
  };
}

export function parseEmails(raw: string): string[] {
  return raw
    .split(/[,\s]+/)
    .map((e) => e.trim())
    .filter(Boolean);
}

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

function num(v: string): number {
  return v.trim() === "" ? Number.NaN : Number(v);
}

/** The first problem with a draft, or null. `creating` requires a notification target. */
export function validateDraft(d: AlertDraft, creating: boolean): string | null {
  if (!d.name.trim()) return "Give the rule a name.";
  const emails = parseEmails(d.emails);
  const bad = emails.find((e) => !EMAIL.test(e));
  if (bad) return `${bad} is not an email address.`;
  for (const [label, url] of [
    ["The webhook URL", d.webhookUrl],
    ["The Slack URL", d.slackUrl],
  ] as const) {
    if (url && !/^https?:\/\//.test(url.trim()))
      return `${label} must start with http:// or https://.`;
  }
  if (creating && !emails.length && !d.webhookUrl.trim() && !d.slackUrl.trim())
    return "Add at least one target: an email, a webhook or Slack.";
  if (d.kind === "threshold") {
    const t = num(d.threshold);
    if (!Number.isFinite(t) || t < 0) return "The threshold must be a number, 0 or more.";
    const w = num(d.window);
    if (!Number.isInteger(w) || w < 1 || w > 1440)
      return "The window is a whole number of minutes, 1 to 1440.";
    if (d.metric === "matching_count" && !d.query.trim()) return "Enter the keywords to match.";
  } else {
    const s = num(d.sensitivity);
    if (!Number.isFinite(s) || s < 1.5 || s > 20)
      return "Sensitivity is between 1.5 and 20 standard deviations.";
    const m = num(d.minCount);
    if (!Number.isInteger(m) || m < 1) return "The minimum is a whole number of errors, 1 or more.";
    const b = num(d.baselineHours);
    if (!Number.isInteger(b) || b < 1 || b > 336) return "The baseline is 1 to 336 hours.";
  }
  const c = num(d.cooldown);
  if (!Number.isInteger(c) || c < 1 || c > 1440) return "The cooldown is 1 to 1440 minutes.";
  return null;
}

export function toCreate(d: AlertDraft, projectId: string): AlertIn {
  return {
    project_id: projectId,
    name: d.name.trim(),
    kind: d.kind,
    metric: d.metric,
    query: d.query.trim(),
    service: d.service.trim(),
    environment: d.environment.trim(),
    threshold: d.kind === "threshold" ? Number(d.threshold) : 0,
    window_minutes: d.kind === "threshold" ? Number(d.window) : 5,
    sensitivity: Number(d.sensitivity),
    min_count: Number(d.minCount),
    baseline_hours: Number(d.baselineHours),
    email_to: parseEmails(d.emails),
    webhook_url: d.webhookUrl.trim() || null,
    slack_url: d.slackUrl.trim() || null,
    cooldown_minutes: Number(d.cooldown),
    enabled: true,
  };
}

/** Only what changed; empty URL fields keep the stored URL. */
export function toUpdate(d: AlertDraft, r: AlertRule): AlertUpdate {
  const out: AlertUpdate = {};
  if (d.name.trim() !== r.name) out.name = d.name.trim();
  if (d.query.trim() !== r.query) out.query = d.query.trim();
  if (d.service.trim() !== r.service) out.service = d.service.trim();
  if (d.environment.trim() !== r.environment) out.environment = d.environment.trim();
  if (r.kind === "threshold") {
    if (Number(d.threshold) !== r.threshold) out.threshold = Number(d.threshold);
    if (Number(d.window) !== r.window_minutes) out.window_minutes = Number(d.window);
  } else {
    if (Number(d.sensitivity) !== r.sensitivity) out.sensitivity = Number(d.sensitivity);
    if (Number(d.minCount) !== r.min_count) out.min_count = Number(d.minCount);
    if (Number(d.baselineHours) !== r.baseline_hours) out.baseline_hours = Number(d.baselineHours);
  }
  const emails = parseEmails(d.emails);
  if (emails.join(",") !== r.email_to.join(",")) out.email_to = emails;
  if (d.webhookUrl.trim()) out.webhook_url = d.webhookUrl.trim();
  if (d.slackUrl.trim()) out.slack_url = d.slackUrl.trim();
  if (Number(d.cooldown) !== r.cooldown_minutes) out.cooldown_minutes = Number(d.cooldown);
  return out;
}

/** One line describing what a rule watches. */
export function describeRule(
  r: Pick<
    AlertRule,
    | "kind"
    | "metric"
    | "threshold"
    | "window_minutes"
    | "service"
    | "environment"
    | "query"
    | "sensitivity"
    | "min_count"
    | "baseline_hours"
  >
): string {
  const scope = [r.service || "all services", r.environment].filter(Boolean).join(" in ");
  if (r.kind === "anomaly")
    return `Errors in ${scope} ${r.sensitivity} standard deviations above the ${r.baseline_hours} h baseline (at least ${r.min_count} in 5 min)`;
  const what =
    {
      error_count: "errors",
      error_rate: "% errors",
      log_count: "lines",
      matching_count: `lines matching "${r.query}"`,
    }[r.metric] ?? r.metric;
  return `More than ${r.threshold}${r.metric === "error_rate" ? "" : " "}${what} in ${r.window_minutes} min, ${scope}`;
}
