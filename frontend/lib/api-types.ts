// TypeScript interfaces matching backend Pydantic schemas

export interface HealthResponse {
  status: "ok" | "degraded";
  environment: string;
  database: boolean;
}

export interface Organization {
  id: string;
  name: string;
  alert_email: string | null;
  created_at: string;
}

export interface ActionRecord {
  id: string;
  org_id: string;
  sequence_number: number;
  previous_hash: string;
  record_hash: string;
  recorded_at: string;
  agent_name: string;
  agent_version: string | null;
  agent_id: string | null;
  data_subject_id: string | null;
  model_id: string | null;
  model_version: string | null;
  framework: string | null;
  framework_version: string | null;
  action_type: string;
  action_name: string;
  action_description: string | null;
  action_timestamp: string;
  target_system: string | null;
  target_resource: string | null;
  authorized_by: string;
  authorization_scope: string | null;
  delegation_chain: unknown[];
  result: string;
  error_message: string | null;
  duration_ms: number | null;
  input_data: Record<string, unknown>;
  policies_applied: unknown[];
  environment: Record<string, unknown>;
  outcome: Record<string, unknown>;
  reasoning: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export interface ActionListResponse {
  records: ActionRecord[];
  total: number;
  limit: number;
  offset: number;
}

export interface ActionQueryParams {
  agent_name?: string;
  action_type?: string;
  result?: string;
  authorized_by?: string;
  data_subject_id?: string;
  // Phase 1 PR 13: per-customer filter used by the Customer detail page's
  // decisions stream. Backend uses the indexed ``tenant_id`` column.
  tenant_id?: string;
  start_date?: string;
  end_date?: string;
  search?: string;
  limit?: number;
  offset?: number;
}

export interface ChainVerification {
  is_valid: boolean;
  records_checked: number;
  first_invalid_sequence: number | null;
  message: string;
}

export interface RecordVerification {
  record_id: string;
  record_hash_valid: boolean;
  chain_link_valid: boolean;
  message: string;
}

export interface Checkpoint {
  id: string;
  org_id: string;
  sequence_at_checkpoint: number;
  hash_at_checkpoint: string;
  merkle_root: string | null;
  key_id: string | null;
  created_at: string;
  signature: string;
  verified_at: string | null;
  is_valid: boolean | null;
}

export interface CheckpointListResponse {
  checkpoints: Checkpoint[];
  total: number;
}

export interface CheckpointVerificationResult {
  checkpoint_id: string;
  sequence: number;
  hash: string;
  merkle_root: string | null;
  is_valid: boolean;
  verified_at: string;
}

export interface CheckpointVerifyAllResponse {
  results: CheckpointVerificationResult[];
  all_valid: boolean;
  total_checked: number;
}

export interface Agent {
  id: string;
  org_id: string;
  name: string;
  description: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  permissions: string[];
  created_at: string;
  revoked_at: string | null;
  expires_at: string | null;
  is_active: boolean;
}

export interface ApiKeyCreateResponse {
  id: string;
  name: string;
  raw_key: string;
  key_prefix: string;
  permissions: string[];
  created_at: string;
}

export interface ApiKeyCreateInput {
  name: string;
  permissions: string[];
  expires_at?: string;
}

// Policies
export type ConditionType =
  | "unknown_agent"
  | "missing_reasoning"
  | "failure_rate"
  | "high_failure_burst"
  | "consecutive_failures";

export type PolicyAction = "flag" | "email";
export type PolicySeverity = "critical" | "high" | "medium" | "low";

export interface Policy {
  id: string;
  org_id: string;
  name: string;
  description: string | null;
  condition_type: ConditionType;
  condition_params: Record<string, unknown>;
  action: PolicyAction;
  severity: PolicySeverity;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface PolicyListResponse {
  policies: Policy[];
  total: number;
}

export interface PolicyCreateInput {
  name: string;
  description?: string;
  condition_type: ConditionType;
  condition_params: Record<string, unknown>;
  action: PolicyAction;
  severity: PolicySeverity;
  is_active?: boolean;
}

export interface PolicyUpdateInput {
  name?: string;
  description?: string;
  condition_params?: Record<string, unknown>;
  action?: PolicyAction;
  severity?: PolicySeverity;
  is_active?: boolean;
}

// Violations
export interface PolicyViolation {
  id: string;
  org_id: string;
  policy_id: string | null;
  record_id: string | null;
  triggered_at: string;
  severity: PolicySeverity;
  context: Record<string, unknown>;
  resolved_at: string | null;
  resolved_by: string | null;
}

export interface ViolationListResponse {
  violations: PolicyViolation[];
  total: number;
}

export interface ViolationQueryParams {
  severity?: PolicySeverity;
  resolved?: boolean;
  policy_id?: string;
  record_id?: string;
  limit?: number;
  offset?: number;
}

// Approvals (Human-in-the-Loop)
export type RiskTier = "low" | "medium" | "high" | "critical";
export type ApprovalStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "expired"
  | "cancelled";

export interface ApprovalDecisionRecord {
  decision: "approve" | "reject" | "cancel";
  approver: string;
  note?: string | null;
  decided_at: string;
  signature?: string;
  key_id?: string;
}

export interface Approval {
  id: string;
  org_id: string;
  request_record_id: string | null;
  resolution_record_id: string | null;
  requested_by_agent: string;
  data_subject_id: string | null;
  action_name: string;
  action_summary: string | null;
  context: Record<string, unknown>;
  risk_tier: RiskTier;
  approvers_required: number;
  status: ApprovalStatus;
  decisions: ApprovalDecisionRecord[];
  requested_at: string;
  expires_at: string | null;
  resolved_at: string | null;
}

export interface ApprovalListResponse {
  approvals: Approval[];
  total: number;
}

export interface ApprovalCreateInput {
  agent_name: string;
  action_name: string;
  action_summary?: string;
  data_subject_id?: string;
  context?: Record<string, unknown>;
  risk_tier?: RiskTier;
  approvers_required?: number;
  expires_in_seconds?: number;
}

export interface ApprovalDecisionInput {
  decision: "approve" | "reject";
  approver: string;
  note?: string;
}

export interface ApprovalQueryParams {
  status?: ApprovalStatus;
  risk_tier?: RiskTier;
  data_subject_id?: string;
  limit?: number;
  offset?: number;
}

// Customers (Phase 1 PR 2/3 — multi-tenant first-class concept)
//
// "Customer" in the UI means *your* customer — the audit target your AI
// serves (hospital in medtech, bank in lending, employer in hiring). The
// data model is generic. See dashboard-design.md §The multi-tenant model.
export type CustomerStatus =
  | "pending_setup"
  | "active"
  | "suspended"
  | "archived";

// "terminated" distinguishes a rescinded BAA from one that simply expired.
// Matches backend backend/app/schemas/customer.py and CHECK constraint.
export type BAAStatus =
  | "missing"
  | "pending"
  | "active"
  | "expired"
  | "terminated";

export interface Customer {
  id: string;
  org_id: string;
  tenant_id: string;
  display_name: string | null;
  status: CustomerStatus;
  baa_status: BAAStatus;
  contact_email: string | null;
  contact_name: string | null;
  jurisdictions: string[] | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
  decision_count_30d: number;
  created_at: string;
  updated_at: string;
}

export interface CustomerListResponse {
  items: Customer[];
  total: number;
  limit: number;
  offset: number;
}

export interface CustomerQueryParams {
  status?: CustomerStatus;
  baa_status?: BAAStatus;
  // Phase 1 PR 13: opt into batched decision_count_30d rollup. Default
  // off so the Home page's tiny list stays cheap; the full Customers
  // list (`/customers`) passes `with_counts=1` so each row shows
  // accurate 30-day activity without N+1 fetches.
  with_counts?: boolean;
  limit?: number;
  offset?: number;
}

// Onboarding wizard (Phase 1 PR 14, Stream F item F5).
// Shapes mirror backend/app/schemas/wizard.py. Slugs are stable on the
// wire — UI labels live in components/wizard/questions.ts.

export type WizardAgentType =
  | "scribe"
  | "receptionist"
  | "prior_auth"
  | "triage"
  | "other";

export type WizardDecisionVolume =
  | "lt_10k"
  | "10k_100k"
  | "100k_1m"
  | "gt_1m";

export type WizardReviewChannel =
  | "in_app_webhook"
  | "slack"
  | "vera_dashboard"
  | "multiple";

// Allow-listed jurisdiction tokens (server enforces the same set).
export type WizardJurisdiction = "us_federal" | "us_ca" | "other_state";

export interface WizardPrivacyOfficer {
  name: string;
  email: string;
}

export interface WizardAnswers {
  agent_type: WizardAgentType | null;
  agent_type_other: string | null;
  jurisdictions: WizardJurisdiction[] | null;
  decision_volume: WizardDecisionVolume | null;
  channel: WizardReviewChannel | null;
  privacy_officer: WizardPrivacyOfficer | null;
}

export interface WizardAnswersResponse {
  answers: WizardAnswers | null;
  completed_at: string | null;
}

export interface WizardAnswersSubmission {
  answers: Partial<WizardAnswers>;
  completed: boolean;
}

// AI Coverage Matrix per-customer agent rows (Phase 1 PR 13, Stream F item F4).
// Backed by GET /v1/customers/{tenant_id}/agents. The Phase 1 placeholder
// columns (`hitl_gate_count`, `pdf_included`, `posture_included`) are
// surfaced today so the dashboard contract stays stable when Phase 2/4
// actually populates them — only the values change.
export type CustomerAgentSource = "auto_discovered" | "declared" | "csv_import";
export type CustomerAgentConfidence = "low" | "medium" | "high";
export type CustomerAgentLifecycle = "active" | "retired";
export type CustomerAgentCoverageLevel = "covered" | "partial" | "none";

export interface CustomerAgentCoverage {
  id: string;
  agent_type: string;
  agent_id: string | null;
  source: CustomerAgentSource;
  confidence: CustomerAgentConfidence;
  status: CustomerAgentLifecycle;
  first_seen_at: string;
  last_seen_at: string;
  coverage: CustomerAgentCoverageLevel;
  has_capture: boolean;
  hitl_gate_count: number;
  pdf_included: boolean;
  posture_included: boolean;
}

export interface CustomerAgentsResponse {
  items: CustomerAgentCoverage[];
  total: number;
}

// BAA upload contract (Phase 1 PR 13, Phase 1 acceptance gate).
// Phase 1 ships the wire contract with a pre-signed document_uri; a
// follow-up will wire the actual multipart-to-S3 path. The acceptance
// gate ("one BAA upload completes setup") is met by the schema change +
// freshness-cache invalidation.
export interface BAAUploadInput {
  document_uri: string;
  effective_at?: string | null;
  expires_at?: string | null;
  signed_at?: string | null;
  is_unrestricted?: boolean;
  covered_services?: string[];
  covered_agent_types?: string[];
}

export interface BAAUploadResponse {
  agreement_id: string;
  scope_id: string;
  customer_baa_status: BAAStatus;
  customer_status: CustomerStatus;
  effective_at: string | null;
  expires_at: string | null;
}

// Webhook subscriptions + delivery health (Phase 2 Wave 2B PR A3 backend,
// Wave 2C PR C3 dashboard surface).
//
// A ``WebhookSubscription`` is the customer-facing endpoint (URL + event
// subscriptions). A ``WebhookDelivery`` is one (subscription, event) pair;
// it survives retries. ``WebhookDeliveryAttempt`` is one HTTP send. The
// Settings → Integrations page hangs a health panel off each subscription
// card by calling `GET /v1/webhooks/{id}/deliveries` and reducing the
// returned rows into a few scalar stats.
//
// ``WebhookDeliveryStatus`` mirrors the backend `webhook_deliveries.status`
// column verbatim — it is the canonical wire shape. The Decisions-tab
// UI uses a derived view (``DecisionWebhookStatus`` below) that collapses
// ``succeeded`` → ``delivered`` and synthesises ``retrying`` from
// ``pending AND attempt_count > 1``.
export type WebhookDeliveryStatus =
  | "pending"
  | "in_progress"
  | "succeeded"
  | "aborted";

export interface WebhookSubscription {
  id: string;
  url: string;
  event_types: string[];
  is_active: boolean;
  description: string | null;
  created_at: string;
  last_delivery_at: string | null;
  last_delivery_status: string | null;
  consecutive_failures: number;
}

export interface WebhookListResponse {
  webhooks: WebhookSubscription[];
}

export interface WebhookDeliveryAttempt {
  id: string;
  attempt_number: number;
  attempted_at: string;
  status_code: number | null;
  error_message: string | null;
  duration_ms: number | null;
  next_retry_at: string | null;
}

export interface WebhookDelivery {
  id: string;
  subscription_id: string;
  event_type: string;
  status: WebhookDeliveryStatus;
  attempt_count: number;
  next_retry_at: string | null;
  created_at: string;
  succeeded_at: string | null;
  aborted_at: string | null;
  last_status_code: number | null;
  idempotency_key: string;
  attempts: WebhookDeliveryAttempt[];
}

export interface WebhookDeliveriesResponse {
  deliveries: WebhookDelivery[];
  total: number;
}

export interface WebhookDeliveriesQueryParams {
  status?: WebhookDeliveryStatus;
  limit?: number;
  offset?: number;
}

export interface WebhookDeliveryReplayResponse {
  id: string;
  status: WebhookDeliveryStatus;
  attempt_count: number;
  next_retry_at: string | null;
}

// ── Wave 2C PR C1 + C1.5 — Customer detail Decisions tab ─────────────────
//
// Surfaces what each agent decision *meant*: the gate Ruling, the
// downstream webhook delivery status, and (for pending HITL approvals)
// the time-to-expiry countdown.
//
// Backend source of truth (post-C1.5):
//   * GET /v1/customers/{tenant_id}/decisions — server-side join of
//     ActionRecord ⋈ Approval ⋈ WebhookDelivery (most recent per
//     approval). Shape mirrors backend/app/schemas/customer_decision.py.
//   * Ruling fields come off ``Approval.context`` (gate_name /
//     required_role / citation / reason) — NOT ActionRecord.reasoning.
//     Writing into reasoning would change the hash chain.
//   * Webhook delivery status is the latest WebhookDelivery row whose
//     idempotency_key starts ``"{approval.id}:"``.
//
// C1 originally adapted GET /v1/actions client-side; C1.5 replaced the
// adapter with the dedicated endpoint when /review caught that the
// adapter read keys the backend doesn't write. Hook signature was
// preserved — consumers of useCustomerDecisions are unaffected.
//
// ALLOW-ruling limitation: ``ruling`` is ``null`` for actions whose
// gate decided ALLOW (no Approval row is created on the ALLOW path).
// Out-of-scope follow-up: either SDK-side denormalisation onto
// ActionRecord or a new ``gate_evaluations`` table.

export type RulingEffect = "allow" | "require_hitl" | "block";

export interface Ruling {
  effect: RulingEffect;
  reason: string;
  reason_detail: string | null;
  citation: string | null;
  review_id: string | null;
  fix_url: string | null;
  required_role: string | null;
  gate_name: string | null;
}

// UI-layer derived status for the Decisions tab (distinct from
// ``WebhookDeliveryStatus`` above, which is the canonical backend wire
// shape). The mapping the adapter applies:
//   backend ``succeeded``         → ``delivered``
//   backend ``aborted``           → ``aborted``
//   backend ``pending``  (attempt_count > 1, next_retry_at set) → ``retrying``
//   backend ``pending`` / ``in_progress`` (otherwise) → ``pending``
// This keeps the row label intuitive ("Delivered" / "Retrying") without
// coupling the customer-facing UI to backend lifecycle vocabulary.
export type DecisionWebhookStatus =
  | "delivered"
  | "pending"
  | "retrying"
  | "aborted";

export interface WebhookDeliverySummary {
  status: DecisionWebhookStatus;
  attempt_count: number;
  // Total attempts allowed before status flips to ``aborted``. Backend
  // currently uses 7 (see services/webhooks.py); surfacing it lets the
  // UI render "Retry N/7" without hard-coding the budget.
  max_attempts: number;
  next_retry_at: string | null;
  last_status_code: number | null;
  succeeded_at: string | null;
  aborted_at: string | null;
}

// Composite shape consumed by the Decisions tab. One row per action.
// Built client-side from an ActionRecord + (optional) Ruling pulled out
// of reasoning + (optional) webhook delivery summary.
export interface CustomerDecision {
  id: string;
  sequence_number: number;
  action_timestamp: string;
  agent_name: string;
  action_name: string;
  action_type: string;
  result: string;
  // Present when a gate evaluated this action. ``null`` = no gate ran
  // (capture-only mode or Wave 2A stub allow).
  ruling: Ruling | null;
  // Present when this action triggered a webhook subscription. ``null``
  // for actions with no subscribers.
  webhook_delivery: WebhookDeliverySummary | null;
  // Mirrors Approval.expires_at when ruling.effect === 'require_hitl' and
  // a review is still pending. ``null`` otherwise (approved, expired, or
  // no HITL required).
  hitl_expires_at: string | null;
}

export interface CustomerDecisionsResponse {
  decisions: CustomerDecision[];
  total: number;
  limit: number;
  offset: number;
}

export interface CustomerDecisionsQueryParams {
  limit?: number;
  offset?: number;
}
