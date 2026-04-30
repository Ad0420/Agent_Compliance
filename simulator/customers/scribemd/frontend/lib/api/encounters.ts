/**
 * Encounter endpoints — create / fetch / list.
 *
 * The shapes match `backend/contract.md` verbatim; the request bodies for
 * `createEncounter` are validated by the discriminated `StartEncounterInput`
 * union in `./types`.
 */

import { request } from "./client";
import type {
  EncounterSnapshot,
  ListEncountersOptions,
  ListEncountersResponse,
  StartEncounterInput,
  StartEncounterResponse,
} from "./types";

/** Kick off an encounter workflow. Returns the new encounter id. */
export async function createEncounter(
  input: StartEncounterInput,
): Promise<StartEncounterResponse> {
  return request<StartEncounterResponse>("/api/encounters", {
    method: "POST",
    body: input,
  });
}

/** Snapshot of an encounter's current state. Throws on 404. */
export async function getEncounter(id: string): Promise<EncounterSnapshot> {
  return request<EncounterSnapshot>(
    `/api/encounters/${encodeURIComponent(id)}`,
  );
}

/** List encounters newest-first; `limit` is clamped server-side to [1, 100]. */
export async function listEncounters(
  opts: ListEncountersOptions = {},
): Promise<ListEncountersResponse> {
  return request<ListEncountersResponse>("/api/encounters", {
    query: {
      limit: opts.limit,
      offset: opts.offset,
    },
  });
}
