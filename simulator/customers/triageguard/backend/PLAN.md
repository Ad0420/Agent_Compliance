# TriageGuard Backend — Plan (Use Case 3)

Telehealth front-door triage. AI assesses symptoms; if its acuity call is low and a red-flag detector trips, Nurse Rivera, RN reviews. Architecture mirrors ScribeMD's backend verbatim; differences are domain-only.

## 1. Workflow state machine

```
running                                       (just created)
  └─ session_started → triage_classified → red_flag_evaluated
running
  ├─ if red_flag.flagged AND classifier.level in {self_care, virtual_visit}:
  │     → status=awaiting_review, event=nurse_review_requested
  │       └─ nurse confirm → use AI level → routed (event)
  │       └─ nurse escalate → use detector.recommended_override → routed (event)
  │       └─ timeout (5s in tests / 300s prod) → auto-escalate to recommended_override → routed
  └─ else:
        → routed (auto, AI level)
terminal: routed | routing_blocked | error
```

## 2. Agent contract

`TriageClassifierAgent` (OpenAI gpt-4o-mini, framework=`triageguard-pipeline`, agent_name=`triageguard-triage-classifier`).
- input: `{symptoms: str, patient_subject_id, session_id}`
- LLM returns JSON: `{level: "self_care|virtual_visit|urgent_care|ER", reasoning: str, confidence: float}`
- Vera record: action=`classify_triage`, type=`llm_call`, outcome=parsed JSON, reasoning includes model+prompt-hash, data_subject_id=patient.subject_id.

`RedFlagDetectorAgent` (Anthropic Claude, framework=`triageguard-pipeline`, agent_name=`triageguard-red-flag-detector`).
- input: `{symptoms: str, classifier_level: str, patient_subject_id, session_id}`
- Returns JSON: `{flagged: bool, terms: [str], recommended_override: "self_care|virtual_visit|urgent_care|ER"|null, reasoning: str}`
- Vera record: action=`evaluate_red_flags`, outcome=parsed JSON, reasoning includes model.

Routing committer uses agent_name=`triageguard-routing-committer` for the request_approval call, the routed record (success), and the routing_blocked record (failure).

## 3. API surface

Base `http://localhost:8002`. Cookie `triageguard_session`, samesite=lax. CORS default `localhost:3002`.

- `GET /api/health` → `{ok, service: "triageguard-backend"}`
- `POST /api/auth/login` `{passkey}` → 204 + cookie | 401
- `POST /api/auth/logout` → 204
- `GET /api/auth/me` → `{signed_in_as}` | 401
- `POST /api/sessions` body has exactly one of `fixture` (FixtureKey) or `custom` (`CustomSessionInput`) → 201 `{id, status}` | 400 | 422
- `GET /api/sessions/{id}` → `SessionSnapshot` | 404
- `GET /api/sessions?limit&offset` → `SessionListResponse`
- `POST /api/reviews/{vera_approval_id}/decide` body=`DecideReviewRequest` → 200 `{approval_id, decision, nurse, received}` | 404
- `GET /api/events/{session_id}` → SSE; replay-then-tail.

## 4. SSE event types

| Event | When | Payload |
|---|---|---|
| `session_started` | First step | `{session_id, patient}` |
| `triage_classified` | Classifier returned | `{level, reasoning, confidence, record_id, model, tokens, duration_ms}` |
| `red_flag_evaluated` | Detector returned | `{flagged, terms, recommended_override, reasoning, record_id, model, tokens}` |
| `nurse_review_requested` | HITL gate | `{approval_id, risk_tier, context}` |
| `nurse_decided` | Backend captured nurse's call | `{approval_id, decision, nurse}` |
| `routed` | Final routing recorded | `{final_level, auto: bool, record_id}` |
| `routing_blocked` | Workflow blocked / timeout | `{approval_status, record_id}` |
| `error` | Setup or runtime failure | `{code, message, ts}` |

## 5. HITL decision shape

```jsonc
POST /api/reviews/{vera_approval_id}/decide
{
  "decision": "confirm" | "escalate",
  "nurse": "Nurse Rivera, RN",
  "note": "string|null"
}
```
- `confirm` → use AI's level
- `escalate` → use detector's `recommended_override` (workflow falls back to `urgent_care` if null)

## 6. Risk tiering

Determined by classifier level + red-flag presence:
- `critical` — red-flag fired AND escalation final level is `ER`
- `high` — red-flag fired AND classifier was `self_care`/`virtual_visit` (HITL case)
- `medium` — clear `urgent_care` or `virtual_visit` with no red flag
- `low` — clear `self_care`, no red flag

Passed to `request_approval(risk_tier=…)` and onto the `routed` record.

## 7. Canned fixtures

- `easy_self_care` — common cold; classifier→`self_care`, detector→`flagged=false`. No HITL. Auto-route, risk=low.
- `red_flag_chest_pain` — exertional chest pain, diaphoresis, jaw radiation. Classifier→`virtual_visit` (deliberately under-triaged); detector→`flagged=true`, terms=[chest pain, diaphoresis, jaw radiation], recommended_override=`ER`. HITL. Nurse escalates.
- `ambiguous` — moderate fever + cough, no clear red flag. Classifier→`virtual_visit`; detector→`flagged=false`. No HITL.

## 8. Policies (`simulator/customers/triageguard/policies.py`)

- `TriageGuard: Unknown agent activity` — `condition_type=unknown_agent`, known_agents=[`triageguard-triage-classifier`, `triageguard-red-flag-detector`, `triageguard-routing-committer`], action=flag.
- `TriageGuard: Missing reasoning trace` — `condition_type=missing_reasoning`, action=flag.
- `TriageGuard: Burst of failed red-flag detections` — `condition_type=consecutive_failures`, threshold=3, agent=`triageguard-red-flag-detector`, action=email.

`register_policies(api_url, api_key)` mirrors ScribeMD's helper.

## 9. Test surface (`tests/test_smoke.py`)

`os.environ.setdefault("TRIAGEGUARD_REVIEW_TIMEOUT_SECONDS", "5")` at module scope.

- `test_health`, `test_anon_routes_are_401`, `test_login_bad_passkey`
- `test_full_flow_confirm` — chest-pain fixture, nurse confirms → final=AI level
- `test_full_flow_escalate` — chest-pain fixture, nurse escalates → final=ER
- `test_no_hitl_when_clear` — easy_self_care skips HITL
- `test_sse_replay` — drain SSE after terminal (anti-deadlock)
- `test_decide_unknown_review_404`, `test_create_requires_one_input`, `test_list_sessions`

Fakes: `FakeOpenAILLM` returns level keyed off user text. `FakeAnthropicLLM` returns flagged JSON for chest-pain, unflagged otherwise. `FakeVeraClient` mirrors ScribeMD: shared approval registry, `record_action`, `request_approval`, `wait_for_approval`, post intercept for decide.

## 10. Threading bridge

Reuse ScribeMD's pattern verbatim: `asyncio.to_thread(run_session, …)`; per-pending `_PendingDecision`; route calls `resolve_pending(...)`; worker blocks on `event.wait(timeout=review_timeout_seconds)`. No new primitives.
