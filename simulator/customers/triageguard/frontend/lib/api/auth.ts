/**
 * Auth endpoints — `/api/auth/login`, `/api/auth/logout`, `/api/auth/me`.
 *
 * The session cookie is HTTP-only; we never read it. `me()` is the canonical
 * "am I signed in?" probe.
 */

import { request, ApiError } from "./client";

export interface MeResponse {
  signed_in_as: string;
}

/**
 * Exchange a passkey for a session cookie.
 *
 * Throws `ApiError` (status 401) on a wrong passkey. On success the backend
 * sets `triageguard_session` and returns 204 — there is no body.
 */
export async function login(passkey: string): Promise<void> {
  await request<null>("/api/auth/login", {
    method: "POST",
    body: { passkey },
  });
}

/** Clear the session cookie + revoke server-side state. Always 204. */
export async function logout(): Promise<void> {
  await request<null>("/api/auth/logout", {
    method: "POST",
  });
}

/**
 * Return the signed-in user's display name, or `null` if no valid session.
 *
 * Wraps the `/api/auth/me` 401 in a `null` so callers (the auth provider)
 * can branch on a simple value instead of catching errors.
 */
export async function me(): Promise<string | null> {
  try {
    const res = await request<MeResponse>("/api/auth/me");
    return res.signed_in_as;
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      return null;
    }
    throw err;
  }
}
