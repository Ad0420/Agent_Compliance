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

Never use "court-admissible" or "court-ready" anywhere. Use "regulator-ready" or
"evidence trail" instead.
