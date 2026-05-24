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
