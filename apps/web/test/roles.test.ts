import { describe, expect, it } from "vitest";

import {
  atLeast,
  can,
  CAN,
  isRole,
  needsRoleText,
  roleDescription,
  roleLabel,
  roleRank,
  ROLES,
} from "@/lib/roles";

describe("roles", () => {
  it("ranks viewer < admin < owner like the API's ROLE_RANK", () => {
    expect(ROLES).toEqual(["viewer", "admin", "owner"]);
    expect(roleRank("viewer")).toBe(0);
    expect(roleRank("admin")).toBe(1);
    expect(roleRank("owner")).toBe(2);
    expect(roleRank("root")).toBe(-1);
  });

  it("atLeast respects the order and refuses unknown roles", () => {
    expect(atLeast("owner", "admin")).toBe(true);
    expect(atLeast("admin", "admin")).toBe(true);
    expect(atLeast("viewer", "admin")).toBe(false);
    expect(atLeast(undefined, "viewer")).toBe(false);
    expect(atLeast("superuser", "viewer")).toBe(false);
  });

  it("gates every admin action for viewers", () => {
    const adminCaps = (Object.keys(CAN) as (keyof typeof CAN)[]).filter((c) => CAN[c] === "admin");
    expect(adminCaps.length).toBeGreaterThan(5);
    for (const c of adminCaps) {
      expect(can("viewer", c)).toBe(false);
      expect(can("admin", c)).toBe(true);
      expect(can("owner", c)).toBe(true);
    }
  });

  it("only owners manage users, matching the Owner dependency on /api/v1/users", () => {
    expect(can("admin", "manageUsers")).toBe(false);
    expect(can("owner", "manageUsers")).toBe(true);
  });

  it("providers and keys need admin, matching the routers", () => {
    expect(CAN.manageProviders).toBe("admin");
    expect(CAN.investigate).toBe("viewer");
    expect(CAN.manageKeys).toBe("admin");
    expect(CAN.updateOrg).toBe("admin");
  });

  it("explains a disabled control", () => {
    expect(needsRoleText("createProject")).toBe("Needs the admin role or higher.");
    expect(needsRoleText("manageUsers")).toBe("Needs the owner role or higher.");
  });

  it("labels and describes roles", () => {
    expect(roleLabel("owner")).toBe("Owner");
    expect(roleLabel("x")).toBe("Unknown");
    expect(roleDescription("viewer")).toMatch(/runs AI investigations/);
    expect(isRole("admin")).toBe(true);
    expect(isRole(3)).toBe(false);
  });
});
