/**
 * Session endpoints — create / fetch / list.
 *
 * The shapes match `backend/contract.md` verbatim; the request bodies for
 * `createSession` are validated by the discriminated `StartSessionInput`
 * union in `./types`.
 */

import { request } from "./client";
import type {
  ListSessionsOptions,
  ListSessionsResponse,
  SessionSnapshot,
  StartSessionInput,
  StartSessionResponse,
} from "./types";

/** Kick off a triage session workflow. Returns the new session id. */
export async function createSession(
  input: StartSessionInput,
): Promise<StartSessionResponse> {
  return request<StartSessionResponse>("/api/sessions", {
    method: "POST",
    body: input,
  });
}

/** Snapshot of a session's current state. Throws on 404. */
export async function getSession(id: string): Promise<SessionSnapshot> {
  return request<SessionSnapshot>(
    `/api/sessions/${encodeURIComponent(id)}`,
  );
}

/** List sessions newest-first; `limit` is clamped server-side to [1, 100]. */
export async function listSessions(
  opts: ListSessionsOptions = {},
): Promise<ListSessionsResponse> {
  return request<ListSessionsResponse>("/api/sessions", {
    query: {
      limit: opts.limit,
      offset: opts.offset,
    },
  });
}
