# Vera Simulator

A multi-tenant demo bench of mock medtech AI startups, each integrated with Vera. Lives inside the Vera repo so every Vera feature update can be exercised against realistic customer code.

## What's in here

Each subfolder under `customers/` is a mock medtech company built around one ICP from `use_cases.md`. They share `shared/` (LLM provider abstraction, Vera bootstrap, synthetic patient fixtures) and each registers as its own org against Vera production.

| Customer | Use Case | Status |
|---|---|---|
| `scribemd/` | #1 — AI scribe → chart entry | Week 1: headless CLI |
| `triageguard/` | #3 — AI triage / symptom checker | Planned |
| `authassist/` | #2 — Prior auth agent | Planned |
| `trialscope/` | #4 — Clinical trial eligibility | Planned |
| `appealsai/` | #5 — Claims denial / appeal | Planned |
| `pvscope/` | #6 — Pharmacovigilance | Planned |
| `credly/` | #7 — Physician credentialing | Planned |

## Three modes

| Mode | Vera target | LLMs | When to run |
|---|---|---|---|
| **A — Demo** | Vera production | Real OpenAI + Anthropic | Live sales screenshare |
| **B — CI** | Local in-memory Vera (pytest fixture) | Recorded cassettes | Every PR |
| **C — Chaos** | Local Vera (`docker compose up`) | Real or stubbed | Manual / weekly |

Production is **never** the target for chaos. The simulator's chaos mode tampers with Vera's DB to verify alarms fire — that's local-only by design.

## Quickstart (Mode A)

```bash
# 1. Install
cd simulator
pip install -e .
pip install -e ../sdk

# 2. Configure
cp .env.example .env.local
# Edit .env.local: set VERA_API_URL, OPENAI_API_KEY, ANTHROPIC_API_KEY

# 3. Bootstrap a Vera production org for each mock customer (one-time)
python -m simulator.scripts.bootstrap_orgs

# 4. Run the canonical Week 1 demo
python -m simulator.modes.demo scribemd
```

The bootstrap step calls `POST /v1/register` on Vera production once per mock customer and stores the resulting API keys in `.env.local`. Re-running is idempotent — if a key already exists for that customer slug, it's reused.

## Layout

```
simulator/
├── shared/
│   ├── llm.py            # LLMProvider: real OpenAI/Anthropic + cassette stub
│   ├── vera_setup.py     # Org bootstrap + per-customer client factory
│   └── fixtures/
│       └── patients.py   # Faker-generated synthetic patients (HIPAA-safe)
├── customers/
│   └── scribemd/
│       ├── agents/       # Note drafter (OpenAI), orders extractor (Anthropic)
│       ├── workflows/    # encounter.py: end-to-end pipeline
│       ├── fixtures/     # encounters.py: synthetic visit transcripts
│       └── policies.py   # Registers policies via /v1/policies
├── modes/
│   └── demo.py           # CLI entry point: `python -m simulator.modes.demo <slug>`
├── scripts/
│   └── bootstrap_orgs.py # One-time org registration on Vera prod
└── tests/                # Mode B regression suite (pytest)
```

## Adding a new customer

1. Add an entry to `CUSTOMERS` in `simulator/shared/vera_setup.py`.
2. Create `simulator/customers/<slug>/` with `agents/`, `workflows/`, `policies.py`.
3. Wire up a CLI entry in `simulator/modes/demo.py`.
4. Re-run `bootstrap_orgs.py` to register the new org.

## Synthetic data only

All patient data is Faker-generated. Real or realistic PHI is never used. The redaction layer in the Vera SDK is exercised regardless — fake SSNs and emails still get redacted, which is the point.
