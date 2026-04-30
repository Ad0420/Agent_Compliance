/**
 * Wire types mirroring `simulator/customers/scribemd/backend/contract.md`.
 *
 * Edit the contract first; this file is the TypeScript shadow of it.
 */

export type EncounterStatus =
  | "running"
  | "awaiting_approval"
  | "committed"
  | "blocked"
  | "auto_committed"
  | "error";

export type FixtureKey = "pancreatitis" | "followup" | "chest_pain";

export type RiskTier = "low" | "medium" | "high" | "critical";

export type EncounterEventType =
  | "draft_started"
  | "draft_complete"
  | "orders_extracted"
  | "approval_requested"
  | "approval_decided"
  | "chart_committed"
  | "chart_blocked"
  | "error";

export interface PatientSummary {
  subject_id: string;
  name: string;
  dob: string;
  sex: string;
  allergies: string[];
  active_meds: string[];
  chronic_conditions: string[];
  chief_complaint: string;
  visit_type: string;
  expected_risk: RiskTier;
}

export interface TerminalOutcome {
  encounter_id: string;
  approval_status: string;
  chart_committed: boolean;
  risk_tier: RiskTier;
  diagnoses: string[];
  medication_orders: string[];
  lab_or_imaging_orders: string[];
  note: string;
}

export interface EncounterEvent {
  event: EncounterEventType;
  data: Record<string, unknown>;
}

export interface EncounterSnapshot {
  id: string;
  source: "fixture" | "custom";
  fixture_key: FixtureKey | null;
  patient_summary: PatientSummary | null;
  status: EncounterStatus;
  last_event: EncounterEventType | null;
  vera_approval_id: string | null;
  vera_record_ids: string[];
  terminal_outcome: TerminalOutcome | null;
  events: EncounterEvent[];
  input_payload: Record<string, unknown> | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface CustomEncounterInput {
  transcript: string;
  chief_complaint: string;
  visit_type?: "office" | "urgent" | "telehealth";
  expected_risk?: RiskTier;
}

export type StartEncounterInput =
  | { fixture: FixtureKey }
  | { custom: CustomEncounterInput };

export interface StartEncounterResponse {
  id: string;
  status: EncounterStatus;
}

export interface ListEncountersResponse {
  encounters: EncounterSnapshot[];
  total: number;
  limit: number;
  offset: number;
}

export interface ListEncountersOptions {
  limit?: number;
  offset?: number;
}

export interface DecideApprovalResponse {
  approval_id: string;
  decision: "approve" | "reject";
  approver: string;
  received: boolean;
}

/** Whether a status is terminal — polling should stop on these. */
export function isTerminalStatus(status: EncounterStatus): boolean {
  return (
    status === "committed" ||
    status === "blocked" ||
    status === "auto_committed" ||
    status === "error"
  );
}

/** Whether an event signals the SSE stream should be closed. */
export function isTerminalEvent(event: EncounterEventType): boolean {
  return (
    event === "chart_committed" ||
    event === "chart_blocked" ||
    event === "error"
  );
}
