/**
 * Pure helpers over an investigation report (the JSON the API validated: every
 * statement already carries only evidence ids that exist). Unit tested.
 */

export interface Statement {
  text: string;
  evidence: string[];
}

export interface TimelineEntry extends Statement {
  at: string;
}

export interface ReportView {
  summary: string;
  rootCause: string;
  rootCauseEvidence: string[];
  confidence: number;
  impact: string;
  findings: Statement[];
  timeline: TimelineEntry[];
  fixes: string[];
  followUps: string[];
  discarded: string[];
  rejected: string[];
}

const str = (v: unknown): string => (typeof v === "string" ? v : "");
const strs = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];

function statements(v: unknown, key: string): Statement[] {
  if (!Array.isArray(v)) return [];
  return v
    .filter((x): x is Record<string, unknown> => typeof x === "object" && x !== null)
    .map((x) => ({ text: str(x[key]), evidence: strs(x.evidence) }))
    .filter((s) => s.text);
}

export function readReport(raw: Record<string, unknown> | null | undefined): ReportView | null {
  if (!raw) return null;
  const timeline = Array.isArray(raw.timeline)
    ? (raw.timeline as unknown[])
        .filter((x): x is Record<string, unknown> => typeof x === "object" && x !== null)
        .map((x) => ({ text: str(x.description), evidence: strs(x.evidence), at: str(x.at) }))
        .filter((t) => t.text)
    : [];
  return {
    summary: str(raw.summary),
    rootCause: str(raw.root_cause),
    rootCauseEvidence: strs(raw.root_cause_evidence),
    confidence: typeof raw.confidence === "number" ? raw.confidence : 0,
    impact: str(raw.impact),
    findings: statements(raw.findings, "statement"),
    timeline,
    fixes: strs(raw.suggested_fixes),
    followUps: strs(raw.follow_up_questions),
    discarded: strs(raw.discarded),
    rejected: strs(raw.rejected_citations),
  };
}

export interface AnswerView {
  answer: string;
  findings: Statement[];
  confidence: number;
  discarded: string[];
  rejected: string[];
}

export function readAnswer(raw: Record<string, unknown> | null | undefined): AnswerView | null {
  if (!raw) return null;
  return {
    answer: str(raw.answer),
    findings: statements(raw.findings, "statement"),
    confidence: typeof raw.confidence === "number" ? raw.confidence : 0,
    discarded: strs(raw.discarded),
    rejected: strs(raw.rejected_citations),
  };
}

/** "High", "Medium" or "Low" for a 0 to 1 confidence. */
export function confidenceLabel(c: number): "High" | "Medium" | "Low" {
  if (c >= 0.7) return "High";
  if (c >= 0.45) return "Medium";
  return "Low";
}

/** How much of the raw window never reached the model, as a 0 to 1 share. */
export function savedShare(rawTokens: number, contextTokens: number): number {
  if (rawTokens <= 0) return 0;
  return Math.max(0, Math.min(1, 1 - contextTokens / rawTokens));
}
