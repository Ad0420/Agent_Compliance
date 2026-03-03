// TypeScript interfaces matching backend Pydantic schemas

export interface HealthResponse {
  status: "ok" | "degraded";
  environment: string;
  database: boolean;
}

export interface Organization {
  id: string;
  name: string;
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
