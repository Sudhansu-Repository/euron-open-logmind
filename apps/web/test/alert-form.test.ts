import { describe, expect, it } from "vitest";

import {
  describeRule,
  draftFromRule,
  EMPTY_DRAFT,
  parseEmails,
  toCreate,
  toUpdate,
  validateDraft,
} from "@/features/alerts/form";
import type { AlertRule } from "@/lib/api/types";

const rule: AlertRule = {
  id: "r1",
  project_id: "p1",
  name: "Checkout errors",
  kind: "threshold",
  metric: "error_count",
  query: "",
  service: "checkout",
  environment: "",
  threshold: 20,
  window_minutes: 10,
  sensitivity: 3,
  min_count: 10,
  baseline_hours: 24,
  email_to: ["oncall@example.com"],
  has_webhook: true,
  has_slack: false,
  cooldown_minutes: 30,
  enabled: true,
  state: "ok",
  last_value: null,
  last_evaluated_at: null,
  last_fired_at: null,
  created_at: "2026-01-01T00:00:00Z",
};

describe("alert form", () => {
  it("validates names, targets, numbers and URLs", () => {
    expect(validateDraft(EMPTY_DRAFT, true)).toMatch(/name/);
    const named = { ...EMPTY_DRAFT, name: "x" };
    expect(validateDraft(named, true)).toMatch(/at least one target/);
    expect(validateDraft({ ...named, emails: "nope" }, true)).toMatch(/not an email/);
    expect(validateDraft({ ...named, emails: "a@b.co", webhookUrl: "ftp://x" }, true)).toMatch(
      /http/
    );
    expect(validateDraft({ ...named, emails: "a@b.co", threshold: "-1" }, true)).toMatch(
      /threshold/
    );
    expect(validateDraft({ ...named, emails: "a@b.co", window: "0" }, true)).toMatch(/window/);
    expect(validateDraft({ ...named, emails: "a@b.co", metric: "matching_count" }, true)).toMatch(
      /keywords/
    );
    expect(
      validateDraft({ ...named, emails: "a@b.co", kind: "anomaly", sensitivity: "1" }, true)
    ).toMatch(/Sensitivity/);
    expect(
      validateDraft({ ...named, emails: "a@b.co", kind: "anomaly", minCount: "0" }, true)
    ).toMatch(/minimum/);
    expect(
      validateDraft({ ...named, emails: "a@b.co", kind: "anomaly", baselineHours: "999" }, true)
    ).toMatch(/baseline/);
    expect(validateDraft({ ...named, emails: "a@b.co", cooldown: "0" }, true)).toMatch(/cooldown/);
    expect(validateDraft({ ...named, slackUrl: "https://hooks.slack.com/x" }, true)).toBeNull();
    expect(validateDraft(named, false)).toBeNull();
  });

  it("builds create and update bodies", () => {
    const body = toCreate(
      {
        ...EMPTY_DRAFT,
        name: " Spike ",
        kind: "anomaly",
        emails: "a@b.co, c@d.co",
        webhookUrl: "",
      },
      "p1"
    );
    expect(body).toMatchObject({
      project_id: "p1",
      name: "Spike",
      kind: "anomaly",
      threshold: 0,
      email_to: ["a@b.co", "c@d.co"],
      webhook_url: null,
    });
    const d = draftFromRule(rule);
    expect(toUpdate(d, rule)).toEqual({});
    expect(toUpdate({ ...d, threshold: "50", emails: "", slackUrl: "https://s" }, rule)).toEqual({
      threshold: 50,
      email_to: [],
      slack_url: "https://s",
    });
    expect(
      toUpdate(
        { ...draftFromRule({ ...rule, kind: "anomaly" }), sensitivity: "4" },
        { ...rule, kind: "anomaly" }
      )
    ).toEqual({ sensitivity: 4 });
    expect(parseEmails(" a@b.co ,, c@d.co ")).toEqual(["a@b.co", "c@d.co"]);
  });

  it("describes rules in words", () => {
    expect(describeRule(rule)).toBe("More than 20 errors in 10 min, checkout");
    expect(describeRule({ ...rule, metric: "error_rate", threshold: 5, service: "" })).toBe(
      "More than 5% errors in 10 min, all services"
    );
    expect(describeRule({ ...rule, kind: "anomaly", environment: "production" })).toMatch(
      /3 standard deviations above the 24 h baseline/
    );
  });
});
