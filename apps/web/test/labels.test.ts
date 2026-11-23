import { describe, expect, it } from "vitest";

import { hourlySeries } from "@/components/charts/sparkline";
import { toVolumePoints } from "@/components/charts/volume-chart";
import {
  alertStateSpec,
  evidenceSpec,
  groupStatusSpec,
  investigationStatusSpec,
  levelColor,
  levelSpec,
  LEVELS,
  REDACTION_CATEGORIES,
  serviceStatusSpec,
} from "@/lib/labels";
import { activeNavItem } from "@/lib/nav";

describe("labels", () => {
  it("gives every level, status and evidence kind a label and a tone", () => {
    for (const l of LEVELS) expect(levelSpec(l).label).not.toBe("Unknown");
    expect(levelSpec("weird")).toEqual({ label: "weird", tone: "neutral" });
    expect(levelColor("error")).toBe("var(--level-error)");
    expect(levelColor("nope")).toBe("var(--level-info)");
    expect(groupStatusSpec("resolved").tone).toBe("success");
    expect(investigationStatusSpec("failed").tone).toBe("danger");
    expect(serviceStatusSpec("critical").tone).toBe("danger");
    expect(evidenceSpec("change").label).toBe("Change");
    expect(evidenceSpec(null).label).toBe("Evidence");
    expect(alertStateSpec("firing").tone).toBe("danger");
    expect(alertStateSpec("firing", false).label).toBe("Off");
    expect(REDACTION_CATEGORIES).toContain("credential");
  });

  it("maps paths to nav items", () => {
    expect(activeNavItem("/errors/abc")?.href).toBe("/errors");
    expect(activeNavItem("/investigations/x/")?.label).toBe("AI investigations");
    expect(activeNavItem("/nowhere")).toBeUndefined();
  });

  it("builds chart series", () => {
    const now = Date.UTC(2026, 0, 1, 5, 30);
    expect(
      hourlySeries(
        [
          { hour: "2026-01-01T05:00:00Z", count: 3 },
          { hour: "2026-01-01T03:00:00Z", count: 1 },
        ],
        4,
        now
      )
    ).toEqual([0, 1, 0, 3]);
    const pts = toVolumePoints([
      { at: "2026-01-01T00:00:00Z", trace: 1, debug: 2, info: 3, warn: 4, error: 5, fatal: 6 },
    ]);
    expect(pts[0]).toEqual({
      at: Date.UTC(2026, 0, 1),
      debug: 3,
      info: 3,
      warn: 4,
      error: 5,
      fatal: 6,
    });
  });
});

describe("anomaly spikes", async () => {
  const { groupSpikes } = await import("@/features/overview/anomalies");
  const a = (service: string, minute: number, value: number) => ({
    service,
    at: new Date(Date.UTC(2026, 0, 1, 10, minute)).toISOString(),
    value,
    expected: 2,
    zscore: value / 2,
  });
  it("merges consecutive windows per service and sorts newest first", () => {
    const spikes = groupSpikes([
      a("checkout", 0, 30),
      a("checkout", 5, 44),
      a("checkout", 10, 40),
      a("checkout", 30, 20),
      a("search", 15, 12),
    ]);
    expect(spikes.map((s) => [s.service, s.windows, s.peak])).toEqual([
      ["checkout", 1, 20],
      ["search", 1, 12],
      ["checkout", 3, 44],
    ]);
    expect(groupSpikes([])).toEqual([]);
  });
});
