# Error Discipline — 12-class catalog

This is a **cross-phase PR-gate checklist** for the Vera v1 implementation
plan (Codex DX X5). Every new error path — SDK, backend, dashboard,
webhook callback, CLI — MUST surface all four of:

| Field | Purpose | Audience |
|---|---|---|
| `user_facing_reason` | One sentence in plain language; safe to render to a CEO or in-house counsel. No stack traces, no field names, no hex IDs. | Customer-facing surfaces (dashboard banner, email digest, PDF blocker copy). |
| `developer_reason` | The specific technical condition that triggered the error, with the field/value/state that's wrong. | Engineer reading SDK logs, CLI output, support ticket. |
| `fix_url` | Deep link into the dashboard that lands the user on the screen where they can resolve it (e.g., the BAA upload page, the API-key rotation page, the policy-pack install page). | Customer remediation. |
| `docs_url` | Deep link into Vera's docs site explaining the error class, common causes, and the fix flow. | Engineer understanding the failure mode. |

A PR that adds an error path without all four fields fails the
error-discipline gate and does not merge.

## The 12 classes

These are the canonical error codes used across the SDK + backend +
dashboard. New error conditions either map onto one of these or get
added here in a follow-up PR before the new path lands.

| Code | When raised |
|---|---|
| `missing_api_key` | SDK call has no `VERA_API_KEY` set and no key passed via `vera.init(api_key=...)`. |
| `invalid_api_key` | Key present but rejected by `/v1/auth/verify` — revoked, malformed, or unknown. |
| `wrong_key_tier` | Caller used an `al_test_*` key against a production-only route, or `al_live_*` key against a sandbox-only route. |
| `dev_mode_active` | `VERA_DEV=1` and a sandbox key are both active and `VERA_FORCE_OVERLAY` is unset; ambiguous which mode applies. |
| `init_missing` | A decorator fired before `vera.init()` was called (no `agent_type` registered, no tenant resolver bound). |
| `tenant_missing` | A `@vera.gate`-decorated call ran without a resolvable `tenant_id` (no kwarg, no context manager, no middleware default). |
| `tenant_invalid_or_phi` | The tenant_id failed format regex or matched the PHI-shape heuristic — rejected hard on `al_live_*`, warned on `al_test_*`. |
| `gate_timeout_or_network` | Gate evaluation didn't complete within the SDK timeout, or the backend was unreachable. |
| `policy_block` | A gate evaluated and the policy decision was BLOCK; the SDK raises `vera.PolicyBlock` so the calling agent halts. |
| `pending_review` | A gate evaluated to HITL; the SDK raises `vera.PendingReview` with the review handle so the calling agent can wait or surface to the user. |
| `reviewer_credentials_insufficient` | A reviewer attempted to complete a Review without the required role/license (e.g., non-prescriber on a controlled-substance review). |
| `redaction_or_spool_failure` | The audit-record spooler failed to redact a PHI field or persist a record — record is held in the spool queue and capture is degraded. |
| `unknown_agent_type_or_action_class` | An action was captured with an `agent_type` or `action_class` not present in the registered taxonomy; the backend emits `new_agent_type_detected`. |

## Concrete shape

Every error returned from `POST /v1/gates/evaluate`,
`POST /v1/reviews/{id}/complete`, and every SDK exception raised
by `vera-sdk` MUST be serializable to:

```json
{
  "code": "policy_block",
  "user_facing_reason": "This decision was blocked because the agent...",
  "developer_reason": "policy_pack=clinical_scribe rule=controlled_substance_dea_check evaluated to BLOCK on rxnorm_code=...",
  "fix_url": "https://app.vera.dev/customers/abridge/policies/clinical-scribe/controlled-substance-dea-check",
  "docs_url": "https://docs.vera.dev/errors/policy_block"
}
```

If a new error path can't yet point at a real `fix_url` (e.g., the
remediation screen hasn't been built), the PR adding the error must
either (a) build the remediation screen in the same PR or (b) point
`fix_url` at a documented "contact support" surface and note the
follow-up in the PR description. `null` is not allowed.

## PR-gate checklist

Reviewers checking a PR that touches an error path verify each box:

- [ ] Error code is in the table above (or this doc is updated in the same PR).
- [ ] `user_facing_reason` is one sentence, plain language, no jargon.
- [ ] `developer_reason` names the specific field/value/state that triggered it.
- [ ] `fix_url` resolves to a real screen (or a documented support fallback).
- [ ] `docs_url` resolves to a published docs page (or a placeholder is
      filed and tracked).
- [ ] SDK serialization round-trips the four fields (test or fixture proves it).
- [ ] Dashboard surface that renders the error renders all four fields
      (or renders `user_facing_reason` + an expand-for-details
      affordance that reveals `developer_reason` + the two URLs).

## Why this lives here, not in code

Errors degrade silently if the discipline isn't enforced socially. A
runtime check ("did you set fix_url?") catches missing fields too
late — after the error has already been thrown in production. This
doc is the PR-time gate; the SDK + backend each ship their own
linter-style helpers (`vera.errors.ensure_complete(payload)`) that
backs it up at runtime, but the doc is the contract.

## References

- v1 implementation plan §"Error catalog" (line ~1000)
- v1 implementation plan Phase 2 §"SDK" (`@vera.gate` raising
  `vera.PendingReview` / `vera.PolicyBlock` with full 12-class catalog)
- Codex DX finding X5 (the originating recommendation)
