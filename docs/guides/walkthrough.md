# Walkthrough

After `make up && make demo`, sign in as `owner@lumen.example` / `Demo-Owner-Pass-1`.

1. **Overview.** 24 hours of Lumen Retail's Storefront: volume by level with the incident
   spike at the right edge, the error count against the previous window, open error groups,
   redacted values, anomalies flagged against each service's own baseline (checkout, last 40
   minutes), service health, the finished AI investigation and the alert that fired.
2. **Log explorer.** Search `timeout`, filter level `error` and service `checkout`. Click a
   line: its fields, the stack trace, attributes, the lines before and after from checkout
   and the gateway line of the same trace. Password reset lines show `[REDACTED:email]`, card
   numbers `[REDACTED:payment_card]`; the originals never reached storage.
3. **Live logs.** Send a line with curl or an SDK (Settings, API keys shows how) and watch it
   arrive.
4. **Errors.** `PaymentGatewayTimeout` is one group with about 230 occurrences although each
   line had a different order id and line number; the search `TypeError` group has occurred
   all day. Open the timeout group.
5. **AI investigation.** The demo already ran one: the root cause cites the payments deploy,
   the connection pool warnings and the first checkout failure. The header shows how many
   lines were in the window and how few reached the model. Click a citation to jump to its
   evidence, click the evidence to open the real stored line, and press Verify citations: the
   API re-reads every cited line from ClickHouse. Ask "Is it still happening?".
6. **Services.** checkout is critical, notifications degraded, the rest healthy.
7. **Alerts.** "Checkout error rate" fired and resolved; open it for the delivery outcomes.
   The email is in Mailpit, the Slack message at http://localhost:6050/hooks/slack-oncall.
8. **Settings.** Projects (retention and redaction, with a live preview), API keys, AI
   providers (the mock gateway), people and the audit log.
