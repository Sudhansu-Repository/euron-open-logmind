"use client";

import { PlusIcon, SparklesIcon } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { Chip } from "@/components/ui/chip";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/empty-state";
import { GatedButton } from "@/components/gated";
import { QueryState } from "@/components/query-state";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Input } from "@/components/ui/input";
import { Field, FieldError } from "@/components/ui/label";
import { SimpleSelect } from "@/components/ui/select";
import {
  useCreateProvider,
  useDeleteProvider,
  useProviders,
  useTestProvider,
  useUpdateProvider,
} from "@/features/providers/api";
import type { Provider } from "@/lib/api/types";
import { errorMessage } from "@/lib/api/errors";
import { formatRelative } from "@/lib/format";
import { PROVIDER_KIND, PROVIDER_KINDS, type ProviderKind } from "@/lib/labels";

/** AI providers for the organisation: AI is optional, and every key is sealed. */
export function AiPanel() {
  const providers = useProviders();
  const create = useCreateProvider();
  const update = useUpdateProvider();
  const test = useTestProvider();
  const del = useDeleteProvider();
  const [kind, setKind] = React.useState<ProviderKind>("mock");
  const [name, setName] = React.useState("");
  const [model, setModel] = React.useState("");
  const [baseUrl, setBaseUrl] = React.useState("");
  const [apiKey, setApiKey] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [removing, setRemoving] = React.useState<Provider | null>(null);
  const spec = PROVIDER_KIND[kind];

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const slug = (name.trim() || kind).toLowerCase().replace(/[^a-z0-9_-]+/g, "-");
    if (spec.needsUrl && !baseUrl.trim()) return setError("This kind needs its base URL.");
    if (spec.needsKey && !apiKey.trim()) return setError("Paste the provider's API key.");
    setError(null);
    create.mutate(
      {
        name: slug,
        kind,
        model: model.trim(),
        base_url: baseUrl.trim() || null,
        api_key: apiKey.trim() || null,
        timeout_s: 60,
        enabled: true,
        is_default: false,
      },
      {
        onSuccess: () => {
          toast.success("Provider added.");
          setName("");
          setApiKey("");
          setModel("");
          setBaseUrl("");
        },
        onError: (err) => setError(errorMessage(err)),
      }
    );
  }

  return (
    <div className="space-y-5">
      <Surface>
        <SurfaceHeader
          title="AI providers"
          description="Used only by AI investigations. Log search, error grouping and alerts never need one. Keys are sealed with KMS (or the local master key) and never shown again."
        />
        <QueryState
          query={providers}
          errorTitle="Could not load providers"
          empty={(d) => d.length === 0}
          emptyState={
            <EmptyState
              compact
              icon={SparklesIcon}
              title="No AI provider yet"
              description="Add the built-in mock to try investigations with no key, or connect OpenAI, Anthropic, Gemini, Ollama or any OpenAI-compatible gateway."
            />
          }
        >
          {(list) => (
            <ul className="divide-y divide-hairline px-5 pb-3">
              {list.map((p) => (
                <li key={p.id} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center">
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-2 font-medium">
                      {p.name}
                      {p.is_default && <Chip tone="primary">Default</Chip>}
                      {!p.enabled && <Chip>Off</Chip>}
                      {p.last_test_ok === true && <Chip tone="success">Test passed</Chip>}
                      {p.last_test_ok === false && <Chip tone="danger">Test failed</Chip>}
                    </span>
                    <span className="block text-[12px] text-muted-foreground">
                      {PROVIDER_KIND[p.kind as ProviderKind]?.label ?? p.kind}, {p.model}
                      {p.base_url ? `, ${p.base_url}` : ""}
                      {p.has_api_key ? ", key stored" : ""}
                      {p.last_test_at ? `, tested ${formatRelative(p.last_test_at)}` : ""}
                    </span>
                    {p.last_test_ok === false && p.last_test_message && (
                      <span className="block text-[12px] text-danger">{p.last_test_message}</span>
                    )}
                  </span>
                  <span className="flex gap-1.5">
                    <GatedButton
                      need="manageProviders"
                      size="xs"
                      variant="outline"
                      onClick={() =>
                        test.mutate(p.id, {
                          onSuccess: (r) =>
                            r.ok
                              ? toast.success(`${p.name} answered in ${r.latency_ms} ms.`)
                              : toast.error(r.message),
                          onError: (err) => toast.error(errorMessage(err)),
                        })
                      }
                      disabled={test.isPending}
                    >
                      Test
                    </GatedButton>
                    {!p.is_default && (
                      <GatedButton
                        need="manageProviders"
                        size="xs"
                        variant="ghost"
                        onClick={() =>
                          update.mutate(
                            { id: p.id, body: { is_default: true } },
                            { onError: (err) => toast.error(errorMessage(err)) }
                          )
                        }
                      >
                        Make default
                      </GatedButton>
                    )}
                    <GatedButton
                      need="manageProviders"
                      size="xs"
                      variant="ghost"
                      onClick={() => setRemoving(p)}
                    >
                      Remove
                    </GatedButton>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </QueryState>
      </Surface>
      <Surface>
        <SurfaceHeader title="Add a provider" />
        <form onSubmit={submit} className="space-y-4 px-5 pb-5" noValidate>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Kind" htmlFor="pv-kind">
              <SimpleSelect
                id="pv-kind"
                value={kind}
                onValueChange={(v) => setKind(v as ProviderKind)}
                options={PROVIDER_KINDS.map((k) => ({ value: k, label: PROVIDER_KIND[k].label }))}
              />
            </Field>
            <Field label="Name" htmlFor="pv-name" hint="Short, unique in the organisation">
              <Input
                id="pv-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={kind}
              />
            </Field>
            <Field
              label="Model"
              htmlFor="pv-model"
              hint={spec.model ? `Default: ${spec.model}` : "Required"}
            >
              <Input
                id="pv-model"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder={spec.model}
              />
            </Field>
            {(spec.needsUrl || kind !== "mock") && (
              <Field
                label="Base URL"
                htmlFor="pv-url"
                hint={spec.needsUrl ? "Required" : "Optional: the provider's default is used"}
              >
                <Input
                  id="pv-url"
                  type="url"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder={kind === "ollama" ? "http://localhost:11434" : "https://"}
                />
              </Field>
            )}
            {kind !== "mock" && (
              <Field
                label="API key"
                htmlFor="pv-key"
                hint={spec.needsKey ? "Sealed before storage" : "Optional"}
              >
                <Input
                  id="pv-key"
                  type="password"
                  autoComplete="off"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                />
              </Field>
            )}
          </div>
          {error && <FieldError>{error}</FieldError>}
          <GatedButton
            need="manageProviders"
            type="submit"
            disabled={create.isPending}
            data-qa="add-provider"
          >
            <PlusIcon />
            {create.isPending ? "Adding..." : "Add provider"}
          </GatedButton>
        </form>
      </Surface>
      <ConfirmDialog
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={`Remove ${removing?.name ?? "this provider"}?`}
        description="Its sealed key is deleted. Existing investigation reports stay."
        confirmLabel="Remove provider"
        pending={del.isPending}
        onConfirm={() =>
          removing &&
          del.mutate(removing.id, {
            onSuccess: () => {
              toast.success("Provider removed.");
              setRemoving(null);
            },
            onError: (err) => toast.error(errorMessage(err)),
          })
        }
      />
    </div>
  );
}
