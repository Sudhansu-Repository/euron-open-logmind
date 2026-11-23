"use client";

import * as React from "react";
import { toast } from "sonner";

import { Segmented } from "@/components/segmented";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Field, FieldError } from "@/components/ui/label";
import { SimpleSelect } from "@/components/ui/select";
import type { AlertRule } from "@/lib/api/types";
import { errorMessage } from "@/lib/api/errors";
import { ALERT_METRIC, ALERT_METRICS, type AlertMetric } from "@/lib/labels";

import { useCreateAlertRule, useUpdateAlertRule } from "../api";
import {
  draftFromRule,
  EMPTY_DRAFT,
  toCreate,
  toUpdate,
  validateDraft,
  type AlertDraft,
} from "../form";

/** Create (rule = null) or edit an alert rule. */
export function AlertDialog({
  open,
  rule,
  projectId,
  onClose,
  onCreated,
}: {
  open: boolean;
  rule: AlertRule | null;
  projectId: string;
  onClose: () => void;
  onCreated?: (secret: string | null) => void;
}) {
  const create = useCreateAlertRule();
  const update = useUpdateAlertRule();
  const [d, setD] = React.useState<AlertDraft>(EMPTY_DRAFT);
  const [error, setError] = React.useState<string | null>(null);
  const busy = create.isPending || update.isPending;
  React.useEffect(() => {
    if (open) {
      setD(rule ? draftFromRule(rule) : EMPTY_DRAFT);
      setError(null);
    }
  }, [open, rule]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const problem = validateDraft(d, !rule);
    if (problem) return setError(problem);
    setError(null);
    if (rule) {
      update.mutate(
        { id: rule.id, body: toUpdate(d, rule) },
        {
          onSuccess: () => {
            toast.success("Alert rule saved.");
            onClose();
          },
          onError: (err) => setError(errorMessage(err)),
        }
      );
    } else {
      create.mutate(toCreate(d, projectId), {
        onSuccess: (created) => {
          toast.success(`Alert ${created.name} created.`);
          onClose();
          onCreated?.(created.webhook_secret ?? null);
        },
        onError: (err) => setError(errorMessage(err)),
      });
    }
  }

  const metric = ALERT_METRIC[d.metric];
  return (
    <Dialog open={open} onOpenChange={(o) => !o && !busy && onClose()}>
      <DialogContent className="sm:max-w-xl">
        <form onSubmit={submit} className="flex min-h-0 flex-col" noValidate>
          <DialogHeader>
            <DialogTitle>{rule ? `Edit ${rule.name}` : "Create an alert rule"}</DialogTitle>
            <DialogDescription>
              Rules are evaluated against live data every few seconds. When one fires, every target
              is notified once, then again only after the cooldown if it is still breached.
            </DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-4">
            <Field label="Name" htmlFor="al-name">
              <Input
                id="al-name"
                autoFocus
                value={d.name}
                onChange={(e) => setD({ ...d, name: e.target.value })}
                placeholder="Checkout error rate"
              />
            </Field>
            {!rule && (
              <Field label="Type" htmlFor="al-kind">
                <Segmented
                  ariaLabel="Rule type"
                  value={d.kind}
                  onChange={(kind) => setD({ ...d, kind })}
                  options={[
                    {
                      value: "threshold",
                      label: "Threshold",
                      description: "A number crosses a line you set",
                    },
                    {
                      value: "anomaly",
                      label: "Anomaly",
                      description: "Errors deviate from their own baseline",
                    },
                  ]}
                />
              </Field>
            )}
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Service" htmlFor="al-service" hint="Empty watches every service">
                <Input
                  id="al-service"
                  value={d.service}
                  onChange={(e) => setD({ ...d, service: e.target.value })}
                  placeholder="checkout"
                />
              </Field>
              <Field label="Environment" htmlFor="al-env" hint="Empty watches every environment">
                <Input
                  id="al-env"
                  value={d.environment}
                  onChange={(e) => setD({ ...d, environment: e.target.value })}
                  placeholder="production"
                />
              </Field>
            </div>
            {d.kind === "threshold" ? (
              <>
                <div className="grid gap-4 sm:grid-cols-3">
                  <Field label="Measure" htmlFor="al-metric">
                    <SimpleSelect
                      id="al-metric"
                      value={d.metric}
                      onValueChange={(v) => setD({ ...d, metric: v as AlertMetric })}
                      disabled={!!rule}
                      options={ALERT_METRICS.map((m) => ({
                        value: m,
                        label: ALERT_METRIC[m].label,
                      }))}
                    />
                  </Field>
                  <Field label="Above" htmlFor="al-threshold" hint={metric.unit}>
                    <Input
                      id="al-threshold"
                      inputMode="decimal"
                      value={d.threshold}
                      onChange={(e) => setD({ ...d, threshold: e.target.value })}
                    />
                  </Field>
                  <Field label="Window" htmlFor="al-window" hint="minutes">
                    <Input
                      id="al-window"
                      inputMode="numeric"
                      value={d.window}
                      onChange={(e) => setD({ ...d, window: e.target.value })}
                    />
                  </Field>
                </div>
                <p className="text-xs text-muted-foreground">{metric.hint}</p>
                {d.metric === "matching_count" && (
                  <Field label="Keywords" htmlFor="al-query">
                    <Input
                      id="al-query"
                      value={d.query}
                      onChange={(e) => setD({ ...d, query: e.target.value })}
                      placeholder="payment declined"
                    />
                  </Field>
                )}
              </>
            ) : (
              <>
                <div className="grid gap-4 sm:grid-cols-3">
                  <Field label="Sensitivity" htmlFor="al-sens" hint="standard deviations">
                    <Input
                      id="al-sens"
                      inputMode="decimal"
                      value={d.sensitivity}
                      onChange={(e) => setD({ ...d, sensitivity: e.target.value })}
                    />
                  </Field>
                  <Field label="At least" htmlFor="al-min" hint="errors in 5 min">
                    <Input
                      id="al-min"
                      inputMode="numeric"
                      value={d.minCount}
                      onChange={(e) => setD({ ...d, minCount: e.target.value })}
                    />
                  </Field>
                  <Field label="Baseline" htmlFor="al-base" hint="hours of history">
                    <Input
                      id="al-base"
                      inputMode="numeric"
                      value={d.baselineHours}
                      onChange={(e) => setD({ ...d, baselineHours: e.target.value })}
                    />
                  </Field>
                </div>
                <p className="text-xs text-muted-foreground">
                  Fires when the errors of the last five minutes sit this many standard deviations
                  above the mean of the same five-minute windows over the baseline period.
                </p>
              </>
            )}
            <Field
              label="Email"
              htmlFor="al-email"
              hint="Comma separated. Locally these land in Mailpit"
            >
              <Input
                id="al-email"
                value={d.emails}
                onChange={(e) => setD({ ...d, emails: e.target.value })}
                placeholder="oncall@example.com"
              />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field
                label="Webhook URL"
                htmlFor="al-hook"
                hint={
                  rule?.has_webhook ? "Stored. Leave empty to keep it" : "Signed with HMAC-SHA256"
                }
              >
                <Input
                  id="al-hook"
                  type="url"
                  value={d.webhookUrl}
                  onChange={(e) => setD({ ...d, webhookUrl: e.target.value })}
                  placeholder="https://hooks.example.com/logmind"
                />
              </Field>
              <Field
                label="Slack webhook URL"
                htmlFor="al-slack"
                hint={rule?.has_slack ? "Stored. Leave empty to keep it" : "An incoming webhook"}
              >
                <Input
                  id="al-slack"
                  type="url"
                  value={d.slackUrl}
                  onChange={(e) => setD({ ...d, slackUrl: e.target.value })}
                  placeholder="https://hooks.slack.com/services/..."
                />
              </Field>
            </div>
            <Field
              label="Cooldown"
              htmlFor="al-cool"
              hint="minutes before a continuing breach notifies again"
            >
              <Input
                id="al-cool"
                inputMode="numeric"
                value={d.cooldown}
                onChange={(e) => setD({ ...d, cooldown: e.target.value })}
                className="sm:w-32"
              />
            </Field>
            {error && <FieldError>{error}</FieldError>}
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy}>
              {busy ? "Saving..." : rule ? "Save rule" : "Create rule"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
