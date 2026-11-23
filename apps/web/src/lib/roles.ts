/**
 * Dashboard roles, lowest to highest. Mirrors the API's ROLE_RANK (auth/dependencies.py):
 * viewers read everything and run AI investigations, admins also change projects, API
 * keys, alert rules, AI providers and error statuses, owners also manage people. The API enforces every rule; the
 * UI keeps gated controls visible but disabled, with the reason, for roles that cannot use
 * them.
 */
export const ROLES = ["viewer", "admin", "owner"] as const;
export type Role = (typeof ROLES)[number];

const LABEL: Record<Role, string> = {
  viewer: "Viewer",
  admin: "Admin",
  owner: "Owner",
};

const DESCRIPTION: Record<Role, string> = {
  viewer: "Reads every log, error group, service and alert, and runs AI investigations.",
  admin:
    "Everything a viewer can do, plus projects, API keys, redaction, alerts, AI providers and resolving errors.",
  owner: "Everything an admin can do, plus inviting people and changing their roles.",
};

export function isRole(value: unknown): value is Role {
  return typeof value === "string" && (ROLES as readonly string[]).includes(value);
}

export function roleRank(role: string | null | undefined): number {
  return isRole(role) ? ROLES.indexOf(role) : -1;
}

/** Whether `role` is at least `required`. Unknown or missing roles can do nothing. */
export function atLeast(role: string | null | undefined, required: Role): boolean {
  const r = roleRank(role);
  return r >= 0 && r >= roleRank(required);
}

export function roleLabel(role: string | null | undefined): string {
  return isRole(role) ? LABEL[role] : "Unknown";
}

export function roleDescription(role: string | null | undefined): string {
  return isRole(role) ? DESCRIPTION[role] : "";
}

/**
 * What each gated action needs, in one place so screens and tests agree. Each entry
 * matches the dependency on the API route (Admin or Owner in the routers).
 */
export const CAN = {
  createProject: "admin",
  updateProject: "admin",
  manageKeys: "admin",
  manageAlerts: "admin",
  manageProviders: "admin",
  triageErrors: "admin",
  investigate: "viewer",
  updateOrg: "admin",
  manageUsers: "owner",
} as const satisfies Record<string, Role>;

export type Capability = keyof typeof CAN;

export function can(role: string | null | undefined, capability: Capability): boolean {
  return atLeast(role, CAN[capability]);
}

/** The sentence a disabled control shows when the role is too low. */
export function needsRoleText(capability: Capability): string {
  return `Needs the ${roleLabel(CAN[capability]).toLowerCase()} role or higher.`;
}
