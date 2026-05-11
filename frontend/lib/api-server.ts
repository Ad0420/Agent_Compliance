/**
 * Server-side helper for calling Vera's Clerk-authenticated dashboard API.
 *
 * Phase 3 / Workstream E4. Used by server components under
 * `app/(dashboard)/api-keys/*` to call `/v1/dashboard/*` with the current
 * Clerk session's backend-bound token.
 *
 * This module is `server-only` — it imports `@clerk/nextjs/server`'s `auth()`
 * via `getClerkBackendToken`, which must never be bundled into a client
 * component. The `import "server-only"` line is the guard.
 */
import "server-only";

import { getClerkBackendToken } from "./auth-server";

const API_BASE =
  process.env.VERA_API_URL ??
  process.env.NEXT_PUBLIC_API_BASE ??
  "http://localhost:8000";

export class VeraApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, body: unknown, message: string) {
    super(message);
    this.name = "VeraApiError";
    this.status = status;
    this.body = body;
  }
}

/**
 * Low-level fetch wrapper. Adds the Clerk bearer token and parses JSON.
 *
 * Throws `VeraApiError` (with status + body) on non-2xx responses so server
 * components can branch on error.status (401, 403, 404, 5xx). The thrown
 * `body` is the JSON-decoded response body when available, otherwise the
 * raw text — useful for surfacing FastAPI's `detail` to the user.
 */
export async function fetchFromVera<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const token = await getClerkBackendToken();
  if (!token) {
    throw new VeraApiError(401, null, "Not authenticated");
  }

  // Pass `cache: "no-store"` by default so dashboard pages reflect the most
  // recent state. Callers can opt back into caching via `init.cache`.
  const res = await fetch(`${API_BASE}${path}`, {
    cache: "no-store",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
      Authorization: `Bearer ${token}`,
    },
  });

  // Robust body parse: try JSON, fall back to text. Empty 204s are common
  // for DELETE-style routes.
  let body: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }

  if (!res.ok) {
    throw new VeraApiError(
      res.status,
      body,
      `Vera API ${res.status} on ${path}`,
    );
  }
  return body as T;
}

// ── Dashboard API-key helpers ────────────────────────────────────────────────
// Thin typed wrappers around `/v1/dashboard/api-keys`. Keep these here rather
// than in a client `api-client.ts` because they require the Clerk session
// token, which is only available server-side.

export interface DashboardApiKey {
  id: string;
  name: string;
  key_prefix: string;
  permissions: string[];
  created_at: string;
  revoked_at: string | null;
  expires_at: string | null;
  is_active: boolean;
}

export interface DashboardApiKeyCreated extends DashboardApiKey {
  raw_key: string;
}

export interface DashboardApiKeyCreateInput {
  name: string;
  permissions?: string[];
  expires_at?: string | null;
}

export function listDashboardApiKeys(): Promise<DashboardApiKey[]> {
  return fetchFromVera<DashboardApiKey[]>("/v1/dashboard/api-keys");
}

export function createDashboardApiKey(
  input: DashboardApiKeyCreateInput,
): Promise<DashboardApiKeyCreated> {
  return fetchFromVera<DashboardApiKeyCreated>("/v1/dashboard/api-keys", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function revokeDashboardApiKey(keyId: string): Promise<unknown> {
  return fetchFromVera(`/v1/dashboard/api-keys/${encodeURIComponent(keyId)}`, {
    method: "DELETE",
  });
}
