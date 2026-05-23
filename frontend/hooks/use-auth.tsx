"use client";

import { createContext, useContext, useCallback, type ReactNode } from "react";
import { useClerk, useUser, useOrganization } from "@clerk/nextjs";
import { useQuery } from "@tanstack/react-query";
import { getOrganization } from "@/lib/api-client";
import type { Organization } from "@/lib/api-types";

/**
 * Dashboard auth state, sourced from Clerk (E4 cutover).
 *
 * What changed in E4:
 *   - The legacy localStorage `apiKey` is gone. Humans sign in with Clerk;
 *     the SDK still uses `al_*` Bearer keys, but those keys are minted from
 *     /api-keys, not pasted into a login form.
 *   - `organization` is fetched from the backend with the active Clerk
 *     session attached by `lib/api-client.ts`. The Clerk org id is the join
 *     key on the backend side (`OrgMembership.clerk_org_id`).
 *   - `isAdmin` is derived from the Clerk org role. The backend is still the
 *     source of truth for write/admin actions — UI gating off this is
 *     "keep honest" only.
 */
interface AuthState {
  organization: Organization | null;
  isAdmin: boolean;
  isLoading: boolean;
  isSignedIn: boolean;
}

interface AuthContextValue extends AuthState {
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const { signOut } = useClerk();
  const { isLoaded: userLoaded, isSignedIn } = useUser();
  const { organization: clerkOrg, membership } = useOrganization();

  // Fetch the backend Organization row whenever there's an active Clerk
  // session with an active org context. React Query handles caching across
  // route changes so the dashboard doesn't re-hit /v1/organizations/me on
  // every navigation.
  const { data: organization, isPending: orgPending } = useQuery({
    queryKey: ["organization", clerkOrg?.id],
    queryFn: getOrganization,
    enabled: Boolean(isSignedIn && clerkOrg?.id),
    staleTime: 60_000,
  });

  // Clerk org role values look like "org:admin", "admin", "org:member", etc.
  // Treat any "admin" variant as admin for UI gating; everything else is
  // non-admin. Backend still 403s on write/admin if the membership row
  // disagrees, so this is keep-honest, not load-bearing.
  const role = membership?.role ?? "";
  const isAdmin = role === "org:admin" || role === "admin";

  const logout = useCallback(async () => {
    await signOut({ redirectUrl: "/login" });
  }, [signOut]);

  const isLoading = !userLoaded || (Boolean(isSignedIn) && orgPending);

  const value: AuthContextValue = {
    organization: organization ?? null,
    isAdmin,
    isLoading,
    isSignedIn: Boolean(isSignedIn),
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
