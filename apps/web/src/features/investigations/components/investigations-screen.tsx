"use client";

import { SparklesIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { GroundedBadge, InvestigationStatusChip } from "@/components/badges";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { GatedButton } from "@/components/gated";
import { PageHeader } from "@/components/page-header";
import { useProjectScope } from "@/components/project-select";
import { Stat } from "@/components/stat";
import { Surface, SurfaceHeader } from "@/components/surface";
import { TableSkeleton } from "@/components/table-skeleton";
import { buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useProviders } from "@/features/providers/api";
import { errorMessage } from "@/lib/api/errors";
import { formatNumber, formatPercent, formatRelative, formatTokenCount } from "@/lib/format";

import { useInvestigate, useInvestigations, useUsage } from "../api";

/**
 * Every investigation in the project, the token spend behind them, and a box to ask a
 * free-form question about the last hour of logs.
 */
export function InvestigationsScreen() {
  const [projectId] = useProjectScope();
  const router = useRouter();
  const list = useInvestigations(projectId);
  const usage = useUsage(projectId, 30);
  const providers = useProviders();
  const investigate = useInvestigate();
  const [question, setQuestion] = React.useState("");
  const hasProvider = (providers.data ?? []).some((p) => p.enabled);

  function ask(e: React.FormEvent) {
    e.preventDefault();
    if (!question.trim() || !projectId) return;
    investigate.mutate(
      { project_id: projectId, question: question.trim(), window_minutes: 60 },
      {
        onSuccess: (inv) => router.push(`/investigations/${inv.id}`),
        onError: (err) => toast.error(errorMessage(err)),
      }
    );
  }

  return (
    <>
      <PageHeader
        title="AI investigations"
        description="Root cause reports grounded in your own logs. LogMind selects and compresses the evidence first, then every claim the model makes must cite a real stored line."
      />
      {providers.isSuccess && !hasProvider && (
        <Surface className="mb-5">
          <EmptyState
            compact
            icon={SparklesIcon}
            title="Add an AI provider to investigate"
            description="OpenAI, Anthropic, Gemini, a local Ollama, any OpenAI-compatible gateway, or the built-in mock with no key. Search, grouping and alerts already work without one."
            action={
              <Link href="/settings?tab=ai" className={buttonVariants({ size: "sm" })}>
                Add a provider
              </Link>
            }
          />
        </Surface>
      )}
      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          label="Investigations, 30 days"
          loading={usage.isPending}
          value={formatNumber(usage.data?.investigations)}
        />
        <Stat
          label="Model tokens, 30 days"
          loading={usage.isPending}
          value={formatTokenCount(
            (usage.data?.input_tokens ?? 0) + (usage.data?.output_tokens ?? 0)
          )}
          detail={
            usage.data
              ? `${formatTokenCount(usage.data.input_tokens)} in, ${formatTokenCount(usage.data.output_tokens)} out`
              : undefined
          }
        />
        <Stat
          label="Raw volume never sent"
          loading={usage.isPending}
          tone="good"
          value={formatPercent(usage.data?.saved_ratio)}
          detail="Share of the incident windows' log volume left out by evidence selection"
        />
        <Stat
          label="Model calls"
          loading={usage.isPending}
          value={formatNumber(usage.data?.calls)}
          detail="Reports and follow-ups"
        />
      </div>
      <Surface className="mb-5">
        <SurfaceHeader
          title="Ask about the last hour"
          description="No error group needed: LogMind gathers the warnings, errors and change events of the last hour and answers with citations."
        />
        <form onSubmit={ask} className="flex flex-col gap-2 px-5 pb-5 sm:flex-row">
          <Input
            aria-label="Question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Why did checkout get slow in the last hour?"
            className="flex-1"
          />
          <GatedButton
            need="investigate"
            type="submit"
            disabled={!question.trim() || investigate.isPending || !hasProvider}
            reason={hasProvider ? null : "Add an AI provider in Settings first."}
          >
            <SparklesIcon />
            {investigate.isPending ? "Starting..." : "Investigate"}
          </GatedButton>
        </form>
      </Surface>
      <Surface>
        {list.isPending ? (
          <TableSkeleton rows={6} cols={4} />
        ) : list.isError ? (
          <ErrorState
            compact
            error={list.error}
            title="Could not load investigations"
            onRetry={() => void list.refetch()}
          />
        ) : list.data.length === 0 ? (
          <EmptyState
            icon={SparklesIcon}
            title="No investigations yet"
            description="Open an error group and choose Investigate with AI, or ask a question above. The report lists its evidence so anyone can check it."
            action={
              <Link href="/errors" className={buttonVariants({ size: "sm", variant: "outline" })}>
                Go to errors
              </Link>
            }
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Investigation</TableHead>
                <TableHead className="hidden md:table-cell">Evidence</TableHead>
                <TableHead className="hidden lg:table-cell">Tokens</TableHead>
                <TableHead className="hidden sm:table-cell">Started</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.data.map((inv) => (
                <TableRow key={inv.id}>
                  <TableCell className="max-w-0">
                    <Link
                      href={`/investigations/${inv.id}`}
                      className="block min-w-0 rounded focus-visible:outline-2 focus-visible:outline-ring"
                    >
                      <span className="flex flex-wrap items-center gap-2">
                        <InvestigationStatusChip status={inv.status} />
                        <GroundedBadge grounded={inv.grounded} />
                      </span>
                      <span className="mt-1 block truncate font-medium">{inv.title}</span>
                      <span className="block truncate text-[12px] text-muted-foreground">
                        {inv.root_cause || inv.error || "Collecting evidence"}
                      </span>
                    </Link>
                  </TableCell>
                  <TableCell className="hidden text-[12.5px] text-muted-foreground md:table-cell">
                    {formatNumber(inv.evidence_count)} items from {formatNumber(inv.raw_lines)}{" "}
                    lines
                  </TableCell>
                  <TableCell className="hidden text-[12.5px] tabular lg:table-cell">
                    {formatTokenCount(inv.input_tokens + inv.output_tokens)}
                  </TableCell>
                  <TableCell className="hidden text-[12.5px] whitespace-nowrap text-muted-foreground sm:table-cell">
                    {formatRelative(inv.created_at)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Surface>
    </>
  );
}
