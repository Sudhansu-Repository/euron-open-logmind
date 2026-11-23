"use client";

import { ShieldCheckIcon, ShieldAlertIcon } from "lucide-react";
import * as React from "react";

import { Chip } from "@/components/ui/chip";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  alertEventSpec,
  alertStateSpec,
  evidenceSpec,
  groupStatusSpec,
  investigationStatusSpec,
  levelSpec,
  serviceStatusSpec,
} from "@/lib/labels";
import type { Spec } from "@/lib/tones";

function WithTip({ tip, children }: { tip?: React.ReactNode; children: React.ReactNode }) {
  if (!tip) return <>{children}</>;
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <span
            tabIndex={0}
            className="inline-flex rounded-full focus-visible:outline-2 focus-visible:outline-ring"
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent>{tip}</TooltipContent>
    </Tooltip>
  );
}

function SpecChip({
  spec,
  dot = false,
  tip = true,
  children,
}: {
  spec: Spec;
  dot?: boolean;
  tip?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <WithTip tip={tip ? spec.hint : undefined}>
      <Chip tone={spec.tone} dot={dot}>
        {children}
        {spec.label}
      </Chip>
    </WithTip>
  );
}

export function LevelChip({ level, tip = false }: { level: string; tip?: boolean }) {
  return <SpecChip spec={levelSpec(level)} tip={tip} />;
}

export function GroupStatusChip({ status }: { status: string }) {
  return <SpecChip spec={groupStatusSpec(status)} dot />;
}

export function InvestigationStatusChip({ status }: { status: string }) {
  return <SpecChip spec={investigationStatusSpec(status)} dot />;
}

export function ServiceStatusChip({ status }: { status: string }) {
  return <SpecChip spec={serviceStatusSpec(status)} dot />;
}

export function EvidenceKindChip({ kind }: { kind: string }) {
  return <SpecChip spec={evidenceSpec(kind)} />;
}

export function AlertStateChip({ state, enabled = true }: { state: string; enabled?: boolean }) {
  return <SpecChip spec={alertStateSpec(state, enabled)} dot />;
}

export function AlertEventChip({ event }: { event: string }) {
  return <SpecChip spec={alertEventSpec(event)} tip={false} />;
}

/** Whether every claim in a report cites real evidence (A3). */
export function GroundedBadge({ grounded }: { grounded: boolean | null | undefined }) {
  if (grounded == null) return null;
  return grounded ? (
    <WithTip tip="Every statement in this answer cites at least one real log line from the evidence pack.">
      <Chip tone="success">
        <ShieldCheckIcon aria-hidden />
        Grounded
      </Chip>
    </WithTip>
  ) : (
    <WithTip tip="Some statements cited evidence that does not exist, or none at all. They were removed and are listed separately.">
      <Chip tone="warning">
        <ShieldAlertIcon aria-hidden />
        Partly grounded
      </Chip>
    </WithTip>
  );
}

/** A value the redaction engine replaced before storage. */
export function RedactedCount({ count }: { count: number }) {
  if (!count) return null;
  return (
    <WithTip tip="Values redacted at ingestion, before the line was stored. The original never reached the log store.">
      <Chip tone="warning">{count} redacted</Chip>
    </WithTip>
  );
}
