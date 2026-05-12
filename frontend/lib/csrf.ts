/**
 * Origin / Referer allow-list for mutating dashboard API route handlers.
 *
 * Why this exists (post-PR #164 audit finding CRITICAL #4):
 *   Next.js route handlers under `/api/dashboard/*` accept POST / DELETE
 *   from any cross-origin caller. Clerk session cookies are `SameSite=Lax`
 *   (the default), which blocks the classic top-level navigation CSRF —
 *   but a same-site XSS (e.g. compromised third-party script on the same
 *   apex domain) can still mint and revoke API keys. The Origin / Referer
 *   header allow-list defends against both.
 *
 *   We deliberately do NOT use a token-based CSRF (double-submit cookie or
 *   synchronizer token). For our deployment shape — a small set of
 *   first-party origins, Clerk session cookies, no embeddable forms — the
 *   header-allow-list pattern is simpler and has the same effect.
 *
 * Allow-list sources:
 *   - `NEXT_PUBLIC_APP_URL`              — the deployed app origin (set in
 *                                          Vercel env). Mandatory in prod.
 *   - `NEXT_PUBLIC_DASHBOARD_ORIGINS`    — optional comma-separated list of
 *                                          additional origins (staging, etc).
 *   - `http://localhost:3000`            — always allowed in development.
 *
 * On any GET handler, callers don't need to call this — GETs are idempotent
 * reads. We export the helper so future routes can opt in.
 */

const DEV_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"];

function getAllowedOrigins(): string[] {
  const list: string[] = [];

  const appUrl = process.env.NEXT_PUBLIC_APP_URL?.trim();
  if (appUrl) {
    list.push(appUrl.replace(/\/+$/, ""));
  }

  const extra = process.env.NEXT_PUBLIC_DASHBOARD_ORIGINS?.trim();
  if (extra) {
    for (const raw of extra.split(",")) {
      const cleaned = raw.trim().replace(/\/+$/, "");
      if (cleaned) list.push(cleaned);
    }
  }

  // In development we always accept localhost. In prod, NEXT_PUBLIC_APP_URL
  // SHOULD be set; if it isn't we still permit localhost so the dashboard
  // doesn't go dark — the loud warning in `middleware.ts` already flags
  // missing env vars on every request.
  if (process.env.NODE_ENV !== "production") {
    list.push(...DEV_ORIGINS);
  } else if (list.length === 0) {
    // Prod with no allow-list configured — fail loud once per process,
    // and refuse all requests (return empty list). Better to break than
    // silently accept anything.
    if (typeof console !== "undefined") {
      console.warn(
        "[vera] No NEXT_PUBLIC_APP_URL or NEXT_PUBLIC_DASHBOARD_ORIGINS " +
          "configured in production — dashboard mutating routes will reject " +
          "every request with 403 Forbidden.",
      );
    }
  }

  return list;
}

/**
 * Returns ``true`` iff the request's Origin (preferred) or Referer header
 * matches one of the allowed origins. Missing both headers → reject.
 *
 * Match is `startsWith(origin)` on the trimmed-trailing-slash variant — we
 * don't try to parse URLs to allow paths like
 * ``https://app.example.com/somewhere`` (a Referer carries the full URL).
 */
export function isAllowedOrigin(req: Request): boolean {
  const headerOrigin = req.headers.get("origin");
  const headerReferer = req.headers.get("referer");
  const candidate = headerOrigin ?? headerReferer;
  if (!candidate) {
    // No Origin AND no Referer → we cannot prove this is a same-origin
    // request. Reject. Browsers attach Origin on POST/DELETE for fetch()
    // calls; only same-origin GETs are likely to omit it.
    return false;
  }
  const allowed = getAllowedOrigins();
  if (allowed.length === 0) {
    return false;
  }
  return allowed.some((origin) => candidate.startsWith(origin));
}

/**
 * Convenience guard for route handlers. Returns the Response to send if
 * the request is rejected, or ``null`` if it should proceed.
 *
 * Usage::
 *
 *     export async function POST(req: Request) {
 *       const forbidden = csrfGuard(req);
 *       if (forbidden) return forbidden;
 *       // ... rest of handler
 *     }
 */
export function csrfGuard(req: Request): Response | null {
  if (!isAllowedOrigin(req)) {
    return new Response(
      JSON.stringify({ error: "Forbidden: origin not allowed" }),
      {
        status: 403,
        headers: { "content-type": "application/json" },
      },
    );
  }
  return null;
}
