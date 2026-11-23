import { cn } from "@/lib/cn";

/** The LogMind mark: three log lines and a highlighted finding, in the accent colour. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden className={cn("size-7", className)}>
      <rect width="32" height="32" rx="9" className="fill-primary" />
      <path
        d="M8.5 10.5h15M8.5 16h10M8.5 21.5h13"
        className="stroke-primary-foreground"
        strokeWidth="2.2"
        strokeLinecap="round"
        fill="none"
      />
      <circle cx="23" cy="16" r="2.4" fill="#fde68a" />
    </svg>
  );
}

export function BrandLogo({
  collapsed = false,
  className,
}: {
  collapsed?: boolean;
  className?: string;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <BrandMark />
      {!collapsed && <span className="text-[15px] font-semibold tracking-[-0.02em]">LogMind</span>}
    </span>
  );
}
