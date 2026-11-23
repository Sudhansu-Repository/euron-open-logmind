"use client";

import {
  ArrowRightIcon,
  EyeIcon,
  EyeOffIcon,
  BugIcon,
  ScrollTextIcon,
  ShieldCheckIcon,
  SparklesIcon,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { BrandLogo, BrandMark } from "@/components/brand";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FieldError, FieldHint, Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/api/errors";
import { safeNext } from "@/lib/auth-redirect";
import { passwordMessage } from "@/lib/password";

import { useLogin, useSignup } from "../api";

const PITCH = [
  {
    icon: ScrollTextIcon,
    title: "Every line, searchable in seconds",
    body: "HTTP, Python and Node SDKs, or any OpenTelemetry exporter, into ClickHouse.",
  },
  {
    icon: BugIcon,
    title: "Errors grouped, not repeated",
    body: "Stack traces fingerprinted, so one bug is one row with its first and last time.",
  },
  {
    icon: SparklesIcon,
    title: "Root causes that cite the logs",
    body: "Every claim in an AI report points at a real stored line you can open.",
  },
  {
    icon: ShieldCheckIcon,
    title: "Secrets never stored",
    body: "PII and credentials are redacted at ingestion, before anything is written.",
  },
];

function PasswordInput({
  id,
  value,
  onChange,
  autoComplete,
  invalid,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  autoComplete: string;
  invalid?: boolean;
}) {
  const [show, setShow] = React.useState(false);
  return (
    <div className="relative">
      <Input
        id={id}
        type={show ? "text" : "password"}
        autoComplete={autoComplete}
        className="h-10 pr-10"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={invalid || undefined}
      />
      <button
        type="button"
        onClick={() => setShow((s) => !s)}
        aria-label={show ? "Hide password" : "Show password"}
        className="absolute top-1/2 right-2 flex size-7 -translate-y-1/2 items-center justify-center rounded-md text-subtle hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
      >
        {show ? <EyeOffIcon className="size-4" /> : <EyeIcon className="size-4" />}
      </button>
    </div>
  );
}

export function AuthScreen({ mode }: { mode: "login" | "signup" }) {
  const router = useRouter();
  const params = useSearchParams();
  const login = useLogin();
  const signup = useSignup();
  const [org, setOrg] = React.useState("");
  const [name, setName] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const expired = params.get("reason") === "expired";
  const pending = login.isPending || signup.isPending;
  const next = params.get("next");

  function welcome(fullName: string, dest: string, isNew: boolean) {
    const first = fullName.split(" ")[0] ?? "";
    toast.success(
      isNew
        ? `Welcome, ${first}. Create a project to get an API key for the SDK.`
        : `Welcome back, ${first}.`
    );
    router.replace(dest);
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const onError = (err: unknown) => setError(errorMessage(err));
    if (mode === "login") {
      if (!email.trim() || !password) return setError("Enter your email and password.");
      setError(null);
      login.mutate(
        { email: email.trim(), password },
        { onSuccess: (s) => welcome(s.user.name, safeNext(next), false), onError }
      );
      return;
    }
    if (!org.trim() || !name.trim() || !email.trim())
      return setError("Enter your organization, your name, your email and a password.");
    const weak = passwordMessage(password);
    if (weak) return setError(weak);
    setError(null);
    signup.mutate(
      { org_name: org.trim(), name: name.trim(), email: email.trim(), password },
      { onSuccess: (s) => welcome(s.user.name, "/settings?tab=projects", true), onError }
    );
  }

  const title = mode === "signup" ? "Create your organization" : "Sign in to LogMind";
  const subtitle =
    mode === "signup"
      ? "Creates your organization and makes you its owner. Next: a project, an API key, and your first log line."
      : "Search your logs, see errors grouped, and ask why something broke.";

  return (
    <div className="grid min-h-dvh bg-background lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
      <div className="relative flex flex-col px-4 py-6 sm:px-10">
        <div className="flex items-center justify-between">
          <BrandLogo />
          <ThemeToggle />
        </div>
        <div className="flex flex-1 items-center justify-center py-10">
          <div className="w-full max-w-[380px]">
            <h1 className="text-[26px] leading-tight font-semibold tracking-[-0.025em]">{title}</h1>
            <p className="mt-1.5 text-[13.5px] leading-relaxed text-muted-foreground">{subtitle}</p>
            {expired && mode === "login" && (
              <div
                role="status"
                className="mt-5 rounded-lg bg-warning-soft px-3.5 py-2.5 text-[13px] text-warning"
              >
                Your session expired. Sign in again to pick up where you left off.
              </div>
            )}
            <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
              {mode === "signup" && (
                <>
                  <div className="space-y-1.5">
                    <Label htmlFor="org">Organization</Label>
                    <Input
                      id="org"
                      autoComplete="organization"
                      autoFocus
                      className="h-10"
                      placeholder="Acme Inc."
                      value={org}
                      onChange={(e) => setOrg(e.target.value)}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="name">Your name</Label>
                    <Input
                      id="name"
                      autoComplete="name"
                      className="h-10"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                    />
                  </div>
                </>
              )}
              <div className="space-y-1.5">
                <Label htmlFor="email">Work email</Label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="username"
                  autoFocus={mode === "login"}
                  placeholder="you@company.com"
                  className="h-10"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  aria-invalid={!!error || undefined}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="password">Password</Label>
                <PasswordInput
                  id="password"
                  value={password}
                  onChange={setPassword}
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  invalid={!!error}
                />
                {mode === "signup" && (
                  <FieldHint>
                    At least 10 characters, with upper and lower case letters and a digit.
                  </FieldHint>
                )}
              </div>
              {error && <FieldError>{error}</FieldError>}
              <Button type="submit" size="lg" className="w-full" disabled={pending}>
                {pending
                  ? mode === "login"
                    ? "Signing in..."
                    : "Setting up..."
                  : mode === "signup"
                    ? "Create organization"
                    : "Sign in"}
                {!pending && <ArrowRightIcon />}
              </Button>
            </form>
            <p className="mt-6 text-xs leading-relaxed text-muted-foreground">
              {mode === "login" ? (
                <>
                  New to LogMind?{" "}
                  <Link
                    href="/signup"
                    className="font-medium text-primary underline-offset-2 hover:underline"
                  >
                    Create an organization
                  </Link>
                  . Forgot your password? Ask an owner of your organization to reset it.
                </>
              ) : (
                <>
                  Already have an account?{" "}
                  <Link
                    href={next ? `/login?next=${encodeURIComponent(next)}` : "/login"}
                    className="font-medium text-primary underline-offset-2 hover:underline"
                  >
                    Sign in
                  </Link>
                  .
                </>
              )}
            </p>
          </div>
        </div>
        <p className="text-[11.5px] text-faint">
          Self-hosted. Your logs and investigations stay on your infrastructure.
        </p>
      </div>

      <aside className="relative hidden overflow-hidden bg-[var(--panel)] p-10 text-white lg:flex lg:flex-col lg:justify-between">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-90"
          style={{
            background:
              "radial-gradient(60% 50% at 80% 10%, var(--panel-glow), transparent 70%), radial-gradient(50% 45% at 10% 90%, var(--panel-glow-2), transparent 70%)",
          }}
        />
        <div className="relative flex items-center gap-2 text-[13px] font-medium text-white/70">
          <BrandMark className="size-6" />
          Open-source log intelligence
        </div>
        <div className="relative max-w-lg">
          <h2 className="text-[34px] leading-[1.12] font-semibold tracking-[-0.03em]">
            Ask your logs why it broke.
            <br />
            <span className="text-[var(--panel-accent)]">Get an answer that cites the lines.</span>
          </h2>
          <p className="mt-3 text-[14.5px] leading-relaxed text-white/65">
            LogMind collects, searches and groups your logs, then investigates incidents with
            evidence it pulls from them: a deploy, a pool running dry, the first timeout.
          </p>
          <div
            aria-hidden
            className="mt-8 space-y-2 rounded-2xl bg-white/[0.06] p-4 font-mono text-[12px] shadow-[0_20px_60px_rgba(0,0,0,0.35)] ring-1 ring-white/10"
          >
            {[
              { ref: "E1", text: "payments  deploy started: v2.14.0", color: "var(--chart-1)" },
              {
                ref: "E2",
                text: "payments  db connection pool exhausted x48",
                color: "var(--level-warn)",
              },
              {
                ref: "E3",
                text: "checkout  PaymentGatewayTimeout x212",
                color: "var(--level-error)",
              },
            ].map((r) => (
              <div key={r.ref} className="flex items-center gap-3">
                <span className="w-7 font-semibold" style={{ color: r.color }}>
                  {r.ref}
                </span>
                <span className="truncate text-white/75">{r.text}</span>
              </div>
            ))}
            <div className="pt-2 text-[11.5px] text-white/55">
              Root cause cites E1 E2 E3, all 3 verified
            </div>
          </div>
          <ul className="mt-8 grid gap-5 sm:grid-cols-2">
            {PITCH.map((p) => (
              <li key={p.title} className="flex gap-3">
                <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-white/10 text-[var(--panel-accent)]">
                  <p.icon className="size-4" />
                </span>
                <div>
                  <div className="text-[13px] font-semibold">{p.title}</div>
                  <div className="mt-0.5 text-[12.5px] leading-relaxed text-white/55">{p.body}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <div className="relative text-[11.5px] text-white/40">
          MIT licensed. Part of the Euron open-source initiative.
        </div>
      </aside>
    </div>
  );
}
