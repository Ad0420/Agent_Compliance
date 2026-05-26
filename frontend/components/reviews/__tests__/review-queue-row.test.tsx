/**
 * Review queue typed-contract smoke tests — Wave 2D PR C2 + W2.2.
 *
 * The main ``frontend/`` workspace currently has no Vitest/Jest runner
 * wired up — see the parallel comment in
 * ``components/customers/__tests__/decision-row.test.tsx``. Adding a
 * test runner is out of scope for this PR; a dedicated infra PR is
 * tracked separately.
 *
 * In the meantime, this file exercises the typed contract under
 * ``npx tsc --noEmit`` (which runs in CI via
 * .github/workflows/frontend-typecheck.yml). Each ``test_*`` constant
 * constructs a realistic fixture so:
 *
 *   1. Any future shape change in ``Approval`` / ``RiskTier`` /
 *      ``ReviewerInsufficientDetail`` fails the typecheck loudly here,
 *      not silently at render time.
 *   2. When vitest is added, these fixtures drop straight into
 *      ``render(<ReviewQueueRow approval={test_approval_critical} />)``
 *      style assertions with zero rework.
 *
 * W2.2 update: the dashboard Review queue is read-only — the
 * Approve/Modify/Reject form was removed because HIPAA min-necessary
 * forbids the AI vendor's staff from authorising clinical decisions.
 * HITL completion happens in-band via ScribeMD's EHR callback. The
 * `CompleteReviewInput` / `ReviewerInsufficientDetail` /
 * `AttestationConflictResponse` types stay in ``lib/api-types.ts`` so
 * the SDK + any future in-band UI share the contract, but they no
 * longer flow through the dashboard render tree.
 */

import * as React from "react";

import { ReviewQueueRow } from "../review-queue-row";
import { ReviewQueueTable } from "../review-queue-table";
import { ReviewDetailPanel } from "../review-detail-panel";
import type {
  Approval,
  ApprovalDecisionRecord,
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
  // W2.2 — backend strips data_subject_id for dashboard callers
  // (services/dashboard_views.py); fixture mirrors the live wire shape.
  data_subject_id: null,
  action_name: "prescribe_oxycodone",
  // W2.2 — same as above; action_summary stripped server-side.
  action_summary: null,
  context: {
    gate_name: "clinical_scribe.controlled_substance",
    required_role: "dea_licensed_physician",
    citation: "21 CFR 1306.04",
    fix_url:
      "https://app.vera.io/reviews/00000000-0000-4000-8000-000000000001",
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
  data_subject_id: null,
  action_name: "add_diagnosis",
  action_summary: null,
  context: {
    gate_name: "clinical_scribe.new_diagnosis",
    required_role: "attending_physician",
    citation: "45 CFR 164.502(b)",
    // NOTE: no ``input`` / ``reason_detail`` keys — the dashboard
    // context whitelist drops them server-side, and the UI must not
    // render them either (defense-in-depth, W2.2).
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
  data_subject_id: null,
  action_name: "send_followup_sms",
  action_summary: null,
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

// W2.2 — resolved approval fixture. Mirrors the redacted ``decisions[]``
// shape returned by ``serialize_approval_for_dashboard``: the
// ``approver`` (reviewer_id PII) and ``note`` (PHI narrative) fields
// are stripped server-side, and a derived ``reviewer_role`` is
// surfaced. The detail panel reads ``reviewer_role`` to render the
// read-only "Approved by attending_physician" status indicator
// without ever touching the customer-side clinician's identifier.
export const test_approval_resolved_approved: Approval = {
  ...test_approval_high_new_diagnosis,
  status: "approved",
  resolved_at: "2026-05-24T15:00:00.000Z",
  decided_at: "2026-05-24T15:00:00.000Z",
  decisions: [
    {
      decision: "approve",
      // Dashboard wire omits ``approver`` and ``note`` entirely; the
      // TS contract marks them optional (lib/api-types.ts W2.2) so
      // the dashboard's subset shape compiles cleanly.
      decided_at: "2026-05-24T15:00:00.000Z",
      signature: "kms-signed-blob",
      key_id: "kms-key-1",
      reviewer_role: "attending_physician",
    },
  ],
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

// W2.2 — detail panel is read-only. No CompleteReviewForm prop, no
// ``onSuccess`` / ``onTerminalError`` plumbing. Status indicator is
// the only "action" the panel renders.
const _detail_pending: React.ReactNode = (
  <ReviewDetailPanel
    approval={test_approval_critical_dea}
    onClose={() => {}}
    customerDisplayName="Cleveland Clinic"
  />
);

const _detail_resolved: React.ReactNode = (
  <ReviewDetailPanel
    approval={test_approval_resolved_approved}
    onClose={() => {}}
    customerDisplayName="Memorial Hospital"
  />
);

const _detail_expired: React.ReactNode = (
  <ReviewDetailPanel
    approval={test_approval_low_expiring}
    onClose={() => {}}
    customerDisplayName="Small Clinic"
  />
);

void _row_critical;
void _row_no_gate;
void _row_expired;
void _table;
void _detail_pending;
void _detail_resolved;
void _detail_expired;

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
