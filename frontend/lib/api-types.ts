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

// ── Wave 2D PR C4 — Review queue Recommendation card scaffold ──────────
//
// Mirrors the contract that the Phase 4 AI Insights endpoint
// (`POST /v1/compliance/insights`) will return. Empty in Phase 2 — the
// `ReviewRecommendations` component renders nothing visible because no
// recommendations exist yet. Wired up in Phase 4 when the Haiku-class
// generator lands.
//
// Source of truth: v1-implementation-plan.md Phase 2 line 122 (scaffold
// brief) + Phase 4 line 188 (endpoint shape).
//
// Severity vocabulary matches the existing `SeverityBadge` primitive
// (`HIGH | MEDIUM | LOW | INFO`) so the Phase 4 wiring is a plug-in,
// not a rewrite. The Phase 4 plan permits HIGH | MEDIUM | LOW; INFO is
// reserved for non-actionable findings (e.g., "no patterns detected
// this week").

export type RecommendationSeverity = "HIGH" | "MEDIUM" | "LOW" | "INFO";

export interface ReviewRecommendation {
  id: string;
  severity: RecommendationSeverity;
  title: string;
  /**
   * Issue description (the pattern Vera detected, e.g., "3 decisions
   * below review-time threshold from reviewer X in the last 7 days").
   * Rendered with the amber ⚠ glyph in the primitive's expanded body.
   */
  description: string;
  /**
   * Required regulatory citation or in-context evidence. Per the AI
   * Insights principle in Phase 4 §A6: every card carries a quoted
   * source so the recommendation is grounded, not hallucinated.
   * Rendered in a `--paper-3` block in the primitive.
   */
  quoted_source: string;
  /**
   * Concrete next-step copy ("Open a counsel-review task for reviewer X").
   * In Phase 4 this is what `apply_action` produces when the user clicks
   * Apply (creates a task, no auto-mutation of records).
   */
  suggested_action: string;
  /**
   * Machine-readable identifier of what clicking "Apply" should do.
   * Phase 2: scaffold no-op (the component's `onApply` callback receives
   * the recommendation id; the host wires it up). Phase 4: server
   * dispatches a task per this action key.
   */
  apply_action: string;
}

export interface ReviewRecommendationsResponse {
  recommendations: ReviewRecommendation[];
  /** ISO-8601 timestamp the insights call generated this set. */
  generated_at: string;
  /** Model identifier (e.g., "claude-haiku-4.x"). Surfaces in audit trail. */
  model: string;
}

// ── Wave 2D PR C2 — Review queue page (HITL completion) ──────────────────
//
// Body shape for ``POST /v1/reviews/{review_id}/complete`` — mirrors the
// backend ``ReviewCompletionInput`` schema (backend/app/schemas/review.py).
// Field constraints mirror the server's pydantic bounds verbatim so the
// dashboard form catches input violations before they hit the wire:
//
//   * reviewer_role: min_length=1, max_length=64
//   * reviewer_id:   min_length=1, max_length=128
//   * note:          max_length=2000 (regulation per spec requires a comment
//                    of at least 10 chars on approve/reject — enforced UI-side)
//   * signature:     max_length=512 (Phase 4 will verify; Phase 2 free-form)
export interface CompleteReviewInput {
  decision: "approve" | "reject";
  reviewer_role: string;
  reviewer_id: string;
  note?: string | null;
  signature?: string | null;
}

// Success response shape: ``ApprovalResponse`` on 200. The endpoint
// returns the *updated* approval row so the dashboard's React Query
// cache can swap the queue entry without a refetch.
export type CompleteReviewResponse = Approval;

// 403 error envelope. The backend's ``_insufficient_role_detail``
// returns this as the ``detail`` field on the 403; the dashboard surfaces
// the structured fields inline ("Your role 'MD' is insufficient. This
// decision requires 'dea_licensed_physician'.").
export interface ReviewerInsufficientDetail {
  code: "reviewer_credentials_insufficient";
  review_id: string;
  required_role: string | null;
  reviewer_role: string;
  detail: string;
}

// 409 error envelope. Two distinct codes flow through this status:
//   * already-resolved (approved / rejected / cancelled) — the row moved
//     out of pending while the reviewer was filling out the form.
//   * attestation_conflict (Wave 2D A6) — second callback with a
//     different decision from a different reviewer. Canonical decision
//     stays first; this one is logged and rejected.
// Both surface the same "already decided" message in the UI; admins can
// pull the structured detail from the audit chain.
export interface AttestationConflictResponse {
  code: "attestation_conflict" | "already_resolved";
  review_id: string;
  detail: string;
}

// ── Wave 3D.2 — Customer Verification & Evidence Trail panel ───────────
//
// Backed by ``GET /v1/customers/{tenant_id}/chain-summary``. The panel
// renders the customer's latest checkpoint summary + a 30-day timeline
// strip + a "Download evidence bundle" CTA + an inline "Verify this
// customer's chain" button.
//
// ``verification_supported=false`` greys out the inline verify CTA:
// HMAC-SHA256 chains can't be verified in the browser without the
// shared secret (which must never live client-side); asymmetric KMS
// keys (RSA-PSS / ECDSA) carry a public PEM that the Web Crypto API
// can use to verify the checkpoint signature without holding any
// secret. The dashboard renders an honest reason in either branch.

export type ChainTimelineStatus = "sealed" | "none" | "pending";

export interface ChainTimelineDay {
  /** ISO calendar date for this tile (e.g., "2026-05-19"). */
  date: string;
  status: ChainTimelineStatus;
  checkpoint_id: string | null;
  customer_record_count: number;
}

export interface ChainLatestCheckpoint {
  checkpoint_id: string;
  merkle_root: string | null;
  /** Naive UTC ISO string with millisecond precision. */
  signed_at: string;
  kms_key_id: string | null;
  kms_algorithm: string | null;
  /** PEM-encoded public key for asymmetric KMS providers; null otherwise. */
  kms_public_key_pem: string | null;
  customer_record_count: number;
  total_record_count: number;
  sequence_at_checkpoint: number;
}

export interface CustomerChainSummary {
  tenant_id: string;
  customer_display_name: string | null;
  latest_checkpoint: ChainLatestCheckpoint | null;
  timeline: ChainTimelineDay[];
  verification_supported: boolean;
  /**
   * Documented reason the inline Verify button is greyed out. Today
   * the only value is ``"hmac_symmetric_no_shared_secret"`` (HMAC
   * chains need the shared secret out-of-band). Future values can be
   * added without breaking the contract — consumers fall back to the
   * generic "verification not available in browser" copy if the code
   * isn't recognised.
   */
  verification_unsupported_reason: string | null;
}

// ── Evidence bundle preview (selective-disclosure modal) ───────────────

export interface EvidenceExportPreviewRequest {
  start_date?: string;
  end_date?: string;
  preview: true;
}

export interface EvidenceExportPreview {
  tenant_id: string;
  customer_display_name: string | null;
  customer_record_count: number;
  checkpoint_count: number;
  /**
   * Honest warnings the dashboard surfaces alongside the count.
   * ``"hmac_chain_no_offline_signature_verify"`` = the verifier can
   * confirm Merkle-path integrity from the bundle alone, but the
   * checkpoint signature itself requires the shared HMAC secret which
   * the customer holds out-of-band.
   * ``"tail_records_excluded"`` = some records in the date range have
   * not been sealed into a checkpoint yet; they were not included.
   */
  warnings: string[];
  date_range: { start: string; end: string };
}

export interface EvidenceExportRequest {
  start_date?: string;
  end_date?: string;
  preview?: false;
}

// ── Merkle proof payload (Wave 3B.2 — for in-browser verification) ──────
//
// Returned by ``GET /v1/records/{id}/merkle-proof``. Mirrors the
// ``MerkleProofPayload`` shape from ``backend/app/services/merkle_proof.py``
// verbatim so the in-browser Merkle walker doesn't drift from the
// canonical proof generator.

export interface MerklePathStep {
  sibling_hash: string;
  direction: "left" | "right";
}

export interface MerkleProofPayload {
  action_record_id: string;
  action_record_canonical: string;
  leaf_hash: string;
  merkle_path: MerklePathStep[];
  merkle_root: string;
  checkpoint_id: string;
  checkpoint_signed_at: string;
  // Phase 3 follow-up: ``previous_hash`` is the predecessor leaf in
  // the per-org chain (literal sentinel ``"GENESIS"`` for the first
  // record). Required so an in-browser or offline verifier can
  // enforce ``sha256(previous_hash + canonical) == leaf_hash`` rather
  // than just folding the Merkle path. Added to the backend payload
  // in the same wave; frontend type stays in sync.
  previous_hash: string;
  kms_key_id: string;
  kms_signature: string;
  kms_algorithm: string;
  kms_public_key_pem: string | null;
}

// ── Phase 3 Wave 3D.3 — Off-Vera S3 mirror configuration ─────────────────
//
// Mirrors backend/app/routes/dashboard_s3_mirror.py response models.
// Used by the Settings → Off-Vera evidence mirror sub-page.

export type S3ExportStatus = "pending" | "success" | "failure" | "skipped";

export interface S3MirrorRecentExport {
  id: string;
  checkpoint_id: string;
  status: S3ExportStatus;
  exported_at: string | null;
  duration_ms: number | null;
  record_count: number | null;
  reason: string | null;
}

export interface S3MirrorConfig {
  arn: string | null;
  probe_enabled: boolean;
  iam_role_supported: boolean;
  success_total: number;
  failure_total: number;
  skipped_total: number;
  pending_total: number;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_failure_reason: string | null;
  recent_exports: S3MirrorRecentExport[];
}

export interface S3MirrorValidateInput {
  arn: string;
  role_arn?: string | null;
}

export interface S3MirrorValidateResponse {
  ok: boolean;
  can_put: boolean;
  can_get: boolean;
  stub: boolean;
}

// Flat-error envelope for /v1/dashboard/s3-export-arn/{validate,probe} +
// PUT failures. Matches the existing PR #201 pattern: code + message
// at top level, optional hint, never a nested {"detail": {...}}.
export interface S3MirrorErrorDetail {
  code: string;
  message: string;
  hint?: string;
}

// ───────────────────────────────────────────────────────────────────────
// Phase 3 Wave 3D.1 — Home page Chain Integrity tile.
//
// Single-call aggregate that answers "is our evidence trail intact right
// now?". Backend: ``GET /v1/dashboard/chain-integrity`` →
// ``app.schemas.chain_integrity.ChainIntegrityResponse``.
// ───────────────────────────────────────────────────────────────────────

export type ChainIntegrityStatus = "ok" | "warn" | "error";

export type CheckpointCadence = "hourly" | "daily" | "disabled";

export interface LatestCheckpointSummary {
  checkpoint_id: string;
  /** ISO-8601 timestamp without timezone (UTC by contract). */
  sealed_at: string;
  sequence: number;
  record_count: number;
}

export interface KmsKeySummary {
  key_id: string;
  algorithm: string;
}

export interface ChainIntegrityResponse {
  status: ChainIntegrityStatus;
  /** Regulator-ready, plain-English one-liner. */
  message: string;
  latest_checkpoint: LatestCheckpointSummary | null;
  chain_depth: number;
  kms_key: KmsKeySummary | null;
  cadence: CheckpointCadence;
}
