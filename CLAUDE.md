# Vera — Agent Instructions

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
- Full-date format with year ("Mar 15, 2026" not "Mar 15"); comma separators on
  numbers ("12,500" not "12500"); no abbreviation under 10K
  ("9,500" not "9.5K")
- Recommendation language: "Consider X" / "Recommended: X" — never bare
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
`/* */`, `<!-- -->`) to suppress a false positive. The reason is mandatory
and is surfaced in `--report-json` output for auditability. The marker must
be on the same line as the violation OR the immediately preceding line.
