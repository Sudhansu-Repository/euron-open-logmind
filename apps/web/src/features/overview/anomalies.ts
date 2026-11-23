/**
 * Consecutive anomalous five-minute windows of one service are one spike, shown as one row
 * with its start, end and peak. Pure, unit tested.
 */
import type { Anomaly } from "@/lib/api/types";

export interface Spike {
  service: string;
  start: string;
  end: string;
  windows: number;
  peak: number;
  expected: number;
  zscore: number;
}

const STEP_MS = 5 * 60_000;

export function groupSpikes(anomalies: Anomaly[]): Spike[] {
  const byService = new Map<string, Anomaly[]>();
  for (const a of anomalies) byService.set(a.service, [...(byService.get(a.service) ?? []), a]);
  const spikes: Spike[] = [];
  for (const [service, list] of byService) {
    const sorted = [...list].sort((x, y) => x.at.localeCompare(y.at));
    let run: Anomaly[] = [];
    const flush = () => {
      if (!run.length) return;
      const peak = run.reduce((m, a) => (a.value > m.value ? a : m));
      spikes.push({
        service,
        start: run[0]!.at,
        end: run[run.length - 1]!.at,
        windows: run.length,
        peak: peak.value,
        expected: Math.min(...run.map((a) => a.expected)),
        zscore: Math.max(...run.map((a) => a.zscore)),
      });
      run = [];
    };
    for (const a of sorted) {
      const last = run[run.length - 1];
      if (last && new Date(a.at).getTime() - new Date(last.at).getTime() > STEP_MS) flush();
      run.push(a);
    }
    flush();
  }
  return spikes.sort((x, y) => y.end.localeCompare(x.end));
}
