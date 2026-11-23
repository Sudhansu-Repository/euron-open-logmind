# Alerting and anomaly detection

## Rules

| Kind | Measures | Fires when |
| --- | --- | --- |
| `threshold` / `error_count` | Error and fatal lines in the last `window_minutes` | Above `threshold` |
| `threshold` / `error_rate` | Errors as a percentage of all lines in the window | Above `threshold` (percent) |
| `threshold` / `log_count` | All lines in the window | Above `threshold` |
| `threshold` / `matching_count` | Lines containing every keyword of `query` | Above `threshold` |
| `anomaly` | Errors in the five minutes ending now, against the five-minute windows of the last `baseline_hours` | `zscore >= sensitivity` and at least `min_count` errors |

Each can be scoped to a service and an environment. Counts come from the per-minute rollup
except `matching_count`, which reads lines.

## Anomaly math (`analytics/anomaly.py`)

For each window the baseline is the mean and standard deviation of the windows before it,
never including itself. The spread used is `max(std, sqrt(mean), 1)`: error counts are close
to Poisson, so a quiet series going from 0 to 2 errors does not look like a ten sigma event.
The Overview runs the same detector over every service's aligned five-minute series for the
whole window, with a four hour trailing baseline; alert rules use sliding windows ending now.

## Evaluation and delivery (`alerts/service.py`)

1. A worker selects one enabled rule not evaluated within the interval, with
   `FOR UPDATE SKIP LOCKED`. With several workers, each rule is evaluated by exactly one.
2. It measures the rule, stores `last_value` and the time, and decides: `ok -> firing` writes
   a `fired` history row; `firing -> ok` writes `resolved`; still firing after
   `cooldown_minutes` fires again as a reminder.
3. It commits, releasing the lock, then delivers to every target and writes each outcome to
   the history row. A slow webhook never holds a lock; a crash mid-delivery cannot fire twice.

## Channels

- **Email**: SMTP (Mailpit locally) or SES; subject `[LogMind] FIRING: <rule> (<project>)`.
- **Webhook**: JSON `{event, alert, project, value, threshold, expected, zscore, message, at,
  link}` with `X-LogMind-Event`, `X-LogMind-Delivery` and
  `X-LogMind-Signature: t=<unix>,v1=<hex HMAC-SHA256 of "<t>.<body>">`, using the rule's own
  `whsec_` secret, shown once at creation.
- **Slack**: an incoming webhook with a text and a button back to the rule.

Webhook and Slack URLs and the signing secret are sealed; URLs are checked against metadata
addresses at creation and at send time.
