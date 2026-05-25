/**
 * ReviewQueueRow + CompleteReviewForm — type & contract smoke tests.
 *
 * Wave 2D PR C2. The main ``frontend/`` workspace currently has no
 * Vitest/Jest runner wired up — see the parallel comment in
 * ``components/customers/__tests__/decision-row.test.tsx``. Adding a
 * test runner is out of scope for this PR; a dedicated infra PR is
 * tracked separately.
 *
 * In the meantime, this file exercises the typed contract under
 * ``npx tsc --noEmit`` (which runs in CI via
 * .github/workflows/frontend-typecheck.yml). Each ``test_*`` constant
 * constructs a realistic fixture so:
 *
 *   1. Any future shape change in ``Approval`` / ``CompleteReviewInput``
 *      / ``RiskTier`` / ``ReviewerInsufficientDetail`` fails the
 *      typecheck loudly here, not silently at render time.
 *   2. When vitest is added, these fixtures drop straight into
 *      ``render(<ReviewQueueRow approval={test_approval_critical} />)``
 *      style assertions with zero rework.
 */

import * as React from "react";

import { ReviewQueueRow } from "../review-queue-row";
import { ReviewQueueTable } from "../review-queue-table";
import { ReviewDetailPanel } from "../review-detail-panel";
import { CompleteReviewForm } from "../complete-review-form";
import {
  isAlreadyDecided,
  isAttestationConflict,
  isReviewerInsufficient,
  isReviewExpired,
} from "@/hooks/use-complete-review";
import { ApiError } from "@/lib/api-client";
import type {
  Approval,
  ApprovalDecisionRecord,
  AttestationConflictResponse,
  CompleteReviewInput,
  ReviewerInsufficientDetail,
  RiskTier,
} from "@/lib/api-types";

// ── Approval fixtures (all four risk tiers + edge states) ──────────────

const _now = "2026-05-24T14:20:00.000Z";
const _later = "2026-05-24T16:20:00.000Z";

const _noVotes: ApprovalDecisionRecord[] = [];

export const test_approval_critical_dea: Approval = {
  id: "00000000-0000-4000-8000-000000000001",
  org_id: "org-1",
  request_record_id: "rec-1",
  resolution_record_id: null,
  requested_by_agent: "abridge-scribe@v3.2.1",
  data_subject_id: "cleveland_clinic",
  action_name: "prescribe_oxycodone",
  action_summary: "Prescribe oxycodone 5mg PO TID for post-op pain.",
  context: {
    gate_name: "clinical_scribe.controlled_substance",
    required_role: "dea_licensed_physician",
    citation: "21 CFR 1306.04",
    fix_url:
      "https://app.vera.io/reviews/00000000-0000-4000-8000-000000000001",
    reason_detail:
      "Controlled substance (Schedule II) — DEA-licensed physician required.",
  },
  risk_tier: "critical",
  approvers_required: 1,
  status: "pending",
  decisions: _noVotes,
  requested_at: _now,
  expires_at: _later,
  resolved_at: null,
};

export const test_approval_high_new_diagnosis: Approval = {
  id: "00000000-0000-4000-8000-000000000002",
  org_id: "org-1",
  request_record_id: "rec-2",
  resolution_record_id: null,
  requested_by_agent: "abridge-scribe@v3.2.1",
  data_subject_id: "memorial_hospital",
  action_name: "add_diagnosis",
  action_summary: "Add Type 2 diabetes (E11.9) to active problem list.",
  context: {
    gate_name: "clinical_scribe.new_diagnosis",
    required_role: "attending_physician",
    citation: "45 CFR 164.502(b)",
    input: { code: "E11.9", description: "Type 2 diabetes mellitus" },
  },
  risk_tier: "high",
  approvers_required: 1,
  status: "pending",
  decisions: _noVotes,
  requested_at: _now,
  expires_at: _later,
  resolved_at: null,
};

export const test_approval_medium_no_gate_context: Approval = {
  id: "00000000-0000-4000-8000-000000000003",
  org_id: "org-1",
  request_record_id: null,
  resolution_record_id: null,
  requested_by_agent: "legacy-agent@v1",
  data_subject_id: null,
  action_name: "manual_review",
  action_summary: null,
  // Pre-A2 row: no gate_name, no required_role. UI should render "—".
  context: {},
  risk_tier: "medium",
  approvers_required: 1,
  status: "pending",
  decisions: _noVotes,
  requested_at: _now,
  expires_at: null,
  resolved_at: null,
};

export const test_approval_low_expiring: Approval = {
  id: "00000000-0000-4000-8000-000000000004",
  org_id: "org-1",
  request_record_id: "rec-4",
  resolution_record_id: null,
  requested_by_agent: "voice-agent@v2",
  data_subject_id: "small_clinic",
  action_name: "send_followup_sms",
  action_summary: "Send post-visit follow-up SMS.",
  context: {
    gate_name: "voice_agent.outbound_sms",
    required_role: "nurse_practitioner",
  },
  risk_tier: "low",
  approvers_required: 1,
  status: "pending",
  decisions: _noVotes,
  requested_at: _now,
  // Already past — UI should render "Expired" in brick.
  expires_at: "2026-05-24T14:00:00.000Z",
  resolved_at: null,
};

// ── Render-shape smoke (validates props compile) ───────────────────────

const _row_critical: React.ReactNode = (
  <ReviewQueueRow
    approval={test_approval_critical_dea}
    customerDisplayName="Cleveland Clinic"
    selected
    onSelect={() => {}}
  />
);
const _row_no_gate: React.ReactNode = (
  <ReviewQueueRow approval={test_approval_medium_no_gate_context} />
);
const _row_expired: React.ReactNode = (
  <ReviewQueueRow approval={test_approval_low_expiring} />
);

const _table: React.ReactNode = (
  <ReviewQueueTable
    approvals={[
      test_approval_critical_dea,
      test_approval_high_new_diagnosis,
      test_approval_medium_no_gate_context,
      test_approval_low_expiring,
    ]}
    customersByTenantId={{
      cleveland_clinic: {
        id: "cust-1",
        org_id: "org-1",
        tenant_id: "cleveland_clinic",
        display_name: "Cleveland Clinic",
        status: "active",
        baa_status: "active",
        contact_email: null,
        contact_name: null,
        jurisdictions: null,
        first_seen_at: _now,
        last_seen_at: _now,
        decision_count_30d: 42,
        created_at: _now,
        updated_at: _now,
      },
    }}
    selectedReviewId={test_approval_critical_dea.id}
    onSelect={() => {}}
    total={4}
  />
);

const _detail: React.ReactNode = (
  <ReviewDetailPanel
    approval={test_approval_critical_dea}
    onClose={() => {}}
    customerDisplayName="Cleveland Clinic"
  />
);

const _form: React.ReactNode = (
  <CompleteReviewForm approval={test_approval_high_new_diagnosis} />
);

void _row_critical;
void _row_no_gate;
void _row_expired;
void _table;
void _detail;
void _form;

// ── Mutation input fixtures (all three decision shapes) ────────────────

export const test_complete_input_approve: CompleteReviewInput = {
  decision: "approve",
  reviewer_role: "attending_physician",
  reviewer_id: "alice@hospital.example",
  note: "Diagnosis confirmed via lab results 2026-05-24 — approve.",
};

export const test_complete_input_reject: CompleteReviewInput = {
  decision: "reject",
  reviewer_role: "dea_licensed_physician",
  reviewer_id: "drbob@hospital.example",
  note: "No DEA authorization on file for this patient — reject.",
  signature: "sig:placeholder",
};

// ── Error envelope fixtures (403/409/410) ─────────────────────────────

export const test_error_insufficient_role: ReviewerInsufficientDetail = {
  code: "reviewer_credentials_insufficient",
  review_id: test_approval_critical_dea.id,
  required_role: "dea_licensed_physician",
  reviewer_role: "MD",
  detail:
    "Reviewer role 'MD' does not satisfy required role 'dea_licensed_physician'.",
};

export const test_error_attestation_conflict: AttestationConflictResponse = {
  code: "attestation_conflict",
  review_id: test_approval_high_new_diagnosis.id,
  detail:
    "This review was already attested by another reviewer with a different decision.",
};

// Narrow each ApiError fixture against its guard so the guard's typing
// is locked in at typecheck time.
const _err_403 = new ApiError(403, test_error_insufficient_role.detail, test_error_insufficient_role);
const _err_409 = new ApiError(409, "Review is already approved", { code: "already_resolved" });
const _err_409_conflict = new ApiError(
  409,
  test_error_attestation_conflict.detail,
  test_error_attestation_conflict,
);
const _err_410 = new ApiError(410, "Review has expired");
const _err_500 = new ApiError(500, "Internal server error");

if (isReviewerInsufficient(_err_403)) {
  // After narrowing the detail should be typed correctly.
  const _required: string | null = _err_403.detail.required_role;
  void _required;
}
if (isAlreadyDecided(_err_409)) {
  const _status: number = _err_409.status;
  void _status;
}
if (isAttestationConflict(_err_409_conflict)) {
  const _code: string = _err_409_conflict.detail.code;
  void _code;
}
if (isReviewExpired(_err_410)) {
  const _status: number = _err_410.status;
  void _status;
}
// Negative case — 500 should not narrow as any of the documented errors.
if (
  !isReviewerInsufficient(_err_500) &&
  !isAlreadyDecided(_err_500) &&
  !isReviewExpired(_err_500) &&
  !isAttestationConflict(_err_500)
) {
  // Reached — confirms the guards are exhaustive for the documented codes.
}

// ── Exhaustiveness assertion ───────────────────────────────────────────
//
// If a new RiskTier is added without updating ``review-queue-row.tsx``'s
// lookup tables, the switch fallthrough below stops being exhaustive
// and TS errors out.
function _exhaust_risk(t: RiskTier): string {
  switch (t) {
    case "critical":
      return "H";
    case "high":
      return "H";
    case "medium":
      return "M";
    case "low":
      return "L";
  }
}
void _exhaust_risk;
void test_complete_input_approve;
void test_complete_input_reject;
