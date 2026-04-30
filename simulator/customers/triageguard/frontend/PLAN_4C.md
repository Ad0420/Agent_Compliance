# PLAN_4C — TriageGuard frontend (data + view + tests + CI)

Wave 4C composes 4B's design primitives against 4A's backend contract
(`backend/contract.md`) into a working triage demo: login splash,
auth-guarded `/triage` SPA (selector → live pipeline → review gate →
routed screen), look-book preserved at `/look`. Templates mirror
ScribeMD's frontend verbatim; differences are TriageGuard's domain
language (sessions, reviews, escalation) and the `confirm | escalate`
decision shape.

## 1. Hook signatures

```ts
// hooks/use-auth.tsx
export function AuthProvider({ children }: { children: React.ReactNode }): React.JSX.Element
export function useAuth(): {
  signedInAs: string | null;
  isLoading: boolean;
  login(passkey: string): Promise<void>;
  logout(): Promise<void>;
}

// hooks/use-session.ts
export function useSession(id: string | null): {
  data: SessionSnapshot | null;
  isLoading: boolean;
  error: Error | null;
  refetch(): Promise<void>;
}
export function useStartSession(): {
  start(input: StartSessionInput): Promise<{ id: string }>;
  isStarting: boolean;
  error: Error | null;
}

// hooks/use-session-events.ts
export function useSessionEvents(sessionId: string | null): {
  events: SessionEvent[];
  status: "idle" | "connecting" | "open" | "closed" | "error";
  error: Error | null;
}

// hooks/use-decide-review.ts
export function useDecideReview(): {
  decide(reviewId: string, decision: "confirm" | "escalate", note?: string): Promise<void>;
  isDeciding: boolean;
  error: Error | null;
}
```

## 2. Type plan (`lib/api/types.ts`)

Verbatim from `contract.md`:

- `SessionStatus = "running" | "awaiting_review" | "routed" | "routing_blocked" | "error"`
- `FixtureKey = "easy_self_care" | "red_flag_chest_pain" | "ambiguous"`
- `RiskTier = "low" | "medium" | "high" | "critical"`
- `SessionEventType = "session_started" | "triage_classified" | "red_flag_evaluated" | "nurse_review_requested" | "nurse_decided" | "routed" | "routing_blocked" | "error"`
- `PatientSummary { subject_id, mrn, name, dob, sex, allergies[], active_meds[], chronic_conditions[], chief_complaint }` (no `visit_type`/`expected_risk` — TG schema differs from SM).
- `TerminalRouting { session_id, initial_level, final_level, classifier_reasoning, red_flag_fired, red_flag_terms[], recommended_override, risk_tier, approval_id, nurse_status, routing_committed }`
- `SessionEvent { event: SessionEventType, data: Record<string, unknown> }`
- `SessionSnapshot { id, source, fixture_key, patient_summary, status, last_event, vera_approval_id, vera_record_ids[], terminal_outcome (TerminalRouting|null), events[], input_payload, created_at, updated_at }`
- `CustomSessionInput { symptoms, chief_complaint }`
- `StartSessionInput = { fixture: FixtureKey } | { custom: CustomSessionInput }`
- `StartSessionResponse { id, status }`
- `ListSessionsResponse { sessions[], total, limit, offset }`
- `DecideReviewResponse { approval_id, decision, nurse, received }`
- Helpers `isTerminalStatus()`, `isTerminalEvent()`. Inferred fields: `nurse_status` is `"confirm" | "escalate"` (contract narrative).

## 3. `/triage` state machine

States: `selector | running | terminal`.

- selector → running: `useStartSession().start(...)` resolves, `setSessionId(id)`.
- running → terminal: snapshot status becomes terminal (`routed | routing_blocked | error`).
- terminal → selector: user clicks "New session" (calls `setSessionId(null)`).
- `RoutedScreen variant="routed"` for `routed`; `variant="blocked"` for `routing_blocked`; `variant="error"` for `error`.

## 4. Components (`components/triage/`)

- **session-selector.tsx** — props `{ onStart, isStarting, startError }`. Owns local tab + selected fixture + custom symptom/chief-complaint state. Emits `StartSessionInput`. Hero copy: "Start a triage session".
- **live-pipeline.tsx** — props `{ events: SessionEvent[] }`. Renders 4 `SessionStep`s:
  1. "Listening to symptoms" — done after `session_started`.
  2. "Classifying triage level" — active during `triage_classified`; payload AI level + reasoning.
  3. "Checking for red flags" — active during `red_flag_evaluated`; payload "Red-flag terms detected:" + terms (compact RiskPills).
  4. "Awaiting your triage decision" — active when `nurse_review_requested` fires; done when `nurse_decided`/`routed`; blocked if `routing_blocked`.
- **review-gate.tsx** — props `{ reviewEvent, patient, fallbackRiskTier, isDeciding, decideError, onDecide }`. Renders chief complaint, classifier level + reasoning, "Red-flag terms detected:" list, recommended override pill, "Confirm AI level" (secondary) and "Escalate to ER" (escalate) buttons.
- **routed-screen.tsx** — props `{ session, signedInAs, errorMessage, onReset }`. Three variants:
  - `routed`: hero "Patient routed to <level>." + receipt card + "View audit trail" deep-link (only here).
  - `blocked`: "Decision not recorded." + new-session button.
  - `error`: "We couldn't finish that triage session." + try-again.

## 5. Tests

20 total under `__tests__/hooks/`:

- **use-auth.test.tsx** (5): /me probe success, /me 401, login then /me populates, login 401 leaves state, logout clears state.
- **use-session.test.tsx** (6): idle when id null, fetch on mount, polls 1s and stops on `routed`, 404 path bounds re-tries, useStartSession POST + body, useStartSession 400 surfaces error.
- **use-session-events.test.tsx** (5): opens EventSource with `withCredentials`, parses each of 8 named events in order, closes on unmount, terminal `routed` flips status to closed, error path no auto-reconnect.
- **use-decide-review.test.tsx** (4): confirm path body shape (`nurse` field), escalate path with note, isDeciding toggle, ApiError 404 surfaces.

Total = 20 tests.

## 6. Routing logic at `/`

`useAuth().isLoading` → render Wordmark + "Loading your workspace" StatusDot.
On settle: `router.replace(signedInAs ? "/triage" : "/login")`. `replace` so the splash never lands in browser history.

## 7. Microcopy diff vs ScribeMD

| ScribeMD | TriageGuard |
|---|---|
| "Sign and commit" | "Confirm AI level" |
| "Reject" | "Escalate to ER" |
| "Awaiting your sign-off" | "Awaiting your triage decision" |
| "Chart updated." | "Patient routed to <level>." |
| "Note not signed." | "Decision not recorded." |
| "New encounter" | "New session" |
| "Start an encounter" | "Start a triage session" |
| "Ambient AI scribe…" (login footer) | "AI triage for the telehealth front door." |
| "approver" wire field | "nurse" wire field |

## 8. Error handling

- `useStartSession().error`: shown in selector as a coral/crimson alert. Selector stays mounted, user can retry.
- `useSession().error` (e.g. 404 on snapshot poll): `/triage` shows a small visible error pill in the topbar centerSlot + a "Try again" path that resets the session id.
- `useSessionEvents().status === "error"`: status dot turns to `error` in topbar; pipeline still falls back to snapshot's `events` array.
- All errors surface via the standard `<ApiError>` shape; component branches on `instanceof ApiError` for status-code-specific copy.

## 9. CI strategy

New workflow `.github/workflows/triageguard-frontend-tests.yml` runs Vitest only on `pull_request`, Node 22, `npm ci && npm run test:run`, working-directory `simulator/customers/triageguard/frontend`. Lint + tsc + build are already covered by the existing `triageguard-frontend-ci.yml` from 4B.

YAML validated locally with `python -c "import yaml; yaml.safe_load(open('…'))"`.
