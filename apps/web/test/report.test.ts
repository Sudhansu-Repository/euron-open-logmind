import { describe, expect, it } from "vitest";

import {
  confidenceLabel,
  readAnswer,
  readReport,
  savedShare,
} from "@/features/investigations/report";
import { isPending } from "@/features/investigations/api";

describe("investigation report", () => {
  it("reads the validated report defensively", () => {
    const r = readReport({
      summary: "s",
      root_cause: "pool exhausted",
      root_cause_evidence: ["E1", 2],
      confidence: 0.78,
      findings: [{ statement: "a", evidence: ["E1"] }, { statement: "", evidence: [] }, "junk"],
      timeline: [{ description: "t", evidence: ["E2"], at: "2026-01-01T00:00:00Z" }],
      suggested_fixes: ["fix"],
      follow_up_questions: ["why?"],
      discarded: ["made up"],
      rejected_citations: ["E999"],
    });
    expect(r).toMatchObject({
      rootCause: "pool exhausted",
      rootCauseEvidence: ["E1"],
      confidence: 0.78,
      fixes: ["fix"],
      followUps: ["why?"],
      discarded: ["made up"],
      rejected: ["E999"],
    });
    expect(r?.findings).toEqual([{ text: "a", evidence: ["E1"] }]);
    expect(r?.timeline[0]?.at).toBe("2026-01-01T00:00:00Z");
    expect(readReport(null)).toBeNull();
    expect(readReport({})?.confidence).toBe(0);
  });

  it("reads follow-up answers", () => {
    expect(
      readAnswer({ answer: "x", findings: [{ statement: "y", evidence: ["E3"] }], confidence: 0.7 })
    ).toMatchObject({ answer: "x", confidence: 0.7, findings: [{ text: "y", evidence: ["E3"] }] });
    expect(readAnswer(undefined)).toBeNull();
  });

  it("labels confidence and the compression saving", () => {
    expect(confidenceLabel(0.8)).toBe("High");
    expect(confidenceLabel(0.5)).toBe("Medium");
    expect(confidenceLabel(0.1)).toBe("Low");
    expect(savedShare(10_000, 1_000)).toBeCloseTo(0.9);
    expect(savedShare(0, 10)).toBe(0);
    expect(savedShare(10, 50)).toBe(0);
  });

  it("knows when to keep polling", () => {
    expect(isPending(undefined)).toBe(false);
    expect(isPending({ status: "running", turns: [] })).toBe(true);
    expect(isPending({ status: "completed", turns: [] })).toBe(false);
    expect(isPending({ status: "completed", turns: [{ status: "queued" } as never] })).toBe(true);
  });
});
