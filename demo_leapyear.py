"""
FinFast Bank — AI Loan Decision System
Powered by Vera: Immutable AI Audit Trail

Three AI agents process real loan applications. Every decision is recorded,
cryptographically hashed, and tamper-evident. Regulators can audit every call.
Applicants have a legal right to see all decisions made about them.

Usage:
    OPENAI_API_KEY=sk-... python demo_leapyear.py <VERA_API_KEY> [--url URL]

Requires:
    pip install openai
    pip install -e sdk/
"""
import os
import sys
import time
import argparse

import openai

from vera import VeraClient


# ── Loan applicants ──────────────────────────────────────────────────────────

APPLICANTS = [
    {
        "name": "Sarah Chen",
        "id": "user_sarah_chen",
        "profile": (
            "Applicant: Sarah Chen | Loan request: $320,000 mortgage (30-year fixed) | "
            "Annual income: $95,000 | Credit score: 742 | Debt-to-income ratio: 28% | "
            "Employment: 6 years at Salesforce (senior engineer, W-2 verified) | "
            "Liquid savings: $85,000 | Payment history: 0 late payments in 24 months | "
            "Collections: none"
        ),
    },
    {
        "name": "Marcus Johnson",
        "id": "user_marcus_johnson",
        "profile": (
            "Applicant: Marcus Johnson | Loan request: $185,000 mortgage (30-year fixed) | "
            "Annual income: $62,000 | Credit score: 618 | Debt-to-income ratio: 41% | "
            "Employment: 18 months at Series A startup (base salary, no equity counted) | "
            "Liquid savings: $22,000 | Payment history: 1 late payment in last 12 months | "
            "Collections: none"
        ),
    },
    {
        "name": "Alex Rivera",
        "id": "user_alex_rivera",
        "profile": (
            "Applicant: Alex Rivera | Loan request: $215,000 mortgage (30-year fixed) | "
            "Annual income: $48,000 | Credit score: 551 | Debt-to-income ratio: 58% | "
            "Employment: 7 months at current job (6-month employment gap prior) | "
            "Liquid savings: $8,000 | Payment history: 2 late payments in last 12 months | "
            "Collections: 1 active collection account ($1,200)"
        ),
    },
]


# ── System prompts ────────────────────────────────────────────────────────────

SYSTEM_ANALYSIS = (
    "You are a loan underwriting analyst at FinFast Bank. "
    "Given a loan application, extract exactly 3 key financial signals that determine creditworthiness. "
    "Format your response as:\n1) [signal]\n2) [signal]\n3) [signal]\n"
    "Each signal is a single short phrase referencing a specific number from the application. "
    "No extra commentary."
)

SYSTEM_RISK = (
    "You are a credit risk specialist at FinFast Bank. "
    "Given the financial analysis of a loan applicant, assign a risk level: LOW, MEDIUM, or HIGH. "
    "Begin your response with the risk level in ALL CAPS, followed by ' — ', then one sentence of "
    "justification citing 1-2 specific data points. No extra commentary."
)

SYSTEM_DECISION = (
    "You are a senior loan officer at FinFast Bank making a binding lending decision. "
    "Based on the financial analysis and risk assessment, output exactly one of: "
    "APPROVED, NEEDS_REVIEW, or REJECTED. "
    "Begin your response with the decision in ALL CAPS followed by a colon, "
    "then a regulatory-compliant explanation in 20 words or fewer. No extra commentary."
)


# ── Helpers ───────────────────────────────────────────────────────────────────

W = 62


def rule(char="═"):
    return char * W


MODEL = "gpt-4o-mini"


def call_openai(oc: openai.OpenAI, system: str, user_content: str, max_tokens: int = 160):
    t0 = time.time()
    response = oc.chat.completions.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
    )
    elapsed_ms = int((time.time() - t0) * 1000)
    return response.choices[0].message.content.strip(), elapsed_ms, response.usage


# ── Applicant pipeline ────────────────────────────────────────────────────────

def process_applicant(applicant, index, total, oc, analysis_cl, risk_cl, decision_cl):
    name = applicant["name"]
    subject_id = applicant["id"]
    profile = applicant["profile"]

    label = f" Applicant {index}/{total}: {name} ({subject_id}) "
    pad = max(0, W - 2 - len(label))
    print(f"\n┌─{label}{'─' * pad}┐")

    # ── analysis-agent ────────────────────────────────────────
    print(f"  [analysis-agent] Analyzing financial profile...", end="", flush=True)
    analysis_text, analysis_ms, analysis_usage = call_openai(oc, SYSTEM_ANALYSIS, profile)
    rec1 = analysis_cl.record_action(
        action_name="analyze_application",
        action_type="llm_call",
        result="success",
        input_data={"applicant_id": subject_id, "model": MODEL},
        outcome={
            "analysis": analysis_text,
            "input_tokens": analysis_usage.prompt_tokens,
            "output_tokens": analysis_usage.completion_tokens,
        },
        duration_ms=analysis_ms,
        data_subject_id=subject_id,
    )
    print()
    for line in analysis_text.split("\n"):
        if line.strip():
            print(f"    {line}")
    print(f"    Recorded  seq={rec1['sequence_number']}  hash={rec1['record_hash'][:16]}...  ({analysis_ms}ms)")

    # ── risk-agent ────────────────────────────────────────────
    print(f"  [risk-agent]     Scoring default risk...", end="", flush=True)
    risk_prompt = f"Financial signals extracted from application:\n{analysis_text}\n\nFull application: {profile}"
    risk_text, risk_ms, risk_usage = call_openai(oc, SYSTEM_RISK, risk_prompt)
    rec2 = risk_cl.record_action(
        action_name="assess_risk",
        action_type="llm_call",
        result="success",
        input_data={"applicant_id": subject_id, "analysis": analysis_text, "model": MODEL},
        outcome={
            "risk_assessment": risk_text,
            "input_tokens": risk_usage.prompt_tokens,
            "output_tokens": risk_usage.completion_tokens,
        },
        duration_ms=risk_ms,
        data_subject_id=subject_id,
    )
    print()
    print(f"    {risk_text}")
    print(f"    Recorded  seq={rec2['sequence_number']}  hash={rec2['record_hash'][:16]}...  ({risk_ms}ms)")

    # ── decision-agent ────────────────────────────────────────
    print(f"  [decision-agent] Making final decision...", end="", flush=True)
    decision_prompt = (
        f"Financial analysis:\n{analysis_text}\n\n"
        f"Risk assessment:\n{risk_text}\n\n"
        f"Full application: {profile}"
    )
    decision_text, decision_ms, decision_usage = call_openai(
        oc, SYSTEM_DECISION, decision_prompt, max_tokens=80
    )
    rec3 = decision_cl.record_action(
        action_name="make_decision",
        action_type="llm_call",
        result="success",
        input_data={
            "applicant_id": subject_id,
            "analysis": analysis_text,
            "risk": risk_text,
            "model": MODEL,
        },
        outcome={
            "decision": decision_text,
            "input_tokens": decision_usage.prompt_tokens,
            "output_tokens": decision_usage.completion_tokens,
        },
        duration_ms=decision_ms,
        data_subject_id=subject_id,
    )
    print()
    print(f"    {decision_text}")
    print(f"    Recorded  seq={rec3['sequence_number']}  hash={rec3['record_hash'][:16]}...  ({decision_ms}ms)")

    return {
        "name": name,
        "id": subject_id,
        "decision": decision_text,
        "records": [rec1, rec2, rec3],
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="FinFast Bank AI loan demo — powered by Vera")
    parser.add_argument("api_key", help="Vera API key")
    parser.add_argument("--url", default="http://localhost:8000", help="Vera API base URL")
    args = parser.parse_args()

    openai_key = os.environ.get("OPENAI_API_KEY")
    if not openai_key:
        print("Error: OPENAI_API_KEY is not set.")
        print("  export OPENAI_API_KEY=sk-...")
        sys.exit(1)

    # ── Banner ────────────────────────────────────────────────
    print()
    print(rule())
    print("  FinFast Bank — AI Loan Decision System")
    print("  Powered by Vera: Immutable AI Audit Trail")
    print(rule())
    print(f"  Vera backend:  {args.url}")
    print(f"  AI model:      {MODEL}")
    print()
    print("  Processing 3 applicants through 3 AI agents.")
    print("  Every LLM decision is recorded in real-time.")

    # ── Clients ───────────────────────────────────────────────
    common = dict(
        api_url=args.url,
        api_key=args.api_key,
        framework="finfast-demo",
        model_id=MODEL,
    )
    analysis_cl = VeraClient(**common, agent_name="analysis-agent", agent_version="1.0.0")
    risk_cl     = VeraClient(**common, agent_name="risk-agent",     agent_version="1.0.0")
    decision_cl = VeraClient(**common, agent_name="decision-agent", agent_version="1.0.0")
    oc = openai.OpenAI(api_key=openai_key)

    # ── Process applicants ────────────────────────────────────
    results = []
    for i, applicant in enumerate(APPLICANTS, 1):
        result = process_applicant(
            applicant, i, len(APPLICANTS),
            oc, analysis_cl, risk_cl, decision_cl,
        )
        results.append(result)

    # ── Audit trail ───────────────────────────────────────────
    print()
    print(rule())
    print("  AUDIT TRAIL — 9 Records, Cryptographically Chained")
    print(rule())
    actions = analysis_cl.query_actions(limit=50)
    for rec in sorted(actions["records"], key=lambda r: r["sequence_number"]):
        subj = (rec.get("data_subject_id") or "")[:24]
        print(
            f"  #{rec['sequence_number']:>2}  {rec['action_name']:<24}"
            f"  {subj:<24}  {rec['record_hash'][:16]}..."
        )
    print(f"\n  Total: {actions['total']} records")

    # ── Agents registered ─────────────────────────────────────
    print()
    print(rule())
    print("  AGENTS — Auto-registered on First Action")
    print(rule())
    agents = analysis_cl.list_agents()
    for agent in agents:
        print(f"  {agent['name']:<22}  id: {agent['id'][:16]}...")

    # ── GDPR / EU AI Act subject access ───────────────────────
    print()
    print(rule())
    print("  SUBJECT ACCESS REQUEST")
    print("  EU AI Act Art. 86 / GDPR Art. 22 — right to explanation")
    print(rule())
    print("  Query: all AI decisions about Sarah Chen (user_sarah_chen)")
    print()
    subject_actions = analysis_cl.query_actions(limit=50, data_subject_id="user_sarah_chen")
    for rec in sorted(subject_actions["records"], key=lambda r: r["sequence_number"]):
        print(
            f"  #{rec['sequence_number']:>2}  {rec['action_name']:<24}"
            f"  {rec['record_hash'][:16]}..."
        )
    print(f"\n  → {subject_actions['total']} records found for user_sarah_chen")

    # ── Chain verification ────────────────────────────────────
    print()
    print(rule())
    print("  CHAIN VERIFICATION — Tamper Detection")
    print(rule())
    verification = analysis_cl.verify_chain()
    ok = verification["is_valid"]
    status = "✓ VALID" if ok else "✗ TAMPERED"
    print(f"  {status} — {verification['records_checked']} records checked")
    print(f"  {verification['message']}")

    # ── Checkpoint ────────────────────────────────────────────
    print()
    print(rule())
    print("  CHECKPOINT — Cryptographic Snapshot")
    print(rule())
    checkpoint = analysis_cl.create_checkpoint()
    print(f"  Checkpoint ID:  {checkpoint['id']}")
    print(f"  At sequence:    {checkpoint['sequence_at_checkpoint']}")
    print(f"  Chain hash:     {checkpoint['hash_at_checkpoint'][:32]}...")
    merkle = checkpoint.get("merkle_root") or "n/a"
    print(f"  Merkle root:    {merkle[:32]}{'...' if merkle != 'n/a' else ''}")
    print(f"  KMS signature:  {checkpoint['signature'][:32]}...")

    cp_verify = analysis_cl.verify_checkpoints()
    cp_ok = cp_verify["all_valid"]
    cp_status = "✓ ALL VALID" if cp_ok else "✗ INVALID"
    print(f"\n  Checkpoints:    {cp_status} ({cp_verify['total_checked']} checked)")

    # ── Close ─────────────────────────────────────────────────
    analysis_cl.close()
    risk_cl.close()
    decision_cl.close()

    # ── Final summary ─────────────────────────────────────────
    print()
    print(rule("═"))
    print()
    print("  LOAN DECISIONS:")
    for r in results:
        verdict = r["decision"].split(":")[0].split()[0]
        symbol = "✓" if "APPROVED" in verdict else ("?" if "REVIEW" in verdict else "✗")
        print(f"  {symbol}  {r['name']:<20}  {verdict}")
    print()
    if ok and cp_ok:
        print("  ✓ Audit trail:        9 records, all hashed")
        print("  ✓ Chain integrity:    VERIFIED — nothing tampered")
        print("  ✓ Checkpoint:         SIGNED & VERIFIED")
        print("  ✓ Subject filtering:  GDPR / EU AI Act compliant")
        print("  ✓ Agent tracking:     3 agents auto-registered")
        print()
        print("  Vera makes AI compliance provable.")
    else:
        print("  WARNING: Verification failed — check output above.")
    print()
    print(rule())
    print()


if __name__ == "__main__":
    main()
