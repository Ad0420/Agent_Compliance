/**
 * Wire types mirroring `simulator/customers/triageguard/backend/contract.md`.
 *
 * Edit the contract first; this file is the TypeScript shadow of it.
 */

export type SessionStatus =
  | "running"
  | "awaiting_review"
  | "routed"
  | "routing_blocked"
  | "error";

export type FixtureKey =
  | "easy_self_care"
  | "red_flag_chest_pain"
  | "ambiguous";

export type RiskTier = "low" | "medium" | "high" | "critical";

export type SessionEventType =
  | "session_started"
  | "triage_classified"
  | "red_flag_evaluated"
  | "nurse_review_requested"
  | "nurse_decided"
  | "routed"
  | "routing_blocked"
  | "error";

export interface PatientSummary {
  subject_id: string;
  mrn: string;
  name: string;
  dob: string;
  sex: string;
  allergies: string[];
  active_meds: string[];
  chronic_conditions: string[];
  chief_complaint: string;
}

/**
 * The terminal routing record. Lands on `SessionSnapshot.terminal_outcome`
 * once the workflow has either committed a routing or been blocked.
 *
 * `nurse_status` is the verbatim decision word — `"confirm" | "escalate"` —
 * the nurse picked at the HITL gate. Inferred narrowing of the contract's
 * stringly-typed field; the backend never emits anything else.
 */
export interface TerminalRouting {
  session_id: string;
  initial_level: string;
  final_level: string;
  classifier_reasoning: string;
  red_flag_fired: boolean;
  red_flag_terms: string[];
  recommended_override: string | null;
  risk_tier: RiskTier;
  approval_id: string;
  nurse_status: "confirm" | "escalate" | string;
  routing_committed: boolean;
}

export interface SessionEvent {
  event: SessionEventType;
  data: Record<string, unknown>;
}

export interface SessionSnapshot {
  id: string;
  source: "fixture" | "custom";
  fixture_key: FixtureKey | null;
  patient_summary: PatientSummary | null;
  status: SessionStatus;
  last_event: SessionEventType | null;
  vera_approval_id: string | null;
  vera_record_ids: string[];
  terminal_outcome: TerminalRouting | null;
  events: SessionEvent[];
  input_payload: Record<string, unknown> | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface CustomSessionInput {
  symptoms: string;
  chief_complaint: string;
}

export type StartSessionInput =
  | { fixture: FixtureKey }
  | { custom: CustomSessionInput };

export interface StartSessionResponse {
  id: string;
  status: SessionStatus;
}

export interface ListSessionsResponse {
  sessions: SessionSnapshot[];
  total: number;
  limit: number;
  offset: number;
}

export interface ListSessionsOptions {
  limit?: number;
  offset?: number;
}

export interface DecideReviewResponse {
  approval_id: string;
  decision: "confirm" | "escalate";
  nurse: string;
  received: boolean;
}

/** Whether a status is terminal — polling should stop on these. */
export function isTerminalStatus(status: SessionStatus): boolean {
  return (
    status === "routed" ||
    status === "routing_blocked" ||
    status === "error"
  );
}

/** Whether an event signals the SSE stream should be closed. */
export function isTerminalEvent(event: SessionEventType): boolean {
  return (
    event === "routed" ||
    event === "routing_blocked" ||
    event === "error"
  );
}
