import { getApiKey, clearApiKey } from "./auth";
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
  ApiKey,
  ApiKeyCreateResponse,
  ApiKeyCreateInput,
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

function getHeaders(): HeadersInit {
  const apiKey = getApiKey();
  return {
    "Content-Type": "application/json",
    ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
  };
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: { ...getHeaders(), ...options?.headers },
  });

  if (response.status === 401) {
    clearApiKey();
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
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

export function updateAlertEmail(alert_email: string | null): Promise<Organization> {
  return request("/v1/organizations/me/alert-email", {
    method: "PATCH",
    body: JSON.stringify({ alert_email }),
  });
}

// API Keys
export function getApiKeys(): Promise<ApiKey[]> {
  return request("/v1/api-keys");
}

export function createApiKeyRequest(input: ApiKeyCreateInput): Promise<ApiKeyCreateResponse> {
  return request("/v1/api-keys", { method: "POST", body: JSON.stringify(input) });
}

export function revokeApiKey(id: string): Promise<{ detail: string }> {
  return request(`/v1/api-keys/${id}`, { method: "DELETE" });
}

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
    headers: getHeaders(),
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
