# Vera — Agent Instructions

## Git workflow

This project uses a **`develop` → `main`** two-branch flow. Adopted at the
start of Phase 3 to give us a real integration buffer before production.

- **`main`** is the production branch. Only `develop` merges into `main`,
  on release cadence (planned merges at phase or wave boundaries, never
  feature-by-feature). `main` is what's actually deployed.
- **`develop`** is the integration branch. All feature work happens
  against `develop`; it's near-shippable at all times. Each phase's
  acceptance gate runs on `develop` before the release merge into `main`.
- **Feature branches** branch off `develop` and PR back into `develop`.
  Naming pattern: `feat/<phase><wave><pr>-<short-description>` (e.g.
  `feat/phase3-wave3a-checkpoint-export`).

**Rules for humans + agents:**
- **Default base branch is `develop`.** Never open a feature PR with
  `main` as the base. Use `develop` unless you are explicitly doing a
  release merge.
- **Agent briefs MUST specify `develop` as the base.** When dispatching
  an agent to implement a PR, include in the brief:
  `git checkout develop && git pull --ff-only origin develop && git checkout -b <branch>`
  and `gh pr create --base develop`.
- **`develop` stays green.** Feature work that breaks integration tests
  does not land. Conflicts get rebased against the current `develop`
  head before merge.
- **Release merges (`develop` → `main`)** are intentional events. Open a
  PR titled `release: <phase or wave> → main`, walk the diff, run the
  acceptance gate one last time on `develop`, then merge.
- **Hotfix exception:** a true emergency fix may branch off `main` and
  PR back into `main` directly, but must also be cherry-picked or
  forward-merged into `develop` the same day so the branches stay in sync.

## Design System

Always read [DESIGN.md](DESIGN.md) before making any visual or UI decisions.
All font choices, colors, spacing, and aesthetic direction are defined there.
Do not deviate without explicit user approval.
In QA mode, flag any code that doesn't match DESIGN.md.

## ICP and Voice

The marketing surface (landing page, regulations page, marketing pages) is written
for **CEOs and in-house counsel** of companies deploying AI in regulated spaces
(lending, underwriting, clinical decision support, hiring). It is **not** written
for engineers. Avoid engineering-vernacular language on marketing surfaces:
hex strings, agent names, latency claims, terminal commands, code snippets.

Engineering-audience content (SDK, code samples, integration details) lives on
sub-pages or behind explicit toggles, not on the main landing page.

<!-- copy-allow: this is the rule itself — banned tokens quoted for definition -->
Never use "court-admissible" or "court-ready" anywhere. Use "regulator-ready" or
"evidence trail" instead.

## Voice & copy

User-facing copy on the dashboard is for **CEOs and in-house counsel** of regulated
AI vendors. Specific rules (full spec in `dashboard-design-system.md` §Voice & copy):

- Use "Customer" not "Hospital" / "Tenant"; "posture" not "score";
  <!-- copy-allow: rule definition — banned tokens quoted intentionally -->
  "regulator-ready" not "court-admissible"; "evidence trail" not
  <!-- copy-allow: rule definition — banned token quoted intentionally -->
  "cryptographic proof"
<!-- copy-allow: rule example — "2026" is a year, not a quantity -->
- Full-date format with year ("Mar 15, 2026" not "Mar 15"); comma separators on
  <!-- copy-allow: rule example — counter-form intentionally lacks comma separator -->
  numbers ("12,500" not "12500"); no abbreviation under 10K
  ("9,500" not "9.5K")
- Recommendation language: "Consider X" / "Recommended: X" — never bare
  <!-- copy-allow: rule definition — banned imperative phrases quoted intentionally -->
  imperatives ("You should X", "We recommend that you X", "Make sure to X")
<!-- copy-allow: rule definition — banned token quoted intentionally -->
- No "Welcome back"; no marketing chrome on the dashboard; no comparative
  claims about competitors
- `tabular-nums` on every rendered number (via Tailwind utility or
  `font-feature-settings: 'tnum'`)

The CI gate is `frontend-copy-check`
(`.github/workflows/frontend-copy-check.yml`). The default ruleset is enforced
in CI. Before opening a PR, also run the heuristic strict tier locally:

```
python scripts/check_copy_violations.py --strict frontend/
```

Strict mode adds `date-no-year`, `numbers-no-commas`, `recommendation-language`,
and `tabular-nums-missing` — heuristic rules with non-trivial false-positive
rates. They surface candidates for review; CI does not gate on them.

Add `# copy-allow: <reason>` inline (in any comment style — `//`, `#`,
`/* */`, `<!-- -->`) to suppress a false positive. The reason is mandatory,
must be at least 8 characters, and is surfaced in `--report-json` output for
auditability. The marker must be on the same line as the violation OR the
immediately preceding line.

**Strict→default graduation criteria.** A `--strict` rule earns a promotion
to the CI-gated default tier when BOTH: (1) the false-positive rate across
the entire `frontend/` codebase is zero (running `--strict` produces no
unexpected hits — only true positives or correctly-allowlisted entries),
and (2) at least 3 real violations have been caught in PR review since the
rule landed. Both directions (strict→default and the reverse) are
documented in the changelog.

## IAM tier checks

Wave 3B.3 (PR #236) established the IAM tier model: `IamTier.STAFF_FULL`
is reserved for a v2 break-glass tier and MUST behave identically to
`STAFF_READ_ONLY` in v1 (same redaction, same audit, same read-only
surface). So route handlers MUST branch on the boolean helpers, never on
a direct enum comparison:

- **Use**: `ctx.is_staff` / `ctx.is_customer` (properties on
  `AuthContext` in `backend/app/services/auth.py`).
<!-- iam-tier-direct-comparison-ok: rule definition — banned pattern quoted intentionally -->
- **Do NOT use**: `ctx.tier == IamTier.STAFF_READ_ONLY` or
<!-- iam-tier-direct-comparison-ok: rule definition — banned pattern quoted intentionally -->
  `ctx.tier == IamTier.CUSTOMER`. Either form silently mis-routes a
  future STAFF_FULL caller.

The CI gate is `iam-tier-check`
(`.github/workflows/iam-tier-check.yml`). It runs
`scripts/check_iam_tier_usage.sh` against `backend/app/routes/` on
every PR. The same antipattern was caught by `/review` twice before the
gate landed:

- PR #236 (Wave 3B.3): `backend/app/routes/staff.py:99` — CRITICAL.
- PR #240 (Wave 3D.1): `backend/app/routes/dashboard_chain_integrity.py:48` —
  INFORMATIONAL.

The PR that ships the gate also cleaned up five more pre-existing
instances in `approvals.py`, `records.py`, and `checkpoints_by_date.py`
that pre-dated the policy.

To suppress a deliberate exact-tier introspection (rare), add an inline
comment on the same line OR the immediately preceding line:

```
# iam-tier-direct-comparison-ok: <reason ≥8 chars>
```

The reason is mandatory (≥8 chars) and is surfaced when the script
runs with `--report-json` for auditability.
