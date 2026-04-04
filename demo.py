"""
End-to-end demo for Vera.

Local dev:
  1. cd backend && python setup_local.py   (creates DB + org + API key)
  2. cd backend && uvicorn app.main:app --reload
  3. cd sdk && pip install -e .
  4. python demo.py <YOUR_API_KEY>

Against production:
  python demo.py <YOUR_API_KEY> --url https://agentcompliance-production.up.railway.app
"""
import os
import sys
import time

from actionledger import ActionLedgerClient, audit, set_default_client


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Vera end-to-end demo")
    parser.add_argument("api_key", help="Your Vera API key")
    parser.add_argument("--url", default="http://localhost:8000",
                        help="Vera API base URL (default: http://localhost:8000)")
    args = parser.parse_args()

    print(f"Vera demo — targeting: {args.url}")
    print()

    # ── 1. Initialize client ──────────────────────────────
    client = ActionLedgerClient(
        api_url=args.url,
        api_key=args.api_key,
        agent_name="demo-agent",
        agent_version="1.0.0",
        model_id="gpt-4o",
        framework="custom",
    )
    set_default_client(client)
    print("[1/9] SDK client initialized")

    # ── 2. Register an agent ──────────────────────────────
    agent = client.register_agent(
        name="demo-agent",
        description="A demo agent for testing Vera",
        metadata={"purpose": "demo", "version": "1.0.0"},
    )
    print(f"[2/9] Agent registered: {agent['name']} (id: {agent['id']})")

    # ── 3. Define audited functions ───────────────────────
    @audit(action_name="analyze_data", action_type="computation")
    def analyze_data(dataset: str, threshold: float):
        time.sleep(0.1)
        return {"records_processed": 1500, "anomalies_found": 3, "threshold": threshold}

    @audit(action_name="send_notification", action_type="notification")
    def send_notification(recipient: str, message: str):
        time.sleep(0.05)
        return {"delivered": True, "recipient": recipient}

    @audit(action_name="update_database", action_type="db_write")
    def update_database(table: str, record_id: int, updates: dict):
        time.sleep(0.05)
        return {"rows_affected": 1}

    @audit(action_name="risky_operation", action_type="api_call")
    def risky_operation():
        time.sleep(0.02)
        raise ValueError("Simulated failure for demo purposes")

    # ── 4. Call the functions ─────────────────────────────
    print("[3/9] Running audited functions...")
    result1 = analyze_data("sales_q4", threshold=0.95)
    print(f"  analyze_data:      {result1}")
    result2 = send_notification("admin@example.com", "Analysis complete")
    print(f"  send_notification: {result2}")
    result3 = update_database("customers", 42, {"status": "active"})
    print(f"  update_database:   {result3}")
    try:
        risky_operation()
    except ValueError:
        print("  risky_operation:   failed (expected)")

    # ── 5. Query the API ──────────────────────────────────
    print("[4/9] Querying action records...")
    actions = client.query_actions(limit=10)
    print(f"  Found {actions['total']} action records:")
    for rec in actions["records"]:
        print(f"    #{rec['sequence_number']} {rec['action_name']} -> {rec['result']}"
              f" (hash: {rec['record_hash'][:16]}...)")

    # ── 6. Verify the chain ───────────────────────────────
    print("[5/9] Verifying chain integrity...")
    verification = client.verify_chain()
    print(f"  Valid: {verification['is_valid']}")
    print(f"  Records checked: {verification['records_checked']}")
    print(f"  Message: {verification['message']}")

    # ── 7. Checkpoint creation + verification ─────────────
    print("[6/9] Creating checkpoint...")
    checkpoint = client.create_checkpoint()
    print(f"  Checkpoint ID:  {checkpoint['id']}")
    print(f"  Sequence:       {checkpoint['sequence_at_checkpoint']}")
    print(f"  Hash:           {checkpoint['hash_at_checkpoint'][:16]}...")
    print(f"  Merkle root:    {(checkpoint.get('merkle_root') or 'n/a')[:16]}...")
    print(f"  Signature:      {checkpoint['signature'][:16]}...")

    print("[7/9] Verifying all checkpoints...")
    cp_verification = client.verify_checkpoints()
    print(f"  All valid: {cp_verification['all_valid']}")
    print(f"  Total checked: {cp_verification['total_checked']}")
    for r in cp_verification["results"]:
        print(f"    Checkpoint seq={r['sequence']} valid={r['is_valid']}")

    # ── 8. Anthropic / Claude integration ─────────────────
    print("[8/9] Anthropic/Claude integration...")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        try:
            import anthropic
            from actionledger.integrations.anthropic import AuditedAnthropic

            raw_client = anthropic.Anthropic(api_key=anthropic_key)
            audited_anthropic = AuditedAnthropic(raw_client, ledger_client=client)
            response = audited_anthropic.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=64,
                messages=[{"role": "user", "content": "Reply with exactly: audit trail confirmed."}],
            )
            reply = response.content[0].text
            print(f"  Claude replied: '{reply}'")
            print(f"  Tokens used: {response.usage.input_tokens} in / {response.usage.output_tokens} out")
            print("  Call recorded in audit trail ✓")
        except Exception as e:
            print(f"  Anthropic call failed: {e}")
    else:
        print("  ANTHROPIC_API_KEY not set — skipping live Claude call")
        print("  (Set it to test the AuditedAnthropic wrapper)")

    # ── 9. Other framework stubs ──────────────────────────
    print("[9/9] Framework availability check...")
    try:
        from actionledger.integrations.langchain import ActionLedgerCallbackHandler
        print("  LangChain: ready  (chain.invoke(inputs, config={'callbacks': [handler]}))")
    except ImportError:
        print("  LangChain: not installed  (pip install actionledger[langchain])")

    try:
        import openai
        from actionledger.integrations.openai import AuditedOpenAI
        print("  OpenAI:    ready  (AuditedOpenAI(openai.OpenAI(), ledger_client=client))")
    except ImportError:
        print("  OpenAI:    not installed  (pip install actionledger[openai])")

    try:
        from actionledger.integrations.crewai import enable_crewai_auditing
        print("  CrewAI:    ready  (enable_crewai_auditing(client=client))")
    except ImportError:
        print("  CrewAI:    not installed  (pip install actionledger[crewai])")

    try:
        from actionledger.integrations.anthropic import AuditedAnthropic
        print("  Anthropic: ready  (AuditedAnthropic(anthropic.Anthropic(), ledger_client=client))")
    except ImportError:
        print("  Anthropic: not installed  (pip install actionledger[anthropic])")

    # ── Summary ───────────────────────────────────────────
    print()
    print("=" * 55)
    print("Demo complete!")
    print("=" * 55)
    chain_ok = verification["is_valid"]
    cp_ok = cp_verification["all_valid"]
    if chain_ok and cp_ok:
        print("  Chain verification:      PASSED")
        print("  Checkpoint verification: PASSED")
        print("  Immutable audit trail is working correctly.")
    else:
        print("  WARNING: Verification failed!")
        if not chain_ok:
            print("    - Chain verification FAILED")
        if not cp_ok:
            print("    - Checkpoint verification FAILED")

    client.close()


if __name__ == "__main__":
    main()
