# Security Policy

LogMind stores and analyses other systems' logs, which routinely carry personal data and
secrets by accident. Its security surface is: who can read which logs, what reaches storage,
what an AI report is allowed to claim, and what leaves the deployment. See
[docs/architecture/security.md](docs/architecture/security.md) for the full model (what it
guarantees and what it does not) before filing a report.

## Supported versions

| Version | Supported |
| ------- | --------- |
| 0.x (latest minor) | Yes |
| Older minors | No |

## Reporting a vulnerability

**Please do not open a public issue for security issues.**

Report privately through GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository ("Security" tab, "Report a vulnerability").

Please include the affected component (`apps/api` and which domain, the worker, `apps/web`,
`sdks/python`, `sdks/node`, `infra/terraform/...`) and version or commit, a description of
the issue and its impact, steps to reproduce (the project's redaction settings, the payload,
the role or key used), and any suggested mitigation.

| Stage | Target |
| ----- | ------ |
| Acknowledgement | within 3 business days |
| Initial assessment and severity | within 7 business days |
| Fix or mitigation for critical and high issues | within 30 days |
| Coordinated public disclosure | after a fix is released, credited to you unless you prefer otherwise |

## In scope

- **A redaction bypass.** A value of an enabled category (credential, email, card, ...)
  reaching ClickHouse, Postgres (error group samples), the evidence store, the live stream or
  a model prompt unredacted.
- **A tenant isolation break.** A session or API key from one organisation reading, listing
  or changing another organisation's logs, error groups, investigations, alerts, providers or
  keys, including through a crafted ClickHouse filter.
- **A grounding break.** An investigation report or follow-up showing a statement whose
  citation does not resolve to a stored line of that project, or a verify result that says a
  line matched when it did not.
- **An authentication or key-handling flaw.** A key's secret recoverable from stored data, a
  timing side channel, a session usable after its user was disabled, a sealed provider key or
  webhook URL returned by any endpoint.
- **SSRF or injection** through an AI provider base URL, an alert webhook or Slack URL, a log
  search, or any admin field.
- **A production boot-guard bypass.** `Settings.guard()` accepting a placeholder secret,
  insecure cookies, wildcard CORS, local storage or the log mail backend in production.

## Out of scope

- **The demo seed.** `make demo` creates well-known demo accounts with a published password,
  on purpose.
- **The mock AI service** (`apps/api/src/mockai`), a test and demo fixture never deployed.
- **What a real model concludes.** LogMind guarantees every shown claim cites a real line;
  it cannot guarantee the reasoning that connects them is right. Reports show a confidence
  and the evidence so a person can judge.
- **Recall of the redaction recognizers.** Personal data in an unrecognised format (a name, a
  free-text address) is not detected; projects can add custom patterns. A recognised category
  slipping through is in scope.
