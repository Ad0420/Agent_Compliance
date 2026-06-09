# TriageGuard Backend — API Contract

This is the source of truth for the HTTP + SSE surface the Wave 4B
frontend codes against. Every response shape below is verbatim what the
backend returns.

Base URL: `http://localhost:8002`
Frontend dev origin: `http://localhost:3002` (in CORS allowlist).
Auth: HTTP-only `triageguard_session` cookie, `samesite=lax`, set on login.

All `/api/*` endpoints **except** `POST /api/auth/login` and
`GET /api/health` require the session cookie. The SSE stream included.

---

## Health

### `GET /api/health` — no auth

```http
200 OK
{ "ok": true, "service": "triageguard-backend" }
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
Set-Cookie: triageguard_session=<opaque-token>; HttpOnly; SameSite=Lax; Path=/; Max-Age=28800
```

Errors:
- `401` if the passkey is wrong.
- `422` if the body is malformed.

### `POST /api/auth/logout`

Clears the cookie and revokes the session. Always `204`. Idempotent.

### `GET /api/auth/me`

```http
200 OK
{ "signed_in_as": "Nurse Rivera, RN" }
```

`401` if no valid session cookie.

---

## Sessions

### `POST /api/sessions` — kick off a workflow

Body must include **exactly one** of `fixture` or `custom`.

```jsonc
// fixture
{ "fixture": "easy_self_care" }   // or "red_flag_chest_pain" | "ambiguous"

// custom
{
  "custom": {
    "symptoms": "Patient describes their symptoms here…",
    "chief_complaint": "string"
  }
}
```

```http
201 Created
{ "id": "<session-id>", "status": "running" }
```

`400` on neither / both / unknown fixture. `422` on schema violations.

The workflow is kicked off synchronously *before* the response returns,
but the response itself fires immediately — the workflow runs as a
background asyncio task and emits events on the SSE stream. Open
`GET /api/events/{id}` right after this returns to follow along live.

### `GET /api/sessions/{id}`

Snapshot of the current state. Always returns `200` once the session
exists; poll-friendly.

```jsonc
{
  "id": "abc123…",
  "source": "fixture" | "custom",
  "fixture_key": "red_flag_chest_pain" | null,
  "patient_summary": {
    "subject_id": "pt_xxxxxxx",
    "mrn": "MRN-12345678",
    "name": "Jane Doe",
    "dob": "1972-03-04",
    "sex": "F",
    "allergies": [],
    "active_meds": [],
    "chronic_conditions": [],
    "chief_complaint": "Exertional chest pain with jaw radiation and diaphoresis"
  },
  "status": "running" | "awaiting_review" | "routed" | "routing_blocked" | "error",
  "last_event": "nurse_review_requested" | …,
  "vera_approval_id": "apr_xxxxx" | null,
  "vera_record_ids": ["rec_…", …],
  "terminal_outcome": null | {
    "session_id": "ses_…",
    "initial_level": "virtual_visit",
    "final_level": "ER",
    "classifier_reasoning": "…",
    "red_flag_fired": true,
    "red_flag_terms": ["chest pain", "diaphoresis", "jaw radiation"],
    "recommended_override": "ER",
    "risk_tier": "critical",
    "approval_id": "apr_…",
    "nurse_status": "escalate",
    "routing_committed": true
  },
  "events": [
    { "event": "session_started",     "data": { … } },
    { "event": "triage_classified",   "data": { … } },
    …
  ],
  "input_payload": { "fixture": "red_flag_chest_pain" } | { "custom": { … } },
  "created_at": "2026-04-30T14:22:13.123456+00:00",
  "updated_at": "2026-04-30T14:22:18.456789+00:00"
}
```

`404` if no such session id.

### `GET /api/sessions?limit=20&offset=0`

```jsonc
{
  "sessions": [ <SessionSnapshot>, … ],
  "total": 12,
  "limit": 20,
  "offset": 0
}
```

Newest first. `limit` clamped `[1, 100]`.

---

## Reviews

### `POST /api/reviews/{vera_approval_id}/decide`

Wakes the waiting workflow with the captured nurse decision. The
workflow's `nurse_callback` returns this back into `run_session`, which
calls Vera's own `/v1/approvals/{id}/decide` (`confirm` → `approve`,
`escalate` → `reject`) and continues to terminal state.

```http
POST /api/reviews/apr_xxxxx/decide
Content-Type: application/json

{
  "decision": "confirm",          // "confirm" | "escalate"
  "nurse": "Nurse Rivera, RN",
  "note": "lgtm"                  // optional, may be null
}
```

`confirm` uses the AI classifier's level. `escalate` uses the red-flag
detector's `recommended_override` (falls back to `urgent_care` if the
detector did not propose one).

```http
200 OK
{
  "approval_id": "apr_xxxxx",
  "decision": "confirm",
  "nurse": "Nurse Rivera, RN",
  "received": true
}
```

Errors:
- `404` if no pending review matches the id (already terminal, expired,
  or never reached the gate).
- `422` on schema violations.

The terminal state lands on the SSE stream as `routed` (decided —
either confirm or escalate) or `routing_blocked` (expired without a
decision).

---

## Events (SSE)

### `GET /api/events/{session_id}`

Opens an `text/event-stream` connection. The server first **replays**
every event already persisted on the session row, then **tails** the
live bus.

If the workflow already terminated before the client connects, the
replay includes the terminal event and the stream closes cleanly — no
hang.

Each frame uses the standard SSE format:

```
event: session_started
data: {"session_id":"ses_…","patient":{…}}

event: triage_classified
data: {"level":"virtual_visit","reasoning":"…","confidence":0.55,"record_id":"rec_…","sequence_number":1,"model":"gpt-4o-mini","tokens":{"input":215,"output":134},"duration_ms":1820}

event: red_flag_evaluated
data: {"flagged":true,"terms":["chest pain","diaphoresis","jaw radiation"],"recommended_override":"ER","reasoning":"…","record_id":"rec_…","sequence_number":2,"model":"claude-…","tokens":{"input":380,"output":98},"duration_ms":1900}

event: nurse_review_requested
data: {"approval_id":"apr_…","risk_tier":"high","context":{"session_id":"…","patient_mrn":"MRN-…","classifier_level":"virtual_visit","classifier_reasoning":"…","red_flag_terms":[…],"red_flag_reasoning":"…","recommended_override":"ER","classifier_record_id":"rec_…","red_flag_record_id":"rec_…"}}

event: nurse_decided
data: {"approval_id":"apr_…","decision":"escalate","nurse":"Nurse Rivera, RN"}

event: routed
data: {"final_level":"ER","auto":false,"record_id":"rec_…","risk_tier":"critical","nurse_status":"escalate"}
```

### Event types

| Event | When | Payload |
|---|---|---|
| `session_started` | First step | `{ session_id, patient: {safe summary} }` |
| `triage_classified` | Classifier returned a level | `{ level, reasoning, confidence, record_id, sequence_number, model, tokens, duration_ms }` |
| `red_flag_evaluated` | Detector returned | `{ flagged, terms, recommended_override, reasoning, record_id, sequence_number, model, tokens, duration_ms }` |
| `nurse_review_requested` | Workflow hit HITL gate | `{ approval_id, risk_tier, context }` |
| `nurse_decided` | Decision captured by backend (before terminal) | `{ approval_id, decision, nurse }` |
| `routed` | Final routing recorded | `{ final_level, auto: bool, record_id, risk_tier, nurse_status? }` |
| `routing_blocked` | Workflow blocked (expired without decision) | `{ approval_status, record_id }` |
| `error` | Workflow setup or run failed | `{ code, message, ts }` |

### Reconnect behaviour

Reconnecting clients see the full history replayed in order, then tail.
Clients should treat receipt of `routed`, `routing_blocked`, or `error`
as the cue to close — the server closes the bus shortly after emitting
any of those.

`404` if the session id doesn't exist.

---

## Quick state machine reference

```
created (POST returns 201)
   │
   ├─ status: "running"
   │     └─ events: session_started → triage_classified → red_flag_evaluated
   │
   ├─ status: "awaiting_review"  (only if red-flag fires AND classifier was low-acuity)
   │     └─ event: nurse_review_requested
   │           └─ confirm → final = AI level
   │           └─ escalate → final = recommended_override (typically ER)
   │
   └─ status: "routed" | "routing_blocked" | "error"  (terminal)
         └─ event: routed | routing_blocked | error
```

Risk tiering:
- `critical` — red-flag fired AND escalation final = `ER`
- `high` — red-flag fired AND classifier was `self_care`/`virtual_visit`
- `medium` — clear `urgent_care` or `virtual_visit` with no red flag
- `low` — clear `self_care`, no red flag

Frontend can drive UI off either:
- **The SSE stream** (recommended for the live triage view), or
- **Polling `GET /api/sessions/{id}`** with the `events` array (the
  same data, lower-fidelity timing).

Both are kept consistent — every event lands on both surfaces.
