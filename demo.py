"""
End-to-end demo for the Action Ledger.

Prerequisites:
  1. cd backend && python setup_local.py   (creates DB + org + API key)
  2. cd backend && uvicorn app.main:app --reload  (starts server on :8000)
  3. cd sdk && pip install -e .             (install SDK)
  4. python demo.py <YOUR_API_KEY>
"""
import sys
import time

from actionledger import ActionLedgerClient, audit, set_default_client


def main():
    if len(sys.argv) < 2:
        print("Usage: python demo.py <API_KEY>")
        print("  Get your API key by running: cd backend && python setup_local.py")
        sys.exit(1)

    api_key = sys.argv[1]

    # ── 1. Initialize client ──────────────────────────────
    client = ActionLedgerClient(
        api_url="http://localhost:8000",
        api_key=api_key,
        agent_name="demo-agent",
        agent_version="1.0.0",
        model_id="gpt-4o",
        framework="custom",
    )
    set_default_client(client)
    print("[1/8] SDK client initialized")

    # ── 2. Register an agent ──────────────────────────────
    agent = client.register_agent(
        name="demo-agent",
        description="A demo agent for testing the Action Ledger",
        metadata={"purpose": "demo", "version": "1.0.0"},
    )
    print(f"[2/8] Agent registered: {agent['name']} (id: {agent['id']})")

    # ── 3. Define audited functions ───────────────────────
    @audit(action_name="analyze_data", action_type="computation")
    def analyze_data(dataset: str, threshold: float):
        """Simulated data analysis."""
        time.sleep(0.1)
        return {"records_processed": 1500, "anomalies_found": 3, "threshold": threshold}

    @audit(action_name="send_notification", action_type="notification")
    def send_notification(recipient: str, message: str):
        """Simulated notification."""
        time.sleep(0.05)
        return {"delivered": True, "recipient": recipient}

    @audit(action_name="update_database", action_type="db_write")
    def update_database(table: str, record_id: int, updates: dict):
        """Simulated database update."""
        time.sleep(0.05)
        return {"rows_affected": 1}

    @audit(action_name="risky_operation", action_type="api_call")
    def risky_operation():
        """This one will fail."""
        time.sleep(0.02)
        raise ValueError("Simulated failure for demo purposes")

    # ── 4. Call the functions ─────────────────────────────
    print("[3/8] Running audited functions...")

    result1 = analyze_data("sales_q4", threshold=0.95)
    print(f"  - analyze_data: {result1}")

    result2 = send_notification("admin@example.com", "Analysis complete")
    print(f"  - send_notification: {result2}")

    result3 = update_database("customers", 42, {"status": "active"})
    print(f"  - update_database: {result3}")

    try:
        risky_operation()
    except ValueError:
        print("  - risky_operation: failed (expected)")

    # ── 5. Query the API ──────────────────────────────────
    print("[4/8] Querying action records...")
    actions = client.query_actions(limit=10)
    print(f"  Found {actions['total']} action records:")
    for rec in actions["records"]:
        print(f"    #{rec['sequence_number']} {rec['action_name']} -> {rec['result']}"
              f" (hash: {rec['record_hash'][:16]}...)")

    # ── 6. Verify the chain ───────────────────────────────
    print("[5/8] Verifying chain integrity...")
    verification = client.verify_chain()
    print(f"  Valid: {verification['is_valid']}")
    print(f"  Records checked: {verification['records_checked']}")
    print(f"  Message: {verification['message']}")

    # ── 7. Checkpoint creation + verification ─────────────
    print("[6/8] Creating checkpoint...")
    checkpoint = client.create_checkpoint()
    print(f"  Checkpoint ID: {checkpoint['id']}")
    print(f"  Sequence: {checkpoint['sequence_at_checkpoint']}")
    print(f"  Hash: {checkpoint['hash_at_checkpoint'][:16]}...")
    print(f"  Signature: {checkpoint['signature'][:16]}...")

    print("[7/8] Verifying all checkpoints...")
    cp_verification = client.verify_checkpoints()
    print(f"  All valid: {cp_verification['all_valid']}")
    print(f"  Total checked: {cp_verification['total_checked']}")
    for r in cp_verification["results"]:
        print(f"    Checkpoint seq={r['sequence']} valid={r['is_valid']}")

    # ── 8. Optional framework integration demos ──────────
    print("[8/8] Framework integration demos...")

    # LangChain integration demo
    try:
        from langchain_core.callbacks import BaseCallbackHandler
        from actionledger.integrations.langchain import ActionLedgerCallbackHandler

        handler = ActionLedgerCallbackHandler(client=client)
        print("  LangChain: ActionLedgerCallbackHandler ready")
        print(f"    Usage: chain.invoke(inputs, config={{'callbacks': [handler]}})")
    except ImportError:
        print("  LangChain: not installed (pip install actionledger[langchain])")

    # OpenAI integration demo
    try:
        import openai
        from actionledger.integrations.openai import AuditedOpenAI

        print("  OpenAI: AuditedOpenAI wrapper available")
        print("    Usage: client = AuditedOpenAI(openai.OpenAI(), ledger_client=ledger)")
    except ImportError:
        print("  OpenAI: not installed (pip install actionledger[openai])")

    # CrewAI integration demo
    try:
        from actionledger.integrations.crewai import enable_crewai_auditing

        print("  CrewAI: enable_crewai_auditing() available")
        print("    Usage: enable_crewai_auditing(client=ledger)")
    except ImportError:
        print("  CrewAI: not installed (pip install actionledger[crewai])")

    # ── Summary ───────────────────────────────────────────
    print()
    print("=" * 50)
    print("Demo complete!")
    print("=" * 50)
    if verification["is_valid"] and cp_verification["all_valid"]:
        print("  Chain verification: PASSED")
        print("  Checkpoint verification: PASSED")
        print("  The immutable audit trail is working correctly.")
    else:
        print("  WARNING: Verification failed!")
        if not verification["is_valid"]:
            print("    - Chain verification FAILED")
        if not cp_verification["all_valid"]:
            print("    - Checkpoint verification FAILED")

    client.close()


if __name__ == "__main__":
    main()
