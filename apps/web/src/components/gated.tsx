"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useCan } from "@/hooks/use-can";
import type { Capability } from "@/lib/roles";

type ButtonProps = React.ComponentProps<typeof Button>;

/**
 * A button that needs a capability. When the person's role is too low it stays visible
 * but disabled, with a tooltip naming the role it needs (the API refuses it anyway).
 * `reason` disables it for another reason the screen explains.
 */
export function GatedButton({
  need,
  reason,
  ...props
}: ButtonProps & { need: Capability; reason?: string | null }) {
  const { reason: roleReason } = useCan(need);
  const why = roleReason || reason || null;
  if (!why) return <Button {...props} />;
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <span
            tabIndex={0}
            className="inline-flex rounded-lg focus-visible:outline-2 focus-visible:outline-ring"
          />
        }
      >
        <Button {...props} disabled aria-disabled onClick={undefined} />
      </TooltipTrigger>
      <TooltipContent>{why}</TooltipContent>
    </Tooltip>
  );
}

/** A switch with the same rule: visible, disabled with the reason, for roles that cannot change it. */
export function GatedSwitch({
  need,
  ...props
}: React.ComponentProps<typeof Switch> & { need: Capability }) {
  const { reason } = useCan(need);
  if (!reason) return <Switch {...props} />;
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
        <Switch {...props} disabled />
      </TooltipTrigger>
      <TooltipContent>{reason}</TooltipContent>
    </Tooltip>
  );
}

/** An inline sentence under a read-only form, saying why it cannot be edited. */
export function RoleNote({ need }: { need: Capability }) {
  const { reason } = useCan(need);
  if (!reason) return null;
  return (
    <p className="rounded-lg bg-muted px-3 py-2 text-[12.5px] text-muted-foreground">
      Read only for your role. {reason}
    </p>
  );
}
