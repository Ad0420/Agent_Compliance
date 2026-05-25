import { getClerkToken } from "./clerk-token";
import type {
  HealthResponse,
  Organization,
  ActionListResponse,
  ActionRecord,
  ActionQueryParams,
  ChainVerification,
  RecordVerification,
  CheckpointListResponse,
  Checkpoint,
  CheckpointVerifyAllResponse,
  Agent,
  Policy,
  PolicyListResponse,
  PolicyCreateInput,
  PolicyUpdateInput,
  PolicyViolation,
  ViolationListResponse,
  ViolationQueryParams,
  Approval,
  ApprovalListResponse,
  ApprovalCreateInput,
  ApprovalDecisionInput,
  ApprovalQueryParams,
  Customer,
  CustomerAgentsResponse,
  CustomerListResponse,
  CustomerQueryParams,
  CustomerDecision,
  CustomerDecisionsResponse,
  CustomerDecisionsQueryParams,
  Ruling,
  RulingEffect,
  WebhookDeliverySummary,
  DecisionWebhookStatus,
  WizardAnswersResponse,
  WizardAnswersSubmission,
  BAAUploadInput,
  BAAUploadResponse,
  WebhookDeliveriesQueryParams,
  WebhookDeliveriesResponse,
  WebhookDeliveryReplayResponse,
  WebhookListResponse,
} from "./api-types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function getHeaders(): Promise<HeadersInit> {
  // Dashboard auth = Clerk session token (E4). The backend's
  // `require_permission` accepts either this or an `al_*` API key; the SDK
  // keeps using API keys, the dashboard does not.
  const token = await getClerkToken();
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = await getHeaders();
  const response = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: { ...headers, ...options?.headers },
  });

  if (response.status === 401) {
    // Don't auto-redirect: a 401 with a valid Clerk session means the
    // backend membership isn't ready yet (webhook race) or the session was
    // revoked server-side. Redirecting to /login would loop because Clerk
    // sees the active session and bounces back to /dashboard. Let React
    // Query surface the error; ProtectedRoute handles "no session at all".
    throw new ApiError(401, "Unauthorized");
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Request failed" }));
    throw new ApiError(response.status, error.detail || `Request failed (${response.status})`);
  }

  if (response.status === 204) return undefined as T;
  return response.json();
}

function buildQuery(params?: Record<string, string | number | undefined>): string {
  if (!params) return "";
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== "");
  if (entries.length === 0) return "";
  const searchParams = new URLSearchParams();
  entries.forEach(([k, v]) => searchParams.set(k, String(v)));
  return `?${searchParams.toString()}`;
}

// Health
export function getHealth(): Promise<HealthResponse> {
  return request("/health");
}

// Actions
export function getActions(params?: ActionQueryParams): Promise<ActionListResponse> {
  return request(`/v1/actions${buildQuery(params as Record<string, string | number | undefined>)}`);
}

export function getAction(id: string): Promise<ActionRecord> {
  return request(`/v1/actions/${id}`);
}

// Verification
export function verifyChain(startSeq?: number, endSeq?: number): Promise<ChainVerification> {
  return request(`/v1/verify${buildQuery({ start_seq: startSeq, end_seq: endSeq })}`);
}

export function verifyRecord(id: string): Promise<RecordVerification> {
  return request(`/v1/verify/${id}`);
}

// Checkpoints
export function getCheckpoints(): Promise<CheckpointListResponse> {
  return request("/v1/verify/checkpoints");
}

export function createCheckpoint(): Promise<Checkpoint> {
  return request("/v1/verify/checkpoints", { method: "POST" });
}

export function verifyAllCheckpoints(): Promise<CheckpointVerifyAllResponse> {
  return request("/v1/verify/checkpoints/verify", { method: "POST" });
}

// Agents
export function getAgents(): Promise<Agent[]> {
  return request("/v1/agents");
}

export function getAgent(id: string): Promise<Agent> {
  return request(`/v1/agents/${id}`);
}

// Organization
export function getOrganization(): Promise<Organization> {
  return request("/v1/organizations/me");
}

// Customers (Phase 1 PR 2 — list + per-customer fetch; PR 13 — agents + BAA upload)
export function getCustomers(params?: CustomerQueryParams): Promise<CustomerListResponse> {
  // ``with_counts`` is a boolean; URLSearchParams stringifies booleans
  // verbatim ("true"/"false") and FastAPI's query-param coercion accepts
  // both. Passing the raw boolean through buildQuery keeps the call sites
  // ergonomic.
  return request(
    `/v1/customers${buildQuery(params as Record<string, string | number | undefined>)}`,
  );
}

export function getCustomer(tenant_id: string): Promise<Customer> {
  return request(`/v1/customers/${encodeURIComponent(tenant_id)}`);
}

export function getCustomerAgents(
  tenant_id: string,
): Promise<CustomerAgentsResponse> {
  return request(`/v1/customers/${encodeURIComponent(tenant_id)}/agents`);
}

export interface CustomerPatchInput {
  display_name?: string | null;
  contact_email?: string | null;
  contact_name?: string | null;
  jurisdictions?: string[] | null;
}

export function patchCustomer(
  tenant_id: string,
  input: CustomerPatchInput,
): Promise<Customer> {
  return request(`/v1/customers/${encodeURIComponent(tenant_id)}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function uploadCustomerBaa(
  tenant_id: string,
  input: BAAUploadInput,
): Promise<BAAUploadResponse> {
  return request(`/v1/customers/${encodeURIComponent(tenant_id)}/baa`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

// ── Wave 2C PR C1 — Customer detail Decisions tab ─────────────────────────
//
// No dedicated `/v1/customers/{tenant_id}/decisions` endpoint exists in
// Phase 2 (a backend-side join lives in a later PR). Until then we adapt
// the existing /v1/actions?tenant_id=<id> path: ActionRecord rows already
// carry tenant_id (Phase 1 PR 13), and the Ruling / webhook delivery /
// HITL expiry will ride on each row's ``reasoning`` JSON.
//
// IMPORTANT — backend wiring status (as of PR C1 landing):
//   * ``reasoning.gate_ruling`` — NOT yet written by the gates evaluator
//     or ClinicalScribePack. Tracked as a follow-up Wave 2C backend slice
//     ("mirror Ruling into ActionRecord.reasoning on every gate run").
//   * ``reasoning.webhook_delivery`` — NOT yet written by the dispatcher
//     (Wave 2B PR A3 writes the WebhookDelivery row but does not
//     denormalise the summary onto the originating ActionRecord). Same
//     follow-up backend slice as above.
//   * ``reasoning.hitl_expires_at`` — NOT yet written; depends on the
//     approval dispatcher copying ``Approval.expires_at`` into the
//     request ActionRecord's reasoning blob.
//
// Until those backend slices land, every CustomerDecision will be
// projected with ``ruling: null`` / ``webhook_delivery: null`` /
// ``hitl_expires_at: null``. ``DecisionRow`` handles every null branch
// (renders the "No gate" INFO badge + no webhook dot + no HITL countdown)
// so the tab is functional today — but the headline value (Ruling +
// delivery) only lights up once the backend mirrors are wired. Out of
// scope per the PR C1 spec; this comment is the contract trail so the
// follow-up backend PR knows exactly which keys to populate.
//
// Extracting these views client-side keeps the wire contract small and
// the join trivial — the page only renders 50 rows at a time.

const WEBHOOK_BACKEND_MAX_ATTEMPTS = 7; // mirrors services/webhooks.py

function _coerceRuling(reasoning: Record<string, unknown>): Ruling | null {
  // Ruling rides under reasoning.gate_ruling. ClinicalScribePack and the
  // generic evaluator both write this key; absence = no gate ran.
  const raw = (reasoning as { gate_ruling?: unknown }).gate_ruling;
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const effect = r.effect;
  if (effect !== "allow" && effect !== "require_hitl" && effect !== "block") {
    // Unknown effect = treat as no Ruling rather than crash the row.
    return null;
  }
  return {
    effect: effect as RulingEffect,
    reason: typeof r.reason === "string" ? r.reason : "",
    reason_detail:
      typeof r.reason_detail === "string" ? r.reason_detail : null,
    citation: typeof r.citation === "string" ? r.citation : null,
    review_id: typeof r.review_id === "string" ? r.review_id : null,
    fix_url: typeof r.fix_url === "string" ? r.fix_url : null,
    required_role:
      typeof r.required_role === "string" ? r.required_role : null,
    gate_name: typeof r.gate_name === "string" ? r.gate_name : null,
  };
}

function _coerceWebhookDelivery(
  reasoning: Record<string, unknown>,
): WebhookDeliverySummary | null {
  const raw = (reasoning as { webhook_delivery?: unknown }).webhook_delivery;
  if (!raw || typeof raw !== "object") return null;
  const d = raw as Record<string, unknown>;
  const status = d.status;
  if (
    status !== "delivered" &&
    status !== "pending" &&
    status !== "retrying" &&
    status !== "aborted"
  ) {
    return null;
  }
  return {
    status: status as DecisionWebhookStatus,
    attempt_count: typeof d.attempt_count === "number" ? d.attempt_count : 0,
    max_attempts:
      typeof d.max_attempts === "number"
        ? d.max_attempts
        : WEBHOOK_BACKEND_MAX_ATTEMPTS,
    next_retry_at:
      typeof d.next_retry_at === "string" ? d.next_retry_at : null,
    last_status_code:
      typeof d.last_status_code === "number" ? d.last_status_code : null,
    succeeded_at: typeof d.succeeded_at === "string" ? d.succeeded_at : null,
    aborted_at: typeof d.aborted_at === "string" ? d.aborted_at : null,
  };
}

function _coerceHitlExpiresAt(
  reasoning: Record<string, unknown>,
): string | null {
  // Approval.expires_at is mirrored into the reasoning blob by the
  // gate dispatcher when effect=require_hitl. Absent for ALLOW/BLOCK.
  const v = (reasoning as { hitl_expires_at?: unknown }).hitl_expires_at;
  return typeof v === "string" ? v : null;
}

function _actionRecordToDecision(rec: ActionRecord): CustomerDecision {
  const reasoning = rec.reasoning ?? {};
  return {
    id: rec.id,
    sequence_number: rec.sequence_number,
    action_timestamp: rec.action_timestamp,
    agent_name: rec.agent_name,
    action_name: rec.action_name,
    action_type: rec.action_type,
    result: rec.result,
    ruling: _coerceRuling(reasoning),
    webhook_delivery: _coerceWebhookDelivery(reasoning),
    hitl_expires_at: _coerceHitlExpiresAt(reasoning),
  };
}

export async function getCustomerDecisions(
  tenant_id: string,
  params?: CustomerDecisionsQueryParams,
): Promise<CustomerDecisionsResponse> {
  // Adapter path: GET /v1/actions?tenant_id=<id>, then project each
  // ActionRecord into the CustomerDecision shape. Limit/offset flow
  // straight through — the underlying endpoint accepts both.
  const query: ActionQueryParams = {
    tenant_id,
    limit: params?.limit ?? 50,
    offset: params?.offset ?? 0,
  };
  const raw = await getActions(query);
  return {
    decisions: raw.records.map(_actionRecordToDecision),
    total: raw.total,
    limit: raw.limit,
    offset: raw.offset,
  };
}

export function updateAlertEmail(alert_email: string | null): Promise<Organization> {
  return request("/v1/organizations/me/alert-email", {
    method: "PATCH",
    body: JSON.stringify({ alert_email }),
  });
}

// Onboarding wizard (Phase 1 PR 14, Stream F item F5).
// Five-question modal sequence persisted on the Organization row.
// GET is `read`, POST is `admin` — see backend organizations route.
export function getWizardAnswers(): Promise<WizardAnswersResponse> {
  return request("/v1/organizations/me/wizard-answers");
}

export function submitWizardAnswers(
  body: WizardAnswersSubmission,
): Promise<WizardAnswersResponse> {
  return request("/v1/organizations/me/wizard-answers", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// API Keys are managed via the /api-keys page (Clerk-gated, calls
// /v1/dashboard/api-keys through Next.js route handlers). The legacy
// /v1/api-keys endpoints were removed post-E4 cleanup.

// Policies
export function getPolicies(is_active?: boolean): Promise<PolicyListResponse> {
  return request(`/v1/policies${buildQuery({ is_active: is_active === undefined ? undefined : String(is_active) })}`);
}

export function createPolicy(input: PolicyCreateInput): Promise<Policy> {
  return request("/v1/policies", { method: "POST", body: JSON.stringify(input) });
}

export function updatePolicy(id: string, input: PolicyUpdateInput): Promise<Policy> {
  return request(`/v1/policies/${id}`, { method: "PATCH", body: JSON.stringify(input) });
}

export function deletePolicy(id: string): Promise<void> {
  return request(`/v1/policies/${id}`, { method: "DELETE" });
}

// Violations
export function getViolations(params?: ViolationQueryParams): Promise<ViolationListResponse> {
  return request(`/v1/policies/violations${buildQuery(params as Record<string, string | number | undefined>)}`);
}

export function resolveViolation(id: string, resolved_by?: string): Promise<PolicyViolation> {
  return request(`/v1/policies/violations/${id}/resolve`, {
    method: "PATCH",
    body: JSON.stringify({ resolved_by: resolved_by ?? null }),
  });
}

// Approvals (Human-in-the-Loop)
export function getApprovals(params?: ApprovalQueryParams): Promise<ApprovalListResponse> {
  return request(`/v1/approvals${buildQuery(params as Record<string, string | number | undefined>)}`);
}

export function getApproval(id: string): Promise<Approval> {
  return request(`/v1/approvals/${id}`);
}

export function createApproval(input: ApprovalCreateInput): Promise<Approval> {
  return request("/v1/approvals", { method: "POST", body: JSON.stringify(input) });
}

export function decideApproval(id: string, input: ApprovalDecisionInput): Promise<Approval> {
  return request(`/v1/approvals/${id}/decide`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function cancelApproval(id: string): Promise<Approval> {
  return request(`/v1/approvals/${id}/cancel`, { method: "POST" });
}

// Register
export interface RegisterInput {
  org_name: string;
}

export interface RegisterResult {
  org_id: string;
  org_name: string;
  api_key: string;
  key_prefix: string;
  created_at: string;
}

export function registerOrg(input: RegisterInput): Promise<RegisterResult> {
  return request("/v1/register", { method: "POST", body: JSON.stringify(input) });
}

// Export
export interface ExportParams {
  start_date?: string;
  end_date?: string;
  agent_name?: string;
  action_type?: string;
  result?: string;
  limit?: number;
}

async function downloadFile(path: string, filename: string): Promise<void> {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: await getHeaders(),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Export failed" }));
    throw new ApiError(response.status, error.detail || `Export failed (${response.status})`);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function exportCsv(params?: ExportParams): Promise<void> {
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  const query = buildQuery(params as Record<string, string | number | undefined>);
  return downloadFile(`/v1/export/csv${query}`, `vera_export_${timestamp}.csv`);
}

export function exportPdf(params?: ExportParams): Promise<void> {
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  const query = buildQuery(params as Record<string, string | number | undefined>);
  return downloadFile(`/v1/export/pdf${query}`, `vera_report_${timestamp}.pdf`);
}

// Webhook subscriptions + delivery health (Phase 2 Wave 2C PR C3).
// Admin-only on the backend (require_permission("admin")). The dashboard
// uses these to render the Settings → Integrations webhook health panel.
export function getWebhooks(): Promise<WebhookListResponse> {
  return request("/v1/webhooks");
}

export function getWebhookDeliveries(
  webhook_id: string,
  params?: WebhookDeliveriesQueryParams,
): Promise<WebhookDeliveriesResponse> {
  const query = buildQuery(
    params as Record<string, string | number | undefined>,
  );
  return request(
    `/v1/webhooks/${encodeURIComponent(webhook_id)}/deliveries${query}`,
  );
}

export function replayWebhookDelivery(
  webhook_id: string,
  delivery_id: string,
): Promise<WebhookDeliveryReplayResponse> {
  return request(
    `/v1/webhooks/${encodeURIComponent(webhook_id)}/deliveries/${encodeURIComponent(delivery_id)}/replay`,
    { method: "POST" },
  );
}
