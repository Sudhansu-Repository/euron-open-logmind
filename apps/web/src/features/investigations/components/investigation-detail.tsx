"use client";

import {
  ArrowLeftIcon,
  CheckCircle2Icon,
  CircleAlertIcon,
  LightbulbIcon,
  MessageSquareIcon,
  SendIcon,
  ShieldCheckIcon,
  SparklesIcon,
  XCircleIcon,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { toast } from "sonner";

import {
  EvidenceKindChip,
  GroundedBadge,
  InvestigationStatusChip,
  LevelChip,
} from "@/components/badges";
import { ErrorState } from "@/components/error-state";
import { GatedButton } from "@/components/gated";
import { Hint } from "@/components/hint";
import { PageHeader } from "@/components/page-header";
import { Stat } from "@/components/stat";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { LogDetailSheet } from "@/features/logs/components/log-detail";
import type { EvidenceItem, Investigation, Turn } from "@/lib/api/types";
import { errorMessage } from "@/lib/api/errors";
import { cn } from "@/lib/cn";
import {
  formatDateTime,
  formatNumber,
  formatPercent,
  formatRelative,
  formatTime,
  formatTokenCount,
} from "@/lib/format";

import { isPending, useFollowup, useInvestigation, useVerify } from "../api";
import { confidenceLabel, readAnswer, readReport, savedShare, type Statement } from "../report";
import { CitationChips } from "./citation";

function StatementList({
  items,
  onPick,
  icon: Icon,
}: {
  items: Statement[];
  onPick: (r: string) => void;
  icon?: React.ComponentType<{ className?: string }>;
}) {
  return (
    <ul className="space-y-2.5">
      {items.map((s, i) => (
        <li key={i} className="flex gap-2.5 text-[13.5px] leading-relaxed">
          {Icon && <Icon className="mt-1 size-3.5 shrink-0 text-primary" />}
          <span>
            {s.text} <CitationChips refs={s.evidence} onPick={onPick} />
          </span>
        </li>
      ))}
    </ul>
  );
}

function EvidenceList({
  items,
  highlight,
  onOpen,
  verified,
}: {
  items: EvidenceItem[];
  highlight: string | null;
  onOpen: (item: EvidenceItem) => void;
  verified: Map<string, boolean>;
}) {
  return (
    <ol className="space-y-1.5 px-3 pb-3" data-qa="evidence-list">
      {items.map((e) => {
        const v = verified.get(e.ref);
        return (
          <li key={e.ref} id={`evidence-${e.ref}`}>
            <button
              type="button"
              onClick={() => onOpen(e)}
              className={cn(
                "flex w-full gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-muted/70 focus-visible:outline-2 focus-visible:outline-ring",
                highlight === e.ref && "bg-primary-soft hover:bg-primary-soft"
              )}
            >
              <span className="w-9 shrink-0 font-mono text-[12px] font-semibold text-primary">
                {e.ref}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-1.5">
                  <EvidenceKindChip kind={e.kind} />
                  <LevelChip level={e.level} />
                  <span className="text-[12px] text-muted-foreground">{e.service}</span>
                  <span className="text-[12px] text-subtle tabular">{formatTime(e.timestamp)}</span>
                  {e.count > 1 && <Chip>x{formatNumber(e.count)}</Chip>}
                  {v === true && (
                    <CheckCircle2Icon
                      className="size-3.5 text-success"
                      aria-label="Verified against the stored line"
                    />
                  )}
                  {v === false && (
                    <XCircleIcon
                      className="size-3.5 text-danger"
                      aria-label="Did not match the stored line"
                    />
                  )}
                </span>
                <span className="mt-1 block font-mono text-[12px] leading-relaxed break-words text-foreground">
                  {e.message}
                </span>
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

function TurnView({ turn, onPick }: { turn: Turn; onPick: (r: string) => void }) {
  const a = readAnswer(turn.answer as Record<string, unknown> | null);
  return (
    <li className="space-y-2" data-qa="followup">
      <div className="flex items-start gap-2.5">
        <MessageSquareIcon className="mt-0.5 size-4 shrink-0 text-subtle" />
        <p className="text-[13.5px] font-medium">{turn.question}</p>
      </div>
      <div className="ml-6.5 rounded-xl bg-muted/60 p-3.5">
        {turn.status === "queued" || turn.status === "running" ? (
          <p className="flex items-center gap-2 text-[13px] text-muted-foreground">
            <SparklesIcon className="size-4 animate-pulse text-primary" />
            Looking at the evidence
            {turn.status === "running" ? " and any earlier lines it needs" : ""}...
          </p>
        ) : turn.status === "failed" ? (
          <p className="text-[13px] text-danger">{turn.error}</p>
        ) : a ? (
          <div className="space-y-2.5">
            <div className="flex flex-wrap items-center gap-2">
              <GroundedBadge grounded={turn.grounded} />
              {turn.added_evidence > 0 && (
                <Chip tone="primary">{turn.added_evidence} new evidence items</Chip>
              )}
            </div>
            <p className="text-[13.5px] leading-relaxed">{a.answer}</p>
            <StatementList items={a.findings} onPick={onPick} />
            {a.discarded.length > 0 && (
              <p className="text-[12px] text-warning">
                Removed {a.discarded.length} statement(s) that cited no real evidence.
              </p>
            )}
          </div>
        ) : null}
      </div>
    </li>
  );
}

function Compression({ inv }: { inv: Investigation }) {
  const saved = savedShare(inv.raw_tokens_estimate, inv.context_tokens_estimate);
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Stat
        label="Lines in the window"
        value={formatNumber(inv.raw_lines)}
        detail={`About ${formatTokenCount(inv.raw_tokens_estimate)} tokens if sent raw`}
      />
      <Stat
        label="Evidence items sent"
        value={formatNumber(inv.evidence_count)}
        detail={`About ${formatTokenCount(inv.context_tokens_estimate)} tokens`}
      />
      <Stat
        label="Left out by selection"
        tone="good"
        value={formatPercent(saved)}
        detail="Of the raw window volume, never sent to the model"
      />
      <Stat
        label="Tokens used"
        value={formatTokenCount(inv.input_tokens + inv.output_tokens)}
        detail={`${formatTokenCount(inv.input_tokens)} in, ${formatTokenCount(inv.output_tokens)} out (${inv.provider_name}, ${inv.model})`}
      />
    </div>
  );
}

/**
 * One investigation: the root cause, findings and timeline with their citations, the
 * evidence pack every citation points into, a verify button that re-reads each cited line
 * from the log store, and follow-up questions answered over the same evidence.
 */
export function InvestigationDetail({ id }: { id: string }) {
  const query = useInvestigation(id);
  const inv = query.data;
  const [highlight, setHighlight] = React.useState<string | null>(null);
  const [opened, setOpened] = React.useState<EvidenceItem | null>(null);
  const [verifyOn, setVerifyOn] = React.useState(false);
  const [question, setQuestion] = React.useState("");
  const followup = useFollowup(id);
  const verify = useVerify(id, verifyOn && !!inv && !isPending(inv));
  const report = readReport((inv?.report ?? null) as Record<string, unknown> | null);
  const verified = React.useMemo(
    () => new Map((verify.data?.citations ?? []).map((c) => [c.ref, c.verified])),
    [verify.data]
  );

  const pick = React.useCallback((ref: string) => {
    setHighlight(ref);
    document
      .getElementById(`evidence-${ref}`)
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);

  function ask(q: string) {
    const text = q.trim();
    if (text.length < 3) return;
    followup.mutate(text, {
      onSuccess: () => setQuestion(""),
      onError: (err) => toast.error(errorMessage(err)),
    });
  }

  if (query.isError) {
    return (
      <Surface>
        <ErrorState
          error={query.error}
          title="Could not load this investigation"
          onRetry={() => void query.refetch()}
        />
      </Surface>
    );
  }

  const working = inv && (inv.status === "queued" || inv.status === "running");

  return (
    <>
      <PageHeader
        eyebrow={
          <Link
            href="/investigations"
            className="inline-flex items-center gap-1 text-[12.5px] text-muted-foreground hover:text-foreground"
          >
            <ArrowLeftIcon className="size-3.5" />
            AI investigations
          </Link>
        }
        title={
          inv ? (
            <span className="break-words">{inv.title}</span>
          ) : (
            <Skeleton className="h-7 w-96 max-w-full" />
          )
        }
        description={
          inv
            ? `Started ${formatRelative(inv.created_at)}${inv.window_start ? `, looking at ${formatDateTime(inv.window_start)} to ${formatTime(inv.window_end)}` : ""}`
            : undefined
        }
        actions={
          inv && (
            <>
              <InvestigationStatusChip status={inv.status} />
              <GroundedBadge grounded={inv.grounded} />
              {inv.error_group_id && (
                <Link
                  href={`/errors/${inv.error_group_id}`}
                  className="text-[12.5px] text-primary hover:underline"
                >
                  Error group
                </Link>
              )}
            </>
          )
        }
      />
      {!inv ? (
        <Skeleton className="h-96 w-full" />
      ) : working ? (
        <Surface>
          <div className="flex flex-col items-center px-6 py-16 text-center">
            <SparklesIcon className="mb-3 size-8 animate-pulse text-primary" />
            <h2 className="text-sm font-semibold">
              {inv.status === "queued"
                ? "Waiting for the worker"
                : "Collecting evidence and asking the model"}
            </h2>
            <p className="mt-1 max-w-md text-[13px] text-muted-foreground">
              LogMind is querying the incident window, collapsing repeated lines, and building a
              cited report. This usually takes a few seconds.
            </p>
          </div>
        </Surface>
      ) : inv.status === "failed" ? (
        <Surface>
          <div className="flex flex-col items-center px-6 py-14 text-center" role="alert">
            <CircleAlertIcon className="mb-3 size-8 text-danger" />
            <h2 className="text-sm font-semibold">The investigation failed</h2>
            <p className="mt-1 max-w-lg text-[13px] text-muted-foreground">{inv.error}</p>
            <p className="mt-2 text-[12.5px] text-muted-foreground">
              Check the provider in{" "}
              <Link href="/settings?tab=ai" className="text-primary hover:underline">
                Settings, AI providers
              </Link>{" "}
              (Test makes one small call), then start a new investigation.
            </p>
          </div>
        </Surface>
      ) : (
        <div className="space-y-5">
          <Compression inv={inv} />
          <div className="grid gap-5 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            <div className="min-w-0 space-y-5">
              <Surface data-qa="root-cause">
                <SurfaceHeader
                  title="Root cause"
                  titleExtra={
                    <Hint text="The model's conclusion. It is only shown when it cites evidence that exists in the pack; the cited items are listed on the right and can be checked against the stored logs." />
                  }
                  action={
                    report && report.rootCause ? (
                      <Chip
                        tone={
                          report.confidence >= 0.7
                            ? "success"
                            : report.confidence >= 0.45
                              ? "warning"
                              : "neutral"
                        }
                      >
                        {confidenceLabel(report.confidence)} confidence (
                        {formatPercent(report.confidence)})
                      </Chip>
                    ) : null
                  }
                />
                <div className="space-y-3 px-5 pb-5">
                  {report?.rootCause ? (
                    <p className="text-[15px] leading-relaxed font-medium">
                      {report.rootCause}{" "}
                      <CitationChips refs={report.rootCauseEvidence} onPick={pick} />
                    </p>
                  ) : (
                    <p className="text-[13.5px] text-muted-foreground">
                      The evidence did not support a root cause the model could cite. The findings
                      below are what it could ground.
                    </p>
                  )}
                  {report?.summary && (
                    <p className="text-[13.5px] leading-relaxed text-muted-foreground">
                      {report.summary}
                    </p>
                  )}
                  {report?.impact && (
                    <p className="text-[12.5px] text-muted-foreground">
                      <span className="font-semibold text-foreground">Impact: </span>
                      {report.impact}
                    </p>
                  )}
                </div>
              </Surface>
              {report && report.findings.length > 0 && (
                <Surface>
                  <SurfaceHeader
                    title="Findings"
                    description="Each statement cites the evidence it rests on"
                  />
                  <div className="px-5 pb-5">
                    <StatementList items={report.findings} onPick={pick} icon={ShieldCheckIcon} />
                  </div>
                </Surface>
              )}
              {report && report.timeline.length > 0 && (
                <Surface>
                  <SurfaceHeader
                    title="Timeline"
                    description="Times come from the cited lines, not from the model"
                  />
                  <ol className="space-y-3 px-5 pb-5">
                    {report.timeline.map((t, i) => (
                      <li key={i} className="flex gap-3 text-[13.5px]">
                        <span className="w-[72px] shrink-0 font-mono text-[12px] text-subtle tabular">
                          {formatTime(t.at)}
                        </span>
                        <span>
                          {t.text} <CitationChips refs={t.evidence} onPick={pick} />
                        </span>
                      </li>
                    ))}
                  </ol>
                </Surface>
              )}
              {report && report.fixes.length > 0 && (
                <Surface>
                  <SurfaceHeader title="Suggested next steps" />
                  <ul className="space-y-2 px-5 pb-5">
                    {report.fixes.map((f, i) => (
                      <li key={i} className="flex gap-2.5 text-[13.5px] leading-relaxed">
                        <LightbulbIcon className="mt-0.5 size-4 shrink-0 text-warning" />
                        {f}
                      </li>
                    ))}
                  </ul>
                </Surface>
              )}
              {report && (report.discarded.length > 0 || report.rejected.length > 0) && (
                <Surface data-qa="discarded">
                  <SurfaceHeader
                    title="Removed for missing evidence"
                    description="Statements the model made without a valid citation never reach the report"
                  />
                  <div className="space-y-2 px-5 pb-5 text-[13px]">
                    {report.discarded.map((d, i) => (
                      <p
                        key={i}
                        className="text-muted-foreground line-through decoration-danger/60"
                      >
                        {d}
                      </p>
                    ))}
                    {report.rejected.length > 0 && (
                      <p className="text-[12px] text-warning">
                        Citations that pointed at no evidence: {report.rejected.join(", ")}
                      </p>
                    )}
                  </div>
                </Surface>
              )}
              <Surface>
                <SurfaceHeader
                  title="Follow-up questions"
                  description="Answered over the same evidence, with more earlier lines added when the question needs them"
                />
                <div className="space-y-4 px-5 pb-5">
                  {inv.turns.length > 0 && (
                    <ul className="space-y-4">
                      {inv.turns.map((t) => (
                        <TurnView key={t.id} turn={t} onPick={pick} />
                      ))}
                    </ul>
                  )}
                  {report && report.followUps.length > 0 && (
                    <div className="flex flex-wrap gap-2">
                      {report.followUps.map((q) => (
                        <Button
                          key={q}
                          variant="secondary"
                          size="xs"
                          onClick={() => ask(q)}
                          disabled={followup.isPending}
                        >
                          {q}
                        </Button>
                      ))}
                    </div>
                  )}
                  <form
                    className="flex gap-2"
                    onSubmit={(e) => {
                      e.preventDefault();
                      ask(question);
                    }}
                  >
                    <Input
                      aria-label="Follow-up question"
                      value={question}
                      onChange={(e) => setQuestion(e.target.value)}
                      placeholder="What changed before this started?"
                      data-qa="followup-input"
                    />
                    <GatedButton
                      need="investigate"
                      type="submit"
                      disabled={question.trim().length < 3 || followup.isPending}
                    >
                      <SendIcon />
                      Ask
                    </GatedButton>
                  </form>
                </div>
              </Surface>
            </div>
            <Surface className="h-fit xl:sticky xl:top-4">
              <SurfaceHeader
                title="Evidence"
                description={`${inv.evidence.length} real stored lines, numbered in time order`}
                action={
                  <Button
                    size="xs"
                    variant="outline"
                    onClick={() => (verifyOn ? void verify.refetch() : setVerifyOn(true))}
                    disabled={verify.isFetching}
                    data-qa="verify"
                  >
                    <ShieldCheckIcon />
                    {verify.isFetching ? "Checking..." : "Verify citations"}
                  </Button>
                }
              />
              {verify.data && (
                <p
                  className={cn(
                    "mx-5 mb-3 rounded-lg px-3 py-2 text-[12.5px]",
                    verify.data.all_verified
                      ? "bg-success-soft text-success"
                      : "bg-danger-soft text-danger"
                  )}
                  role="status"
                  data-qa="verify-result"
                >
                  {verify.data.all_verified
                    ? `All ${verify.data.checked} cited lines were re-read from the log store and match the report.`
                    : `${verify.data.verified} of ${verify.data.checked} cited lines matched the log store.`}
                </p>
              )}
              {verify.isError && (
                <p className="mx-5 mb-3 text-[12.5px] text-danger">{errorMessage(verify.error)}</p>
              )}
              <EvidenceList
                items={inv.evidence}
                highlight={highlight}
                onOpen={setOpened}
                verified={verified}
              />
            </Surface>
          </div>
        </div>
      )}
      <LogDetailSheet
        projectId={inv?.project_id ?? ""}
        eventId={opened?.event_id ?? null}
        at={opened?.timestamp ?? null}
        onClose={() => setOpened(null)}
      />
    </>
  );
}
