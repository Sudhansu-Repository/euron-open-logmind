/**
 * Named aliases over the generated OpenAPI types (`pnpm gen:api`). Nothing here is
 * hand-written: every shape comes from `schema.d.ts`, generated from docs/api/openapi.yaml.
 */
import type { components } from "./schema";

type S = components["schemas"];

export type User = S["UserOut"];
export type UserIn = S["UserIn"];
export type UserUpdate = S["UserUpdate"];
export type Session = S["SessionOut"];
export type Org = S["OrgOut"];

export type Project = S["ProjectOut"];
export type ProjectIn = S["ProjectIn"];
export type ProjectUpdate = S["ProjectUpdate"];
export type Environment = S["EnvironmentOut"];
export type ApiKey = S["KeyOut"];
export type ApiKeyCreated = S["KeyCreated"];

export type LogEvent = S["LogEventOut"];
export type LogPage = S["LogPage"];
export type Histogram = S["HistogramOut"];
export type HistogramBucket = S["HistogramBucket"];
export type Facets = S["FacetsOut"];
export type LogContext = S["LogContextOut"];

export type ErrorGroup = S["ErrorGroupOut"];
export type ErrorGroupPage = S["ErrorGroupPage"];

export type ServiceHealth = S["ServiceHealthOut"];
export type Services = S["ServicesOut"];

export type Overview = S["OverviewOut"];
export type Anomaly = S["AnomalyOut"];
export type Usage = S["UsageOut"];

export type InvestigationSummary = S["InvestigationSummary"];
export type Investigation = S["InvestigationOut"];
export type EvidenceItem = S["EvidenceItemOut"];
export type Turn = S["TurnOut"];
export type Verify = S["VerifyOut"];
export type CitationCheck = S["CitationCheck"];

export type Provider = S["ProviderOut"];
export type ProviderCreate = S["ProviderCreate"];
export type ProviderUpdate = S["ProviderUpdate"];

export type AlertRule = S["AlertOut"];
export type AlertIn = S["AlertIn"];
export type AlertCreated = S["AlertCreated"];
export type AlertUpdate = S["AlertUpdate"];
export type AlertHistory = S["AlertHistoryOut"];

export type AuditEntry = S["AuditEntryOut"];
export type AuditPage = S["Page_AuditEntryOut_"];

export type Ready = S["ReadyOut"];
