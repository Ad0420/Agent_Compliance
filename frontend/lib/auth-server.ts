import "server-only";
import { auth } from "@clerk/nextjs/server";

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
 * Phase 3's API-key issuance UI (E4) will consume this helper to mint
 * org-scoped API keys for newly signed-up users.
 */
export async function getClerkBackendToken(): Promise<string | null> {
  const session = await auth();
  if (!session.userId) return null;
  return await session.getToken();
}
