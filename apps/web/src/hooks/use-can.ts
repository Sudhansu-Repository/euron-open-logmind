"use client";

import { usePermissions } from "@/features/auth/api";
import { needsRoleText, type Capability } from "@/lib/roles";

/**
 * Whether the signed-in person may use a gated control, and the sentence to show when not.
 * Controls stay visible and disabled with this reason: never hidden.
 */
export function useCan(capability: Capability): { allowed: boolean; reason: string | null } {
  const { can, user } = usePermissions();
  if (!user) return { allowed: false, reason: "Loading your role..." };
  const allowed = can(capability);
  return { allowed, reason: allowed ? null : needsRoleText(capability) };
}
