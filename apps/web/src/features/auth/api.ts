"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, appFetch, unwrap } from "@/lib/api/client";
import type { User } from "@/lib/api/types";
import { qk, STALE } from "@/lib/query-keys";
import { can, type Capability } from "@/lib/roles";

/** The signed-in user, through the proxy (`GET /api/v1/auth/me`). */
export function useMe() {
  return useQuery({
    queryKey: qk.me,
    queryFn: (): Promise<User> => unwrap(api.GET("/api/v1/auth/me")),
    staleTime: STALE.static,
    retry: false,
  });
}

/**
 * What the signed-in person may do. While the user loads, nothing privileged is allowed.
 * The API enforces the same rules; this only disables controls and explains why.
 */
export function usePermissions(): {
  user: User | undefined;
  role: string | undefined;
  can: (c: Capability) => boolean;
} {
  const { data } = useMe();
  const role = data?.role;
  return { user: data, role, can: (c: Capability) => can(role, c) };
}

interface SignedIn {
  user: User;
}

function useSignedIn() {
  const client = useQueryClient();
  return (session: SignedIn) => {
    client.clear();
    client.setQueryData<User>(qk.me, session.user);
  };
}

/**
 * Sign in through the session bridge: /api/session calls the API's /auth/login on the
 * server, stores the returned token in the httpOnly `lm_session` cookie and answers with
 * the user only. The token never reaches this page's JavaScript.
 */
export function useLogin() {
  const signedIn = useSignedIn();
  return useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      appFetch<SignedIn>("/api/session", {
        method: "POST",
        body: JSON.stringify({ action: "login", ...body }),
      }),
    onSuccess: signedIn,
  });
}

export function useSignup() {
  const signedIn = useSignedIn();
  return useMutation({
    mutationFn: (body: { org_name: string; name: string; email: string; password: string }) =>
      appFetch<SignedIn>("/api/session", {
        method: "POST",
        body: JSON.stringify({ action: "signup", ...body }),
      }),
    onSuccess: signedIn,
  });
}

/**
 * Sign out: clears the session cookie. The API has no logout or revocation endpoint, so
 * the token itself stays valid until it expires; it is simply no longer held anywhere.
 */
export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => appFetch<{ ok: true }>("/api/session", { method: "DELETE" }),
    onSettled: () => client.clear(),
  });
}
