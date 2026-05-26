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
  CustomerChainSummary,
  CustomerListResponse,
  CustomerQueryParams,
  CustomerDecisionsResponse,
  CustomerDecisionsQueryParams,
  EvidenceExportPreview,
  MerkleProofPayload,
  WizardAnswersResponse,
  WizardAnswersSubmission,
  BAAUploadInput,
  BAAUploadResponse,
  WebhookDeliveriesQueryParams,
  WebhookDeliveriesResponse,
  WebhookDeliveryReplayResponse,
  WebhookListResponse,
  // W2.2 — CompleteReviewInput / CompleteReviewResponse kept in
  // api-types.ts for SDK + future in-band UI parity but not imported
  // here: the dashboard wrapper for POST /v1/reviews/{id}/complete was
  // removed when the Review queue went read-only per HIPAA scope
  // reduction. See lib/api-types.ts for the wire-shape contract.
  S3MirrorConfig,
  S3MirrorValidateInput,
  S3MirrorValidateResponse,
  ChainIntegrityResponse,
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
    // Three shapes flow through here:
    //   1. FastAPI's default ``{"detail": "<string>"}`` — common case.
    //   2. Structured wrapped ``{"detail": {"code": ..., "detail": "..."}}``
    //      (e.g. POST /v1/reviews/{id}/complete on 403). Callers narrow
    //      on ``detail`` via type guards.
    //   3. Flat error envelope (PR #201 pattern) — ``{"code": "...",
    //      "message": "...", "hint": "..."}`` at TOP level, no nesting.
    //      Used by /v1/dashboard/s3-export-arn/* and the SDK-side
    //      off-vera-mirror/validate route. Read ``error.message``
    //      directly so the toast renders the structured copy.
    // ``message`` is always a string for ``Error`` super; ``detail`` is
    // the original payload (or the flat-envelope object itself when
    // detail was absent) so callers can narrow on either shape.
    const message =
      typeof detail === "string"
        ? detail
        : detail && typeof detail === "object" && "detail" in detail &&
            typeof (detail as { detail?: unknown }).detail === "string"
          ? (detail as { detail: string }).detail
          : typeof error?.message === "string"
            ? error.message
            : `Request failed (${response.status})`;
    // When the response is a flat envelope, ``detail`` is undefined but
    // the structured fields sit on ``error`` itself. Promote ``error``
    // so callers can ``apiError.detail.code`` regardless of which shape
    // the backend used.
    const carrier = detail ?? error;
    throw new ApiError(response.status, message, carrier);
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

// Phase 3 Wave 3D.1 — Home Chain Integrity tile aggregate.
export function getChainIntegrity(): Promise<ChainIntegrityResponse> {
  return request("/v1/dashboard/chain-integrity");
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

// ── Wave 3D.2 — Customer Verification & Evidence Trail panel ────────────

export function getCustomerChainSummary(
  tenant_id: string,
): Promise<CustomerChainSummary> {
  return request(
    `/v1/customers/${encodeURIComponent(tenant_id)}/chain-summary`,
  );
}

export interface EvidenceExportInput {
  start_date?: string;
  end_date?: string;
}

export function previewEvidenceExport(
  tenant_id: string,
  input: EvidenceExportInput,
): Promise<EvidenceExportPreview> {
  return request(
    `/v1/customers/${encodeURIComponent(tenant_id)}/evidence-export`,
    {
      method: "POST",
      body: JSON.stringify({ ...input, preview: true }),
    },
  );
}

/**
 * Stream the evidence bundle to a browser download.
 *
 * Bundle generation can be slow for large date ranges. The async
 * fetch yields a single Blob; the caller surface drives a normal
 * "Save as…" download via an in-memory object URL — same pattern as
 * ``exportCsv`` / ``exportPdf``.
 *
 * Returns the suggested filename the backend put in
 * ``Content-Disposition`` so the caller can show it as a confirmation
 * line ("Downloaded ``vera-evidence-cleveland_clinic-2026-02-26_to_
 * 2026-05-25.tar.gz``").
 */
export async function downloadEvidenceBundle(
  tenant_id: string,
  input: EvidenceExportInput,
): Promise<{ filename: string }> {
  const headers = await getHeaders();
  const response = await fetch(
    `${BASE_URL}/v1/customers/${encodeURIComponent(tenant_id)}/evidence-export`,
    {
      method: "POST",
      headers,
      body: JSON.stringify({ ...input, preview: false }),
    },
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Export failed" }));
    const detail =
      typeof error?.detail === "string"
        ? error.detail
        : error?.code || `Export failed (${response.status})`;
    throw new ApiError(response.status, detail, error);
  }
  const disposition = response.headers.get("content-disposition") || "";
  const match = /filename="([^"]+)"/.exec(disposition);
  const filename = match?.[1] || `vera-evidence-${tenant_id}.tar.gz`;
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  return { filename };
}

export function getMerkleProof(
  action_record_id: string,
): Promise<MerkleProofPayload> {
  return request(
    `/v1/records/${encodeURIComponent(action_record_id)}/merkle-proof`,
  );
}

// ── Phase 4 Wave 1 C3 — Generate audit PDF on Customer detail ────────────
//
// Backed by ``POST /v1/audits/{customer_id}`` (Stream A1 in flight). The
// route returns ``application/pdf`` bytes with a ``Content-Disposition``
// suggesting the filename — we stream that into a browser download
// (same shape as ``downloadEvidenceBundle`` above).
//
// Error envelope (from A1 brief):
//   403 { error: { code: "baa_expired", message: ... } }
//   404 (customer not in caller's org)
//   504 { error: { code: "pdf_render_timeout", message: ... } }
//
// We re-emit ``error.code`` on the thrown ``ApiError.detail`` so the
// modal can map it to inline-banner copy. The exported error-code
// constants below are the contract surface — the modal imports them
// rather than stringly-typing the codes inline.

export const AUDIT_PDF_SECTION_KEYS = [
  "cover",
  "scope",
  "audit_controls",
  "hitl_evidence",
  "demographic_monitoring",
  "workforce_training",
  "baa_chain",
  "technical_appendix",
] as const;

export type AuditPdfSectionKey = (typeof AUDIT_PDF_SECTION_KEYS)[number];

export type AuditPdfBranding = "customer" | "vera-neutral";

export interface AuditPdfInput {
  date_from: string; // YYYY-MM-DD
  date_to: string; // YYYY-MM-DD
  sections: AuditPdfSectionKey[];
  branding: AuditPdfBranding;
}

export const AUDIT_PDF_ERROR_CODES = {
  baaExpired: "baa_expired",
  pdfRenderTimeout: "pdf_render_timeout",
} as const;

/**
 * Read the ``error.code`` field off an ApiError raised by
 * ``generateAuditPdf``. Returns null when the envelope did not carry a
 * structured code so callers can fall back to a generic message.
 *
 * Tolerates both shapes the backend might emit:
 *   - flat envelope: ``{ code: "...", message: "..." }``
 *   - nested envelope: ``{ error: { code: "...", message: "..." } }``
 *
 * The latter is what the A1 brief specifies; the former matches the
 * dashboard's pre-existing flat-envelope convention (PR #201 onwards).
 * Accepting both keeps the modal robust against the precise wire shape
 * A1 lands.
 */
export function readAuditPdfErrorCode(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  const detail = err.detail;
  if (!detail || typeof detail !== "object") return null;
  const flat = (detail as Record<string, unknown>).code;
  if (typeof flat === "string") return flat;
  const nested = (detail as Record<string, unknown>).error;
  if (nested && typeof nested === "object") {
    const code = (nested as Record<string, unknown>).code;
    if (typeof code === "string") return code;
  }
  return null;
}

/**
 * Generate an audit PDF and stream it to a browser download. The
 * backend renders synchronously (~5-30s), so the caller should show a
 * spinner for the duration. Returns the filename the backend suggested
 * via ``Content-Disposition`` so the caller can log / confirm.
 *
 * On non-2xx, throws an ``ApiError`` whose ``detail`` carries the
 * structured error envelope. Use ``readAuditPdfErrorCode`` to map.
 */
export async function generateAuditPdf(
  customer_id: string,
  input: AuditPdfInput,
): Promise<{ filename: string }> {
  const headers = await getHeaders();
  const response = await fetch(
    `${BASE_URL}/v1/audits/${encodeURIComponent(customer_id)}`,
    {
      method: "POST",
      headers,
      body: JSON.stringify(input),
    },
  );
  if (!response.ok) {
    // We don't know whether the backend emits flat ``{code, message}``
    // or nested ``{error: {code, message}}`` — accept both. ``carrier``
    // is the raw envelope so ``readAuditPdfErrorCode`` can narrow.
    const carrier = await response.json().catch(() => null);
    const flatMessage =
      carrier && typeof carrier === "object" && typeof (carrier as Record<string, unknown>).message === "string"
        ? ((carrier as Record<string, unknown>).message as string)
        : null;
    const nestedMessage =
      carrier &&
      typeof carrier === "object" &&
      (carrier as Record<string, unknown>).error &&
      typeof (carrier as Record<string, unknown>).error === "object"
        ? ((carrier as { error: Record<string, unknown> }).error.message as
            | string
            | undefined) ?? null
        : null;
    const message =
      flatMessage ??
      nestedMessage ??
      `Audit PDF generation failed (${response.status})`;
    throw new ApiError(response.status, message, carrier ?? undefined);
  }
  const disposition = response.headers.get("content-disposition") || "";
  const match = /filename="([^"]+)"/.exec(disposition);
  const filename = match?.[1] || `audit-${customer_id}.pdf`;
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  return { filename };
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

// W2.2 — the dashboard wrapper for ``POST /v1/reviews/{id}/complete``
// was removed when the Review queue page went read-only per HIPAA
// scope reduction. The endpoint itself stays — ScribeMD's in-band
// callback path (W2.1) still calls it server-to-server. See
// ``backend/app/routes/reviews.py`` for the live contract and
// ``lib/api-types.ts`` for the wire-shape types (kept so SDK / future
// in-band UIs share the dashboard's TS contract).

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

// ── Phase 3 Wave 3D.3 — Off-Vera S3 mirror configuration ─────────────────
//
// Settings → Off-Vera evidence mirror sub-page. Admin-only writes; admin
// + developer reads (developers need visibility for SDK integration
// debugging). See backend/app/routes/dashboard_s3_mirror.py.

export function getS3MirrorConfig(): Promise<S3MirrorConfig> {
  return request("/v1/dashboard/s3-export-config");
}

export function updateS3MirrorArn(arn: string): Promise<S3MirrorConfig> {
  return request("/v1/dashboard/s3-export-arn", {
    method: "PUT",
    body: JSON.stringify({ arn }),
  });
}

export function clearS3MirrorArn(): Promise<S3MirrorConfig> {
  return request("/v1/dashboard/s3-export-arn", {
    method: "DELETE",
  });
}

export function validateS3MirrorArn(
  input: S3MirrorValidateInput,
): Promise<S3MirrorValidateResponse> {
  return request("/v1/dashboard/s3-export-arn/validate", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function probeS3MirrorArn(
  input: S3MirrorValidateInput,
): Promise<S3MirrorValidateResponse> {
  return request("/v1/dashboard/s3-export-arn/probe", {
    method: "POST",
    body: JSON.stringify(input),
  });
}
