# Vera v1 — Acceptance Testing Runbook

**Audience:** the operator running manual scenario walkthroughs against a
Railway-backed local stack (Phase 2 onward).

**Sibling docs:** [phase2-acceptance-findings.md](phase2-acceptance-findings.md)
(rolled-up findings table).

This is the runbook captured during Phase 2 acceptance. It catalogs every
hiccup encountered, the unblock, and the now-canonical setup so Phase 3+
testing skips the re-discovery loop.

---

## 1. One-time machine setup

Project does NOT use `uv` or Poetry. Plain pip + conda.

```bash
# conda env named `vera` — referenced throughout this doc as
# /opt/anaconda3/envs/vera/bin/python
conda create -n vera python=3.11
conda activate vera

# Backend deps
cd backend && pip install -r requirements.txt && pip install greenlet
# `greenlet` is required by SQLAlchemy async but isn't pinned in requirements.txt.

# Simulator install (editable, from repo root — NOT from a worktree)
cd /Users/priyansh/code/Agent_Compliance && pip install -e simulator/
```

If `pip install -e simulator/` silently no-ops, your cwd is wrong. The setup
points at MAPPING in the editable record and a wrong cwd makes it install
nothing. Always run from the repo root.

---

## 2. Multi-terminal setup (canonical 4-window layout)

| Window | Purpose | Command |
|---|---|---|
| **1 — Vera backend** | FastAPI on `:8000`, talks to Railway Postgres | `cd backend && docker compose up -d` (or `uvicorn app.main:app --reload --port 8000`) |
| **2 — Vera dashboard** | Next.js on `:3000`, Clerk-gated | `cd frontend && npm run dev` |
| **3 — ScribeMD demo** | FastAPI on `:8001` + Next.js on `:3001`, in-band HITL UX | `cd simulator/customers/scribemd && docker compose up -d` |
| **4 — Scratch** | scenario triggers, DB pokes, log tailing | (interactive) |

TriageGuard runs in the same shape as ScribeMD at `simulator/customers/triageguard/`,
swap port numbers (`:8002`/`:3002` by default — check `docker-compose.yml`).

**Container restart gotcha.** `docker compose restart` does NOT re-read
`.env.local` / `.env`. After changing any env var (including API keys) you
must `docker compose down && docker compose up -d`. Same goes for stale
shell exports — `unset VERA_API_KEY_SCRIBEMD` before re-sourcing.

---

## 3. Sourcing API keys

`POST /v1/register` was deleted in W2.3 (returns 404, not 410). Two paths
forward depending on what you're provisioning:

### 3a. Local dev (development env) — `POST /v1/dev/orgs`

W1.6 shipped this dev-only endpoint. Returns 404 outside `ENVIRONMENT=development`.

```bash
curl -X POST http://localhost:8000/v1/dev/orgs \
  -H "Content-Type: application/json" \
  -d '{"name": "scribemd", "with_baa": true}'
```

Response:
```json
{
  "org_id": "...",
  "name": "scribemd",
  "api_key": "al_test_...",   // shown ONCE — backend only stores hash
  "api_key_prefix": "al_test_xxxxxx",
  "has_baa": true
}
```

`with_baa: true` seeds a placeholder Customer + active BAA + wildcard
BAAScope so the org passes Gate 3 (stale_baa). Without it, every gated
call BLOCKs.

Idempotent on `name` (DB-level UNIQUE since W1.6). Re-using a name returns 409.

### 3b. Bulk scenario provisioning — `simulator/scripts/bootstrap_orgs.py`

Wraps `/v1/dev/orgs` for the three canonical acceptance-test orgs
(`scribemd`, `triageguard`, `scribemd-no-baa-test`) and writes the keys to
`simulator/.env.local` automatically. Run this whenever you wipe the DB.

```bash
DATABASE_URL=<railway-url> python simulator/scripts/bootstrap_orgs.py
```

### 3c. Production — Clerk only

No backdoor. Users sign up via the Clerk-gated dashboard at `/sign-up`.
The Clerk webhook auto-creates the org row on first sign-in.

### 3d. Last-resort recovery

If the dashboard is down, the backend is down, or the operator inherits a
database with orphan orgs whose raw keys were lost: there is no recovery
of the original raw key (backend stores hash only). Mint a new one via
`/v1/dev/orgs` (which generates a fresh admin key for an existing org if
re-called with the same name).

---

## 4. Database

### Local default
`backend/.env` ships with `DATABASE_URL=sqlite+aiosqlite:///./vera.db`. Good
for unit tests; not used during acceptance walkthroughs.

### Railway (acceptance testing)
Use `DATABASE_PUBLIC_URL` from the Railway service dashboard. The internal
`DATABASE_URL` only resolves from inside Railway's network.

```bash
export DATABASE_URL='postgresql+asyncpg://...@<host>.proxy.rlwy.net:<port>/railway'
```

Backend reads `DATABASE_URL` directly; container envs need the *public* URL when
running locally against Railway.

### Migration headroom
Both the old duplicate-revision issue (`s9n1o2p3q4r5` × 2) and the
`baa_scopes.granted_at NOT NULL` gotcha are fixed on main. Fresh Postgres
DBs apply via:

```bash
cd backend && DATABASE_URL=<railway> python -m alembic upgrade head
```

### Org dedupe (post-W2.3)
If duplicate-named orgs slip in (the unique-name migration aborts loudly
in that case), use the maintenance CLI shipped in W2.3:

```bash
# Inspect: list all orgs with the name
DATABASE_URL=<railway> python -m app.cli orgs dedupe \
  --name=scribemd --keep=<one-of-the-ids> --dry-run

# Execute: merges every other matching row INTO --keep in one transaction
DATABASE_URL=<railway> python -m app.cli orgs dedupe \
  --name=scribemd --keep=<surviving-id>
```

Re-points 9 FK tables (`action_records`, `api_keys`, `customers`,
`baa_agreements`, `policies`, `policy_violations`, `approvals`,
`org_memberships`, `checkpoints`), deletes the losing `chain_state` row,
deletes the losing `organizations` row. Single transaction; rolls back on
any failure. Pick the survivor based on which org owns the most
`action_records` (immutable audit trail).

---

## 5. Scenario walkthrough — known gotchas

### Scenario 2 (Gate 2 — controlled substance)
Free-text "oxycodone" in the note body may be redacted before reaching
the gate. **Always pass the explicit kwarg:**

```python
client.gate.evaluate(payload={"medication": "oxycodone", ...})
```

Not `medn=` (heredoc paste typo). Use `python -c '...'` instead of
heredocs when triggering scenarios manually — the typo bit me twice.

### Scenario 3 (Gate 3 — BLOCK no BAA)
Two pre-requisites:
1. **Default tenant must be set:** `set_default_tenant("scribemd-default-customer")`
   before the SDK call, or the action record fails with
   `TenantMissingOrInvalid`.
2. **Use the no-BAA org's key:** `VERA_API_KEY_NOBAA` (mapped to
   `scribemd-no-baa-test`), not the regular `VERA_API_KEY_SCRIBEMD`. The
   regular one has an active BAA and would ALLOW.

### Scenario 5 — REMOVED for MVP
The dashboard's approve/reject UI was stripped in W2.2 per HIPAA
scope-reduction: vendor staff don't approve their customers' agents'
decisions. All HITL flows are now in-band via the customer's EHR (see W2.1
for ScribeMD's Review Inbox at `/reviews`).

### ScribeMD "Not signed in" mid-test
Clerk session expired or the cookie got cleared. Refresh and re-enter the
passkey from `simulator/customers/scribemd/.env.local`
(`SCRIBEMD_PASSKEY`).

### 403 on `/v1/approvals/{id}/decide` (legacy path)
Usually a stale API key. Two failure modes:
- ScribeMD container cached the key — `docker compose down && up -d`
- Shell still has an old export — `unset` and re-source `.env.local`

After W1.1 lands, 403 on this endpoint with `reviewer_credentials_insufficient`
is also legitimate — the gated approval requires a specific `required_role`
in the request body.

---

## 6. PHI + dashboard contract (W1.2 + W2.2)

- **Vera dashboard** (Clerk auth): metadata only. No clinical narratives,
  no `data_subject_id`, no free-text fields that could carry PHI. Reviewer
  IDs are stripped too (W2.2). All filtering, sorting, and read-only audit
  views work as before.
- **SDK callers** (API key auth): full shape preserved. ScribeMD's
  in-band Review Inbox sees full PHI because the clinician is authorized.
- **Approve/reject from dashboard:** doesn't exist anymore. The button is
  gone. The endpoint (`POST /v1/reviews/{review_id}/complete`) is still
  live — only ScribeMD's backend (via the SDK helper) calls it now.

If a Phase 3 finding is "PHI visible in dashboard", confirm via
`backend/tests/test_dashboard_phi_redaction.py` first — that's the
regression net. Real leaks land in the table in
[phase2-acceptance-findings.md](phase2-acceptance-findings.md) under a
follow-up workstream tag.

---

## 7. Quick reference — every common command

```bash
# Activate the env
conda activate vera

# Re-bootstrap all orgs (after DB wipe)
DATABASE_URL=<railway> python simulator/scripts/bootstrap_orgs.py

# Hand-mint a single org
curl -X POST http://localhost:8000/v1/dev/orgs \
  -H "Content-Type: application/json" \
  -d '{"name":"<slug>","with_baa":true}'

# Dedupe duplicate-named orgs
DATABASE_URL=<railway> python -m app.cli orgs dedupe \
  --name=<slug> --keep=<id> --dry-run

# Apply migrations against Railway
cd backend && DATABASE_URL=<railway> python -m alembic upgrade head

# Restart any container after env change
docker compose down && docker compose up -d

# Run the dashboard PHI regression test
cd backend && python -m pytest tests/test_dashboard_phi_redaction.py -x -q

# Tail Vera backend logs
docker compose logs -f vera-backend
```

---

## 8. When Phase 3 surfaces new bottlenecks

Append a section here (`## Phase 3 follow-ups`) and a row to
[phase2-acceptance-findings.md](phase2-acceptance-findings.md) under a
new workstream tag (`W3.x`). Same conventions: append-only, one row per
finding, don't rewrite landed rows.
