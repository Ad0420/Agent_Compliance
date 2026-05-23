# Vera — Agent Instructions

## gbrain session protocol

Vera uses **gbrain** (PGLite-backed personal knowledge brain) as the durable
context substrate across sessions. The rolling source of truth is
[vera-context.md](vera-context.md) — a single markdown file that lives in
this repo, is mirrored into gbrain, and gets updated incrementally.

### At session start

When the user opens a new session and the work touches product, design,
architecture, or compliance decisions, load context from gbrain before
diving in:

```bash
# Quick check: what's relevant to the user's question?
gbrain query "<their question>" --detail medium

# Full read of the rolling context (Vera-specific work)
gbrain get vera-context | head -200
```

Other pages worth knowing about (queryable individually):
`policy-engine-mvp`, `policy-engine-north-star`, `dashboard-design`,
`dashboard-design-system`, `landing-design`.

If the user explicitly says "load context" / "what did we decide about X"
/ "use gbrain" — always check gbrain first before answering.

### At end of session, when substantive decisions were made

If the session produced new product decisions, design choices, architectural
calls, user pushback overruling a prior recommendation, or new
research with operational implications — sync to gbrain before the
session ends:

1. **Update [vera-context.md](vera-context.md) in place.** Edit the
   relevant section rather than appending a dated block. This is the
   rolling source of truth; never create parallel context docs.
2. **Sync to gbrain:**
   ```bash
   cat vera-context.md | gbrain put vera-context
   gbrain embed --stale   # only if OPENAI_API_KEY is set in env
   ```
3. **Commit `vera-context.md` to the Agent_Compliance repo** so it's
   safe on GitHub. The PGLite brain at `~/.gbrain/brain.pglite/` is
   local-only; the markdown source is what survives a laptop loss.

### What counts as "substantive" (trigger the sync)

- New product decisions or architectural calls
- User pushback that overrules a prior recommendation
- New regulations / research with operational implications
- New design documents created, or major sections added to existing docs
- Approvals / denials on plans
- The user explicitly says "save this to context" / "update gbrain"

### What does NOT need a sync

- Routine code changes (git history covers this)
- Debugging chatter
- Tool-result echoes
- Plans abandoned mid-conversation
- One-off questions answered without producing new state

### Date-aware behavior

`vera-context.md` is a **rolling** document, not an append-only log.
When information changes (a decision is reversed, a fact updates, a
scope changes) — EDIT the relevant section in place rather than
adding a new dated section. This keeps gbrain free of contradictions.

`gbrain put` overwrites by slug; `updated_at` reflects the most
recent write. Git history of `vera-context.md` is the audit trail for
"when did this change?"

If a snapshot of prior state needs to be preserved (rare — e.g., a
significant pivot worth remembering historically), save it as
`vera-context-snapshot-YYYY-MM-DD.md` in the repo but **do not put
it into gbrain.** Snapshots in gbrain pollute search results with
stale info.

### A note on the OpenAI dependency

Embeddings (semantic search) require `OPENAI_API_KEY` to be set in
the environment. gbrain uses `text-embedding-3-small` (~$0.02 per 1M
tokens). Without the key, keyword search via `gbrain search` still
works; only semantic `gbrain query` does not.

### A note on cross-machine

The current gbrain backend is PGLite — local to this machine. If the
user works from a second machine, they have two options:
1. Re-run `gbrain put` against the source docs in this repo (rebuild
   the brain from source). The source docs are the authority.
2. Migrate the brain to Supabase-backed remote mode via `/setup-gbrain`
   so multiple machines share one brain.

---

## Design system

Visual decisions live in two design-system docs:

- [landing-design.md](landing-design.md) — marketing surface (landing,
  regulations, marketing sub-pages, login/register)
- [dashboard-design-system.md](dashboard-design-system.md) — in-app
  dashboard (visual tokens, component library)

Plus UX wireframes in [dashboard-design.md](dashboard-design.md).

Always read the relevant design doc before making any visual or UI
decision. All font choices, colors, spacing, and aesthetic direction
are defined there. Do not deviate without explicit user approval.
In QA mode, flag any code that doesn't match.

## ICP and voice

The marketing surface (landing page, regulations page, marketing pages) is written
for **CEOs and in-house counsel** of companies deploying AI in regulated spaces
(lending, underwriting, clinical decision support, hiring). It is **not** written
for engineers. Avoid engineering-vernacular language on marketing surfaces:
hex strings, agent names, latency claims, terminal commands, code snippets.

Engineering-audience content (SDK, code samples, integration details) lives on
sub-pages or behind explicit toggles, not on the main landing page.

Never use "court-admissible" or "court-ready" anywhere. Use "regulator-ready" or
"evidence trail" instead.
