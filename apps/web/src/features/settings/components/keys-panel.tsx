"use client";

import { KeyRoundIcon, PlusIcon } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/empty-state";
import { GatedButton } from "@/components/gated";
import { CodeBlock } from "@/components/json-view";
import { useProjectScope } from "@/components/project-select";
import { QueryState } from "@/components/query-state";
import { SecretOnceDialog } from "@/components/secret-once-dialog";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useCreateKey, useKeys, useRevokeKey } from "@/features/projects/api";
import type { ApiKey } from "@/lib/api/types";
import { errorMessage } from "@/lib/api/errors";
import { formatRelative } from "@/lib/format";

const SNIPPETS = (key: string) => ({
  python: `pip install euron-logmind

from euron_logmind import LogMind

log = LogMind(api_key="${key}", endpoint="http://localhost:6030", service="checkout")
log.info("order placed", order_id="o-123")`,
  otel: `exporters:
  otlphttp/logmind:
    logs_endpoint: http://localhost:6030/v1/logs
    headers:
      Authorization: "Bearer ${key}"`,
});

/** API keys for the scoped project: create (shown once), revoke, and how to use one. */
export function KeysPanel() {
  const [projectId] = useProjectScope();
  const keys = useKeys(projectId);
  const create = useCreateKey();
  const revoke = useRevokeKey();
  const [name, setName] = React.useState("");
  const [plain, setPlain] = React.useState<string | null>(null);
  const [revoking, setRevoking] = React.useState<ApiKey | null>(null);
  const snippets = SNIPPETS("lmk_...");

  return (
    <div className="space-y-5">
      <Surface>
        <SurfaceHeader
          title="API keys"
          description="Services, SDKs and OpenTelemetry exporters send logs with a project key. A key is shown once, when it is created; LogMind stores only a peppered hash."
        />
        <form
          className="flex flex-col gap-2 px-5 pb-4 sm:flex-row"
          onSubmit={(e) => {
            e.preventDefault();
            if (!name.trim() || !projectId) return;
            create.mutate(
              { project_id: projectId, name: name.trim() },
              {
                onSuccess: (k) => {
                  setPlain(k.key);
                  setName("");
                },
                onError: (err) => toast.error(errorMessage(err)),
              }
            );
          }}
        >
          <Input
            aria-label="Key name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Key name, for example: checkout production"
            className="sm:flex-1"
          />
          <GatedButton
            need="manageKeys"
            type="submit"
            disabled={!name.trim() || create.isPending || !projectId}
            data-qa="create-key"
          >
            <PlusIcon />
            Create key
          </GatedButton>
        </form>
        <QueryState
          query={keys}
          errorTitle="Could not load keys"
          empty={(d) => d.length === 0}
          emptyState={
            <EmptyState
              compact
              icon={KeyRoundIcon}
              title="No keys for this project"
              description="Create a key above, then put it in your service's environment as LOGMIND_API_KEY."
            />
          }
        >
          {(list) => (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead className="hidden sm:table-cell">Key</TableHead>
                  <TableHead className="hidden md:table-cell">Last used</TableHead>
                  <TableHead className="text-right">Revoke</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.map((k) => (
                  <TableRow key={k.id}>
                    <TableCell className="font-medium">{k.name}</TableCell>
                    <TableCell className="hidden font-mono text-[12px] text-muted-foreground sm:table-cell">
                      {k.display}
                    </TableCell>
                    <TableCell className="hidden text-muted-foreground md:table-cell">
                      {formatRelative(k.last_used_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <GatedButton
                        need="manageKeys"
                        variant="ghost"
                        size="xs"
                        onClick={() => setRevoking(k)}
                      >
                        Revoke
                      </GatedButton>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </QueryState>
      </Surface>
      <Surface>
        <SurfaceHeader
          title="Send logs with a key"
          description="The Python SDK, and an OpenTelemetry Collector exporter (any OTLP/HTTP exporter works, protobuf or JSON)."
        />
        <div className="grid gap-4 px-5 pb-5 lg:grid-cols-2">
          <CodeBlock code={snippets.python} label="Python SDK" />
          <CodeBlock code={snippets.otel} label="OpenTelemetry Collector" />
        </div>
      </Surface>
      <SecretOnceDialog
        value={plain}
        title="Your new API key"
        description="Copy it now: LogMind keeps only a hash and cannot show it again."
        label="API key"
        onClose={() => setPlain(null)}
      />
      <ConfirmDialog
        open={!!revoking}
        onOpenChange={(o) => !o && setRevoking(null)}
        title={`Revoke ${revoking?.name ?? "this key"}?`}
        description="Anything still sending with it is refused from now on. This cannot be undone."
        confirmLabel="Revoke key"
        pending={revoke.isPending}
        onConfirm={() =>
          revoking &&
          revoke.mutate(revoking.id, {
            onSuccess: () => {
              toast.success("Key revoked.");
              setRevoking(null);
            },
            onError: (err) => toast.error(errorMessage(err)),
          })
        }
      />
    </div>
  );
}
