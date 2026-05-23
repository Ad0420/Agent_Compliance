/**
 * Browser-side Clerk session token accessor for the dashboard's API client.
 *
 * `lib/api-client.ts` is plain TypeScript (not a React component), so it can't
 * call `useAuth().getToken()` from `@clerk/nextjs`. Instead we read the active
 * session off the `window.Clerk` global the Clerk SDK populates at load time.
 *
 * This is the documented browser-side pattern from Clerk's docs. Tokens are
 * short-lived (~60s) so the runtime cost of fetching one per request is
 * acceptable; Clerk's SDK caches and refreshes them internally.
 *
 * Returns `null` if Clerk hasn't initialized yet or there's no active session.
 * Callers that get `null` should treat it as unauthenticated; api-client's
 * 401 handler will bounce the user back to `/login`.
 */

interface ClerkSession {
  getToken: () => Promise<string | null>;
}

interface ClerkGlobal {
  session?: ClerkSession | null;
}

declare global {
  interface Window {
    Clerk?: ClerkGlobal;
  }
}

export async function getClerkToken(): Promise<string | null> {
  if (typeof window === "undefined") return null;
  const session = window.Clerk?.session;
  if (!session) return null;
  try {
    return await session.getToken();
  } catch {
    return null;
  }
}
