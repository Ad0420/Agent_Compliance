# Vera v1 — Phase 2 Acceptance Findings

**Status: rolled-up institutional memory.** This document captures the
gap-and-fix findings surfaced during Phase 2 manual acceptance testing
of Vera v1 (the medtech audit layer). It was previously circulated as a
working file that kept getting recreated whenever someone switched
branches; W2.3 (housekeeping trio) puts it under version control so
future phases have a stable reference.

The findings here drove the W1 and W2 workstreams. Each row in the
status table links to the workstream tag that closed it and the merged
PR title (use `git log --grep="W1\." --grep="W2\." -i --oneline` to
re-derive the chain at any time).

## Status by workstream

| Workstream | Finding | Landed via |
|---|---|---|
| W1.1 | Legacy `POST /v1/approvals/{id}/decide` accepted any-role reviewer when the underlying approval was gated — should enforce the gate's `required_role` like the new `/reviews/{id}/complete` path | `feat(approvals): enforce reviewer role on legacy decide service` + `feat(approvals/schema): add optional reviewer_role to ApprovalDecision` + `feat(approvals/route): relax decide endpoint from admin to write` + `test(approvals): cover reviewer-role enforcement on legacy decide` (PR #251) |
| W1.2 | Dashboard `Approval.context` + `ActionRecord.input_data` + Decision rows leaked PHI to Clerk-authenticated reviewers (HIPAA minimum-necessary) — SDK responses (API-key auth, in-band callers) must stay full-shape | `feat(dashboard): strip PHI from Approval responses` + `test(dashboard): cover PHI redaction + Decisions reason_detail fix` (PR #245) |
| W1.3 | SDK `record_action_batch` 422 on backend (`audit-batch-422`) — gate result enum mismatch + async-close gaps | `fix(sdk): normalise gate result to backend wire enum` + `fix(sdk): close async + record_action_batch gaps from /review` + `test(sdk,backend): roundtrip + regression coverage for W1.3` |
| W1.4 | `POST /v1/gates/evaluate` blocked on webhook dispatch when subscriber slow/dead — endpoint should return promptly and dispatch fire-and-forget | `fix/gate-evaluate-non-blocking-dispatch` + `test(webhooks): regression coverage for fire-and-forget gate-evaluate dispatch` (PR #247) |
| W1.5 | Webhook SSRF hardening — registration accepted `http://169.254.169.254/...` and outbound delivery didn't recheck post-DNS-rebind; both paths needed deterministic guards | `fix/ssrf-guard-hardening` + `test(webhooks): SSRF hardening — registration + delivery-recheck + determinism` (PR #246) |
| W1.6 | (a) `POST /v1/register` was the only org-provisioning path in dev and routed through Clerk in prod — local bootstrap broke without a sandbox path; (b) `organizations.name` lacked UNIQUE → "two-scribemd-orgs" on Railway; (c) bootstrap silently warned instead of failing when the env key authenticated against a different org than expected | `feat(dev): POST /v1/dev/orgs for local org provisioning` + `feat(simulator): rewrite bootstrap_orgs.py for POST /v1/dev/orgs` + `feat(db): UNIQUE constraint on organizations.name` (PR #249, plus alembic chain fix PR #252 re-IDing the migration to `t0o2p3q4r5s6`) |
| W2.1 | _(reserve / unclaimed — fill in when the workstream lands)_ | _pending_ |
| W2.2 | _(reserve / unclaimed — fill in when the workstream lands)_ | _pending_ |
| W2.3 | Housekeeping trio — (a) `/v1/register` 410 stub is dead code now that Clerk + `/v1/dev/orgs` cover both prod and dev; (b) the unique-orgs migration aborts loudly on duplicates but the cleanup recipe is operator-typed SQL; (c) this very findings doc kept getting re-created across branch switches | `chore: housekeeping trio (W2.3 — kill /v1/register, orgs dedupe CLI, findings doc)` |

## Format conventions

* New findings should be appended to the table above with a one-line
  description and the workstream tag (`Wn.m`) that closes them. Keep
  rows in landing order so the table reads chronologically.
* Don't rewrite landed rows — if a follow-up surfaces, add a new row
  with the same workstream tag suffixed (`W1.5b`).
* The "Landed via" column is for the commit-subject excerpts most
  useful for re-deriving context with `git log`. It is not a PR-link
  manifest.

## Phase 3 onward

This doc is now version-controlled. As Phase 3 manual acceptance
testing surfaces new findings, append a section below for each phase
(`## Phase 3 findings`, `## Phase 4 findings`, etc.) and follow the
same table format. Phase 2 findings stay in the table above as a
closed set; future phases get their own.
