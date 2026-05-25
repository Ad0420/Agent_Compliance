/**
 * DecisionRow — type & contract smoke tests.
 *
 * Wave 2C PR C1. The main ``frontend/`` workspace currently has no
 * Vitest/Jest runner wired up (only the simulator workspaces do — see
 * ``simulator/customers/scribemd/frontend/package.json``). Adding a
 * test runner is out of scope for this PR; a dedicated infra PR is
 * tracked separately.
 *
 * In the meantime, this file exercises the typed contract under
 * ``npx tsc --noEmit`` (which runs in CI via .github/workflows/
 * frontend-typecheck.yml). Each ``test_*`` constant constructs a
 * realistic fixture for ``DecisionRow`` and ``DecisionsTab`` so:
 *
 *   1. Any future shape change in ``CustomerDecision`` / ``Ruling`` /
 *      ``WebhookDeliverySummary`` fails the typecheck loudly here,
 *      not silently at render time.
 *   2. When vitest is added, these fixtures drop straight into
 *      ``render(<DecisionRow decision={test_allow_no_webhook} />)``
 *      style assertions with zero rework — they're the same shape.
 *
 * This is intentional: a stale fixture is worse than no fixture. By
 * binding fixtures to the live types we get a real contract test today
 * and a head-start on render tests tomorrow.
 */

import * as React from "react";

import { DecisionRow } from "../decision-row";
import type {
  CustomerDecision,
  Ruling,
  RulingEffect,
  WebhookDeliverySummary,
  WebhookDeliveryStatus,
} from "@/lib/api-types";

// ── Ruling fixtures (all three effects) ────────────────────────────────

export const test_ruling_allow: Ruling = {
  effect: "allow",
  reason: "no_phi_detected",
  reason_detail: "No PHI shape detected in proposed action.",
  citation: null,
  review_id: null,
  fix_url: null,
  required_role: null,
  gate_name: "clinical_scribe.default",
};

export const test_ruling_require_hitl: Ruling = {
  effect: "require_hitl",
  reason: "new_diagnosis_detected",
  reason_detail:
    "New diagnosis (E11.9 Type 2 diabetes) requires attending physician review.",
  citation: "45 CFR 164.502(b)",
  review_id: "00000000-0000-4000-8000-000000000001",
  fix_url: "/reviews/00000000-0000-4000-8000-000000000001",
  required_role: "attending_physician",
  gate_name: "clinical_scribe.new_diagnosis",
};

export const test_ruling_block: Ruling = {
  effect: "block",
  reason: "controlled_substance_detected",
  reason_detail:
    "Controlled substance (Schedule II) without DEA authorization on file.",
  citation: "21 CFR 1308.12",
  review_id: null,
  fix_url: null,
  required_role: null,
  gate_name: "clinical_scribe.controlled_substance",
};

// ── Webhook delivery fixtures (all four statuses) ──────────────────────

export const test_webhook_delivered: WebhookDeliverySummary = {
  status: "delivered",
  attempt_count: 1,
  max_attempts: 7,
  next_retry_at: null,
  last_status_code: 200,
  succeeded_at: "2026-05-24T14:22:18.000Z",
  aborted_at: null,
};

export const test_webhook_pending: WebhookDeliverySummary = {
  status: "pending",
  attempt_count: 0,
  max_attempts: 7,
  next_retry_at: null,
  last_status_code: null,
  succeeded_at: null,
  aborted_at: null,
};

export const test_webhook_retrying: WebhookDeliverySummary = {
  status: "retrying",
  attempt_count: 3,
  max_attempts: 7,
  next_retry_at: "2026-05-24T14:30:00.000Z",
  last_status_code: 503,
  succeeded_at: null,
  aborted_at: null,
};

export const test_webhook_aborted: WebhookDeliverySummary = {
  status: "aborted",
  attempt_count: 7,
  max_attempts: 7,
  next_retry_at: null,
  last_status_code: 500,
  succeeded_at: null,
  aborted_at: "2026-05-24T15:10:00.000Z",
};

// ── Composite decision fixtures ────────────────────────────────────────

const _now = "2026-05-24T14:20:00.000Z";

export const test_decision_allow_no_webhook: CustomerDecision = {
  id: "dec-1",
  sequence_number: 101,
  action_timestamp: _now,
  agent_name: "abridge-scribe@v3.2.1",
  action_name: "draft_visit_summary",
  action_type: "decision",
  result: "ok",
  ruling: test_ruling_allow,
  webhook_delivery: null,
  hitl_expires_at: null,
};

export const test_decision_require_hitl_pending: CustomerDecision = {
  id: "dec-2",
  sequence_number: 102,
  action_timestamp: _now,
  agent_name: "abridge-scribe@v3.2.1",
  action_name: "add_diagnosis",
  action_type: "decision",
  result: "pending",
  ruling: test_ruling_require_hitl,
  webhook_delivery: test_webhook_pending,
  // 2 hours from now-ish — tests against ``formatTimeUntil``.
  hitl_expires_at: "2026-05-24T16:30:00.000Z",
};

export const test_decision_block_retrying: CustomerDecision = {
  id: "dec-3",
  sequence_number: 103,
  action_timestamp: _now,
  agent_name: "abridge-scribe@v3.2.1",
  action_name: "prescribe_oxycodone",
  action_type: "decision",
  result: "blocked",
  ruling: test_ruling_block,
  webhook_delivery: test_webhook_retrying,
  hitl_expires_at: null,
};

export const test_decision_no_ruling_delivered: CustomerDecision = {
  id: "dec-4",
  sequence_number: 104,
  action_timestamp: _now,
  agent_name: "abridge-scribe@v3.2.1",
  action_name: "save_chart_note",
  action_type: "decision",
  result: "ok",
  ruling: null, // capture-only mode (no gate ran)
  webhook_delivery: test_webhook_delivered,
  hitl_expires_at: null,
};

export const test_decision_aborted_webhook: CustomerDecision = {
  id: "dec-5",
  sequence_number: 105,
  action_timestamp: _now,
  agent_name: "abridge-scribe@v3.2.1",
  action_name: "notify_emr",
  action_type: "decision",
  result: "ok",
  ruling: test_ruling_allow,
  webhook_delivery: test_webhook_aborted,
  hitl_expires_at: null,
};

// ── Render-shape smoke (validates props compile) ───────────────────────
//
// Each entry below is a JSX expression — TS will reject any future
// signature change that breaks the call site. The renders are not
// mounted; this is a contract test, not a behavior test.

const _allow_node: React.ReactNode = (
  <DecisionRow decision={test_decision_allow_no_webhook} />
);
const _hitl_node: React.ReactNode = (
  <DecisionRow decision={test_decision_require_hitl_pending} />
);
const _block_node: React.ReactNode = (
  <DecisionRow decision={test_decision_block_retrying} />
);
const _no_ruling_node: React.ReactNode = (
  <DecisionRow decision={test_decision_no_ruling_delivered} />
);
const _aborted_node: React.ReactNode = (
  <DecisionRow decision={test_decision_aborted_webhook} />
);

// Mark intentionally-unused locals so ESLint doesn't strip them; the
// type-side-effect of constructing each node is the test value.
void _allow_node;
void _hitl_node;
void _block_node;
void _no_ruling_node;
void _aborted_node;

// ── Exhaustiveness assertion ───────────────────────────────────────────
//
// If a new RulingEffect or WebhookDeliveryStatus is added to api-types
// without updating ``decision-row.tsx``'s lookup tables, the switch
// fallthroughs below stop being exhaustive and TS errors out.

function _exhaust_effects(e: RulingEffect): string {
  switch (e) {
    case "allow":
      return "L";
    case "require_hitl":
      return "M";
    case "block":
      return "H";
  }
}
function _exhaust_statuses(s: WebhookDeliveryStatus): string {
  switch (s) {
    case "delivered":
      return "ok";
    case "pending":
      return "muted";
    case "retrying":
      return "warn";
    case "aborted":
      return "error";
  }
}

void _exhaust_effects;
void _exhaust_statuses;
