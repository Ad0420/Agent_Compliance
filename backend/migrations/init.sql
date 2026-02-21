-- ============================================================
-- ACTION LEDGER - Database Schema
-- ============================================================
-- Design principles:
--   1. action_records is APPEND-ONLY (enforced by trigger)
--   2. Hash chain: each record links to the previous via hash
--   3. Lean typed columns for indexed/queryable fields
--   4. JSONB escape hatches for flexible/rich data
--   5. One chain_state row per org tracks the head of the chain
-- ============================================================

-- Enable pgcrypto for UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- ORGANIZATIONS
-- Root tenant. Every resource belongs to one org.
-- ============================================================
CREATE TABLE organizations (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- API KEYS
-- Scoped credentials for SDK and API access.
-- We store the hash, never the plaintext key.
-- ============================================================
CREATE TABLE api_keys (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID        NOT NULL REFERENCES organizations(id),
    name        TEXT        NOT NULL,                          -- human label, e.g. "production key"
    key_hash    TEXT        NOT NULL UNIQUE,                   -- SHA-256 of the actual key
    key_prefix  TEXT        NOT NULL,                          -- first 8 chars, shown in UI: "al_live_abcd1234..."
    permissions TEXT[]      NOT NULL DEFAULT '{write,read}',   -- 'read' | 'write' | 'admin'
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at  TIMESTAMPTZ                                    -- NULL = active
);

CREATE INDEX idx_api_keys_org ON api_keys(org_id);
CREATE INDEX idx_api_keys_hash ON api_keys(key_hash);

-- ============================================================
-- AGENTS
-- A registered AI agent belonging to an org.
-- ============================================================
CREATE TABLE agents (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID        NOT NULL REFERENCES organizations(id),
    name        TEXT        NOT NULL,                          -- e.g. "invoice-processor"
    description TEXT,
    metadata    JSONB       NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(org_id, name)                                       -- agent names unique per org
);

CREATE INDEX idx_agents_org ON agents(org_id);

-- ============================================================
-- CHAIN STATE
-- Tracks the current head of the hash chain per org.
-- Used for atomic chain-building: new record reads this first.
-- ============================================================
CREATE TABLE chain_state (
    org_id          UUID        PRIMARY KEY REFERENCES organizations(id),
    latest_sequence BIGINT      NOT NULL DEFAULT 0,
    latest_hash     TEXT        NOT NULL DEFAULT 'GENESIS',   -- seed value for first record
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- ACTION RECORDS
-- The core of the system. Immutable once inserted.
-- ============================================================
CREATE TABLE action_records (
    -- ── Identity & Integrity ──────────────────────────────
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id           UUID        NOT NULL REFERENCES organizations(id),
    sequence_number  BIGINT      NOT NULL,                    -- position in chain, per org
    previous_hash    TEXT        NOT NULL,                    -- hash of previous record (or 'GENESIS')
    record_hash      TEXT        NOT NULL,                    -- SHA-256 of this record's canonical content
    recorded_at      TIMESTAMPTZ NOT NULL DEFAULT now(),      -- server-side receipt time

    -- ── Authorization ─────────────────────────────────────
    authorized_by    TEXT        NOT NULL,                    -- human user ID who authorized the agent
    authorization_scope TEXT,                                 -- free-text: what scope was granted
    delegation_chain JSONB       NOT NULL DEFAULT '[]',       -- [{role, user_id, granted_at}, ...]

    -- ── Agent Identity ────────────────────────────────────
    agent_id         UUID        REFERENCES agents(id),       -- nullable: agent auto-created on first action
    agent_name       TEXT        NOT NULL,                    -- denormalized for fast queries
    agent_version    TEXT,
    model_id         TEXT,                                    -- e.g. "gpt-4o", "claude-3-5-sonnet"
    model_version    TEXT,
    framework        TEXT,                                    -- e.g. "langchain", "crewai"
    framework_version TEXT,

    -- ── Action Details ────────────────────────────────────
    action_type      TEXT        NOT NULL,                    -- "api_call" | "db_write" | "decision" | "notification" | ...
    action_name      TEXT        NOT NULL,                    -- e.g. "approve_invoice"
    action_description TEXT,
    action_timestamp TIMESTAMPTZ NOT NULL,                    -- when action occurred (client clock)
    target_system    TEXT,                                    -- e.g. "SAP", "Stripe"
    target_resource  TEXT,                                    -- e.g. "invoice/12345"

    -- ── Result ────────────────────────────────────────────
    result           TEXT        NOT NULL                     -- "success" | "failure" | "partial" | "pending"
                     CHECK (result IN ('success', 'failure', 'partial', 'pending')),
    error_message    TEXT,
    duration_ms      INTEGER,

    -- ── Flexible JSONB blobs ──────────────────────────────
    -- These fields hold rich data that varies per action type.
    -- Top-level keys are documented but not schema-enforced.
    input_data       JSONB       NOT NULL DEFAULT '{}',       -- what data the agent received
    policies_applied JSONB       NOT NULL DEFAULT '[]',       -- rules / policies in effect
    environment      JSONB       NOT NULL DEFAULT '{}',       -- prod/staging, region, etc.
    reasoning        JSONB       NOT NULL DEFAULT '{}',       -- {type, steps, alternatives, confidence}
    outcome          JSONB       NOT NULL DEFAULT '{}',       -- {state_before, state_after, side_effects}
    metadata         JSONB       NOT NULL DEFAULT '{}',       -- custom org-specific fields

    -- ── Optional Cryptographic Signature ─────────────────
    signature        TEXT,                                    -- base64-encoded signature (optional)

    -- ── Chain integrity constraint ────────────────────────
    UNIQUE(org_id, sequence_number)                           -- no gaps, no duplicates in chain
);

-- ── Indexes ───────────────────────────────────────────────
-- Optimise the most common query patterns

-- Primary chain traversal
CREATE INDEX idx_ar_org_seq    ON action_records(org_id, sequence_number DESC);

-- Time-range queries (most common dashboard filter)
CREATE INDEX idx_ar_org_time   ON action_records(org_id, action_timestamp DESC);
CREATE INDEX idx_ar_recorded   ON action_records(org_id, recorded_at DESC);

-- Filter by agent
CREATE INDEX idx_ar_agent      ON action_records(org_id, agent_name);

-- Filter by action type / name
CREATE INDEX idx_ar_action     ON action_records(org_id, action_type, action_name);

-- Filter by result
CREATE INDEX idx_ar_result     ON action_records(org_id, result);

-- Filter by authorizer
CREATE INDEX idx_ar_authorized ON action_records(org_id, authorized_by);

-- Hash lookups (verification)
CREATE INDEX idx_ar_hash       ON action_records(record_hash);

-- Full-text search across action_name + target_resource
CREATE INDEX idx_ar_fts ON action_records
    USING GIN (to_tsvector('english', action_name || ' ' || coalesce(target_resource, '') || ' ' || coalesce(action_description, '')));

-- GIN index for JSONB queries
CREATE INDEX idx_ar_input_data ON action_records USING GIN (input_data);
CREATE INDEX idx_ar_metadata   ON action_records USING GIN (metadata);

-- ============================================================
-- APPEND-ONLY ENFORCEMENT
-- These triggers make action_records tamper-proof at the DB level.
-- Even if application code has a bug, the DB will refuse mutations.
-- ============================================================
CREATE OR REPLACE FUNCTION enforce_append_only()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'action_records is an append-only ledger. UPDATE and DELETE are not permitted. '
        'Record ID: %, Sequence: %', OLD.id, OLD.sequence_number;
    RETURN NULL;
END;
$$;

CREATE TRIGGER no_update_action_records
    BEFORE UPDATE ON action_records
    FOR EACH ROW EXECUTE FUNCTION enforce_append_only();

CREATE TRIGGER no_delete_action_records
    BEFORE DELETE ON action_records
    FOR EACH ROW EXECUTE FUNCTION enforce_append_only();

-- Also protect chain_state from direct sequence manipulation
CREATE OR REPLACE FUNCTION enforce_chain_state_monotonic()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.latest_sequence < OLD.latest_sequence THEN
        RAISE EXCEPTION
            'chain_state sequence can only increase. '
            'Attempted to set % from %', NEW.latest_sequence, OLD.latest_sequence;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER chain_state_monotonic
    BEFORE UPDATE ON chain_state
    FOR EACH ROW EXECUTE FUNCTION enforce_chain_state_monotonic();

-- ============================================================
-- SEED: Create a default dev organization (convenience only)
-- Remove or replace before production.
-- ============================================================
INSERT INTO organizations (id, name)
VALUES ('00000000-0000-0000-0000-000000000001', 'Dev Org');

INSERT INTO chain_state (org_id, latest_sequence, latest_hash)
VALUES ('00000000-0000-0000-0000-000000000001', 0, 'GENESIS');
