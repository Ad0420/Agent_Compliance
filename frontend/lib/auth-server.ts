import "server-only";
import { auth, currentUser } from "@clerk/nextjs/server";

/**
 * Get a backend-bound Clerk session token for the current request.
 *
 * Returns `null` if the request is unauthenticated. Intended for server
 * components and route handlers that need to call Vera's
 * `/v1/dashboard/*` endpoints on behalf of the signed-in user.
 *
 * Note: this lives in `auth-server.ts` (not `auth.ts`) because
 * `lib/auth.ts` houses the existing client-side localStorage helpers
 * for the legacy API-key flow. Mixing `@clerk/nextjs/server` imports
 * into a module that is also imported by client components would break
 * the build. Once Phase 3 (E4) finishes migrating the dashboard off the
 * legacy API-key flow, the two files can be merged.
 *
 * Used by `lib/api-server.ts#fetchFromVera` to authenticate calls to
 * `/v1/dashboard/*` (Workstream E4: API-key issuance dashboard).
 */
export async function getClerkBackendToken(): Promise<string | null> {
  const session = await auth();
  if (!session.userId) return null;
  return await session.getToken();
}

export interface ClerkSessionSummary {
  userId: string;
  orgId: string | null;
  orgRole: string | null;
  email: string | null;
}

/**
 * Get a lightweight summary of the active Clerk session for server
 * components. Returns `null` when there is no signed-in user.
 *
 * `orgRole` is Clerk's raw role string (e.g. `org:admin`, `org:member`) —
 * the backend webhook handler translates these to backend roles. For UI
 * gating, prefer the role from the actual `/v1/dashboard/api-keys` call:
 * the backend is the source of truth and any drift between Clerk roles
 * and backend memberships will surface as a 403 from the API.
 */
export async function getClerkSessionSummary(): Promise<ClerkSessionSummary | null> {
  const session = await auth();
  if (!session.userId) return null;
  const user = await currentUser();
  const primaryEmail =
    user?.emailAddresses?.find((e) => e.id === user?.primaryEmailAddressId)
      ?.emailAddress ??
    user?.emailAddresses?.[0]?.emailAddress ??
    null;
  return {
    userId: session.userId,
    orgId: session.orgId ?? null,
    orgRole: session.orgRole ?? null,
    email: primaryEmail,
  };
}
