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
  CustomerDecisionsResponse,
  CustomerDecisionsQueryParams,
  WizardAnswersResponse,
  WizardAnswersSubmission,
  BAAUploadInput,
  BAAUploadResponse,
  WebhookDeliveriesQueryParams,
  WebhookDeliveriesResponse,
  WebhookDeliveryReplayResponse,
  WebhookListResponse,
  CompleteReviewInput,
  CompleteReviewResponse,
} from "./api-types";

export class ApiError extends Error {
  public status: number;
  /**
   * Raw `detail` value as returned by the backend. For most endpoints this
   * is a string and ``message`` is the same value; for endpoints that
   * return a structured envelope (e.g. ``POST /v1/reviews/{id}/complete``
   * → 403 with ``{code, required_role, reviewer_role, ...}``) callers can
   * narrow on the shape via type guards to render an actionable error.
   */
  public detail: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.name = "ApiError";
    this.detail = detail ?? message;
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
    const detail = error?.detail;
    // ``detail`` is a string in the common case (FastAPI's default
    // HTTPException) and an object for endpoints that surface a
    // structured envelope (e.g. POST /v1/reviews/{id}/complete on 403).
    // We pass both: ``message`` is always a string for ``Error`` super,
    // ``detail`` is the original payload so callers can narrow.
    const message =
      typeof detail === "string"
        ? detail
        : detail && typeof detail === "object" && "detail" in detail &&
            typeof (detail as { detail?: unknown }).detail === "string"
          ? (detail as { detail: string }).detail
          : `Request failed (${response.status})`;
    throw new ApiError(response.status, message, detail);
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

// ── Wave 2C PR C1.5 — Customer detail Decisions tab (backend-served) ──────
//
// C1 originally adapted ``GET /v1/actions?tenant_id=<id>`` client-side
// because no dedicated endpoint existed. The /review on C1 caught that
// the adapter read ``reasoning.gate_ruling`` / ``reasoning.webhook_delivery``
// / ``reasoning.hitl_expires_at`` from ``ActionRecord`` — keys the
// backend never wrote. C1.5 fixes that by serving the join from
// ``GET /v1/customers/{tenant_id}/decisions``, which assembles the
// composite from ``ActionRecord`` ⋈ ``Approval`` ⋈ ``WebhookDelivery``
// server-side (see ``backend/app/services/decisions.py``).
//
// Hook signature unchanged so ``useCustomerDecisions`` consumers keep
// working without modification — only the underlying transport changed.
//
// ALLOW-ruling limitation (carried over from C1.5 backend service): the
// dashboard receives ``ruling: null`` for actions whose gate decided
// ALLOW. Surfacing those rulings needs an out-of-PR follow-up (SDK-side
// denormalisation onto ActionRecord, or a new ``gate_evaluations``
// table). The Decisions tab's ``DecisionRow`` already renders the
// null-ruling branch as a "No gate" INFO badge, so the UI degrades
// gracefully.

export function getCustomerDecisions(
  tenant_id: string,
  params?: CustomerDecisionsQueryParams,
): Promise<CustomerDecisionsResponse> {
  const query = buildQuery({
    limit: params?.limit,
    offset: params?.offset,
  });
  return request(
    `/v1/customers/${encodeURIComponent(tenant_id)}/decisions${query}`,
  );
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

// ── Wave 2D PR C2 — Review queue page ───────────────────────────────────
//
// Wraps the A4 endpoint ``POST /v1/reviews/{review_id}/complete``. The
// dashboard uses this as the alt channel for HITL completion when the
// customer hasn't wired a webhook receiver (per
// v1-implementation-plan.md §Phase 2 Dashboard, line 120 + 127).
//
// Status codes the dashboard surfaces inline (see complete-review-form.tsx):
//   * 200 — decision recorded, queue refresh
//   * 403 — reviewer role insufficient (detail is ReviewerInsufficientDetail)
//   * 404 — review missing (shouldn't happen post-list-load; treat as 409)
//   * 409 — already resolved OR attestation_conflict (Wave 2D A6)
//   * 410 — review expired
// All non-200s arrive as ``ApiError`` with the structured ``detail`` blob
// preserved for narrowing.
export function completeReview(
  review_id: string,
  input: CompleteReviewInput,
): Promise<CompleteReviewResponse> {
  return request(`/v1/reviews/${encodeURIComponent(review_id)}/complete`, {
    method: "POST",
    body: JSON.stringify(input),
  });
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
