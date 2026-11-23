"use client";

import { ArrowRightIcon, ScrollTextIcon } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/empty-state";
import { CodeBlock } from "@/components/json-view";
import { buttonVariants } from "@/components/ui/button";

/** The first-run state of every log view: what to send, and where to get a key. */
export function SendFirstLog({ compact = false }: { compact?: boolean }) {
  const origin =
    typeof window === "undefined"
      ? "http://localhost:6030"
      : window.location.origin.replace(/:\d+$/, ":6030");
  const snippet = `curl -X POST ${origin}/api/v1/logs \\
  -H "Authorization: Bearer $LOGMIND_API_KEY" \\
  -H "content-type: application/json" \\
  -d '{"message": "hello from my service", "level": "info", "service": "checkout"}'`;
  return (
    <div className="space-y-4">
      <EmptyState
        compact={compact}
        icon={ScrollTextIcon}
        title="No logs in this window yet"
        description="Lines appear here within a second of being sent. Use the Python or Node SDK, any OpenTelemetry exporter (OTLP/HTTP to /v1/logs), or plain HTTP with a project API key from Settings."
        action={
          <Link href="/settings?tab=keys" className={buttonVariants({ size: "sm" })}>
            Get an API key
            <ArrowRightIcon />
          </Link>
        }
      />
      {!compact && (
        <div className="mx-auto max-w-2xl px-5 pb-6">
          <CodeBlock code={snippet} label="curl example" />
        </div>
      )}
    </div>
  );
}

/** Shown when the organisation has no project at all. */
export function NoProject() {
  return (
    <EmptyState
      icon={ScrollTextIcon}
      title="Create a project first"
      description="A project holds one application's logs, its API keys, retention and redaction policy. Create one in Settings, then send your first line."
      action={
        <Link href="/settings?tab=projects" className={buttonVariants({ size: "sm" })}>
          Create a project
          <ArrowRightIcon />
        </Link>
      }
    />
  );
}
