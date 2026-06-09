# ScribeMD Backend — API Contract

This is the source of truth for the HTTP + SSE surface the Wave 2 frontend
codes against. Every response shape below is verbatim what the backend
returns.

Base URL: `http://localhost:8001`
Frontend dev origin: `http://localhost:3001` (in CORS allowlist).
Auth: HTTP-only `scribemd_session` cookie, `samesite=lax`, set on login.

All `/api/*` endpoints **except** `POST /api/auth/login` and `GET /api/health`
require the session cookie. The SSE stream included.

---

## Health

### `GET /api/health` — no auth

```http
200 OK
{ "ok": true, "service": "scribemd-backend" }
```

---

## Auth

### `POST /api/auth/login`

```http
POST /api/auth/login
Content-Type: application/json

{ "passkey": "demo-passkey-change-me" }
```

```http
204 No Content
Set-Cookie: scribemd_session=<opaque-token>; HttpOnly; SameSite=Lax; Path=/; Max-Age=28800
```

Errors:
- `401` if the passkey is wrong.
- `422` if the body is malformed.

### `POST /api/auth/logout`

Clears the cookie and revokes the session. Always `204`. Idempotent.

### `GET /api/auth/me`

```http
200 OK
{ "signed_in_as": "Dr. Adams" }
```

`401` if no valid session cookie.

---

## Encounters

### `POST /api/encounters` — kick off a workflow

Body must include **exactly one** of `fixture` or `custom`.

```jsonc
// fixture
{ "fixture": "pancreatitis" }   // or "followup" | "chest_pain"

// custom
{
  "custom": {
    "transcript": "PHYSICIAN: ...\nPATIENT: ...",
    "chief_complaint": "string",
    "visit_type": "office",          // "office" | "urgent" | "telehealth"
    "expected_risk": "medium"        // "low" | "medium" | "high" | "critical"
  }
}
```

```http
201 Created
{ "id": "<encounter-id>", "status": "running" }
```

`400` on neither / both / unknown fixture. `422` on schema violations.

The workflow is kicked off synchronously *before* the response returns, but
the response itself fires immediately — the workflow runs as a background
asyncio task and emits events on the SSE stream. Open `GET /api/events/{id}`
right after this returns to follow along live.

### `GET /api/encounters/{id}`

Snapshot of the current state. Always returns `200` once the encounter
exists; poll-friendly.

```jsonc
{
  "id": "abc123…",
  "source": "fixture" | "custom",
  "fixture_key": "pancreatitis" | null,
  "patient_summary": {
    "subject_id": "pt_xxxxxxx",
    "mrn": "MRN-12345678",
    "name": "Jane Doe",
    "dob": "1972-03-04",
    "sex": "F",
    "allergies": [],
    "active_meds": [],
    "chronic_conditions": [],
    "chief_complaint": "Severe epigastric pain x 1 day with vomiting",
    "visit_type": "urgent",
    "expected_risk": "high"
  },
  "status": "running" | "awaiting_approval" | "committed" | "blocked"
            | "auto_committed" | "error",
  "last_event": "approval_requested" | …,
  "vera_approval_id": "apr_xxxxx" | null,
  "vera_record_ids": ["rec_…", …],
  "terminal_outcome": null | {
    "encounter_id": "enc_…",
    "approval_status": "approved" | "rejected" | "auto_committed" | …,
    "chart_committed": true,
    "risk_tier": "high",
    "diagnoses": ["Acute pancreatitis"],
    "medication_orders": ["Ondansetron 4mg IV q6h PRN"],
    "lab_or_imaging_orders": ["Lipase", "CBC", "Abdominal US"],
    "note": "SUBJECTIVE: …\nOBJECTIVE: …\nASSESSMENT: …\nPLAN: …"
  },
  "events": [
    { "event": "draft_started",     "data": { … } },
    { "event": "draft_complete",    "data": { … } },
    …
  ],
  "input_payload": { "fixture": "pancreatitis" } | { "custom": { … } },
  "created_at": "2026-04-29T14:22:13.123456+00:00",
  "updated_at": "2026-04-29T14:22:18.456789+00:00"
}
```

`404` if no such encounter id.

### `GET /api/encounters?limit=20&offset=0`

```jsonc
{
  "encounters": [ <EncounterSnapshot>, … ],
  "total": 12,
  "limit": 20,
  "offset": 0
}
```

Newest first. `limit` clamped `[1, 100]`.

---

## Approvals

### `POST /api/approvals/{vera_approval_id}/decide`

Wakes the waiting workflow with the captured decision. The workflow's
`physician_callback` returns this back into `run_encounter`, which calls
Vera's own `/v1/approvals/{id}/decide` and continues to terminal state.

```http
POST /api/approvals/apr_xxxxx/decide
Content-Type: application/json

{
  "decision": "approve",      // "approve" | "reject"
  "approver": "Dr. Adams",
  "note": "lgtm"              // optional, may be null
}
```

```http
200 OK
{
  "approval_id": "apr_xxxxx",
  "decision": "approve",
  "approver": "Dr. Adams",
  "received": true
}
```

Errors:
- `404` if no pending approval matches the id (already terminal, expired,
  or never reached the gate).
- `422` on schema violations.

The terminal state lands on the SSE stream as `chart_committed` (approve)
or `chart_blocked` (reject).

---

## Events (SSE)

### `GET /api/events/{encounter_id}`

Opens an `text/event-stream` connection. The server first **replays** every
event already persisted on the encounter row, then **tails** the live bus.

If the workflow already terminated before the client connects, the replay
includes the terminal event and the stream closes cleanly — no hang.

Each frame uses the standard SSE format:

```
event: draft_started
data: {"encounter_id":"enc_…","patient":{…}}

event: draft_complete
data: {"note":"SUBJECTIVE: …","record_id":"rec_…","sequence_number":1,"tokens":{"input":215,"output":134},"duration_ms":1820,"model":"gpt-4o-mini"}

event: orders_extracted
data: {"diagnoses":["Acute pancreatitis"],"medication_orders":["…"],"lab_or_imaging_orders":["…"],"record_id":"rec_…","sequence_number":2,"model":"claude-…","tokens":{"input":380,"output":98}}

event: approval_requested
data: {"approval_id":"apr_…","risk_tier":"high","context":{"diagnoses":[…],"medication_orders":[…],"lab_or_imaging_orders":[…],"encounter_id":"enc_…","patient_mrn":"MRN-…","note_record_id":"rec_…","extraction_record_id":"rec_…"}}

event: approval_decided
data: {"approval_id":"apr_…","decision":"approve","approver":"Dr. Adams"}

event: chart_committed
data: {"auto":false,"record_id":"rec_…"}
```

### Event types

The SSE `event:` line is always one of:

| Event | When | Payload |
|---|---|---|
| `draft_started` | Note drafter dispatched | `{ encounter_id, patient: {safe summary} }` |
| `draft_complete` | Drafter returned a note | `{ note, record_id, sequence_number, tokens: {input, output}, duration_ms, model }` |
| `orders_extracted` | Extractor returned structured orders | `{ diagnoses, medication_orders, lab_or_imaging_orders, record_id, sequence_number, model, tokens }` |
| `approval_requested` | Workflow hit HITL gate | `{ approval_id, risk_tier, context }` |
| `approval_decided` | Decision captured by backend (before terminal) | `{ approval_id, decision, approver }` |
| `chart_committed` | Workflow committed (approved or no-orders auto-commit) | `{ auto: bool, record_id }` |
| `chart_blocked` | Workflow blocked (rejected / expired) | `{ approval_status, record_id }` |
| `error` | Workflow setup or run failed | `{ code, message, ts }` |

### Reconnect behaviour

Reconnecting clients see the full history replayed in order, then tail.
Clients should treat receipt of `chart_committed`, `chart_blocked`, or
`error` as the cue to close — the server closes the bus shortly after
emitting any of those.

`404` if the encounter id doesn't exist.

---

---

## Review Inbox (W2.1 — in-band HITL via webhook)

When Vera's gate raises `REQUIRE_HITL`, the SDK returns `pending_review`
synchronously to the workflow AND Vera POSTs an `approval.requested`
(legacy) / `review.requested` (new) webhook to ScribeMD's
`/vera/webhooks`. The clinician opens the **Review Inbox** at
`/reviews` in the EHR, clicks Approve or Reject, and ScribeMD calls
Vera's `POST /v1/reviews/{review_id}/complete` via the **SDK**'s
`complete_review` helper. Vera then POSTs `approval.resolved` /
`review.completed` back to confirm — `/vera/webhooks` flips the local
row to terminal and cascades to the matching encounter.

### `GET /api/reviews?status=pending`

Auth required. Returns Review Inbox items, newest first.

```jsonc
{
  "items": [
    {
      "approval_id": "apr_xxxxx",
      "encounter_id": "enc_xxxx" | null,
      "status": "pending" | "approved" | "rejected" | "expired",
      "risk_tier": "high" | …,
      "required_role": "attending_physician" | null,
      "action_name": "commit_orders" | null,
      "agent_name": "scribemd-chart-committer" | null,
      "data_subject_id": "pt_xxx" | null,
      "context_excerpt": { "diagnoses": […], "medication_orders": […], … },
      "decided_by": null | "Dr. Adams",
      "decided_at": null | "2026-05-26T12:05:00+00:00",
      "decision_note": null | "lgtm",
      "requested_at": "2026-05-26T11:30:00+00:00" | null,
      "expires_at": "2026-05-26T15:30:00+00:00" | null,
      "created_at": "…",
      "updated_at": "…"
    }
  ],
  "total": 1
}
```

Query: `status` in `{pending, approved, rejected, expired, all}`
(default `pending`); `limit` `[1,200]`; `offset` `≥0`.

### `GET /api/reviews/{approval_id}`

`200` with one `ReviewInboxItem` or `404 review_not_found`.

### `POST /api/reviews/{approval_id}/decide`

Auth required. Body:

```jsonc
{
  "decision": "approve" | "reject",
  "reviewer_role": "attending_physician",  // optional, default attending_physician
  "note": "looks correct"                  // optional, ≤ 2000 chars
}
```

Status codes mirror the upstream Vera contract:

- `200` — accepted; the row will flip to terminal when `review.completed`
  arrives back via the webhook. The response body is the optimistically
  stamped local row (still `status="pending"` until Vera's webhook lands).
- `403 reviewer_credentials_insufficient` — the clinician's role doesn't
  satisfy the gate's `required_role`.
- `404 review_not_found` — unknown approval_id.
- `409 review_already_<status>` — row already terminal.
- `502 vera_complete_review_failed` — Vera SDK call failed network-wise.

The decision is forwarded to Vera via the **SDK**'s `complete_review`
helper (not raw HTTP), so the call lands on the audit chain via an
SDK-recorded action.

---

## Webhook receiver

### `POST /vera/webhooks` — Vera-only

No session cookie. Authenticated via HMAC-SHA256 in the
`X-Vera-Signature` header (`sha256=<hex>`); the secret lives in
`SCRIBEMD_VERA_WEBHOOK_SECRET`. Bad / missing signature → `401`. No
secret configured → `503` (fail closed, never open-trust).

Handled event types:

- `approval.requested` / `review.requested` → create a pending Review
  Inbox row.
- `approval.resolved` / `review.completed` → flip the row to
  approved/rejected; cascade to the encounter (status → committed /
  blocked, last_event → chart_committed / chart_blocked).
- `review.expired` → mark the row expired; the encounter's
  `last_event` becomes `review_expired` and status flips to blocked
  (returned-to-scribe).

Idempotent on `(approval_id, event_type)`: a duplicate delivery returns
`200 {"applied": false, "reason": "duplicate"}` without mutation.

Unknown event types return `200 {"applied": false, "reason": "event_ignored"}`
so an over-broad subscription doesn't 500 the dispatcher.

---

## Quick state machine reference

```
created (POST returns 201)
   │
   ├─ status: "running"
   │     └─ events: draft_started → draft_complete → orders_extracted
   │
   ├─ status: "awaiting_approval"  (some encounters skip this — auto-commit)
   │     └─ event: approval_requested
   │
   └─ status: "committed" | "blocked" | "auto_committed" | "error"  (terminal)
         └─ event: chart_committed | chart_blocked | error
```

Frontend can drive UI off either:
- **The SSE stream** (recommended for the live encounter view), or
- **Polling `GET /api/encounters/{id}`** with the `events` array (the same
  data, lower fidelity timing).

Both are kept consistent — every event lands on both surfaces.
