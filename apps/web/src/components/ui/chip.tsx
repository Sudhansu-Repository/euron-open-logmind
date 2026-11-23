import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/cn";

/** Small status pill. Tone comes from lib/labels and lib/error-categories so a state looks the same everywhere. */
const chipVariants = cva(
  "inline-flex h-5 shrink-0 items-center gap-1 rounded-full px-2 text-[11px] leading-none font-semibold tracking-[0.01em] whitespace-nowrap [&_svg]:size-3",
  {
    variants: {
      tone: {
        success: "bg-success-soft text-success",
        info: "bg-info-soft text-info",
        primary: "bg-primary-soft text-primary",
        warning: "bg-warning-soft text-warning",
        danger: "bg-danger-soft text-danger",
        neutral: "bg-neutral-soft text-muted-foreground",
        orange: "bg-orange-soft text-orange",
        fuchsia: "bg-fuchsia-soft text-fuchsia",
        cyan: "bg-cyan-soft text-cyan",
      },
    },
    defaultVariants: { tone: "neutral" },
  }
);

function Chip({
  className,
  tone,
  dot = false,
  children,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof chipVariants> & { dot?: boolean }) {
  return (
    <span data-slot="chip" className={cn(chipVariants({ tone }), className)} {...props}>
      {dot && <span aria-hidden className="size-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

export { Chip, chipVariants };
