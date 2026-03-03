import sys
import httpx

API_KEY = "al_live_jVFRycQFZAQyfzeSo0ML_XQhXq1EiideBqc0f3bNEJg"

client = httpx.Client(
    base_url="http://localhost:8000",
    headers={"Authorization": f"Bearer {API_KEY}"}
)

actions = [
    {
        "action_name": "approve_loan",
        "action_type": "decision",
        "agent_name": "credit-agent",
        "model_id": "gpt-4o",
        "result": "success",
        "input_data": {"applicant": "Alice", "amount": 5000},
        "outcome": {"approved": True},
        "reasoning": {"confidence": 0.95},
    },
    {
        "action_name": "flag_transaction",
        "action_type": "decision",
        "agent_name": "fraud-agent",
        "model_id": "gpt-4o",
        "result": "success",
        "input_data": {"tx_id": "TX-001", "amount": 99999},
        "outcome": {"flagged": True},
        "reasoning": {"rule": "exceeds_threshold"},
    },
    {
        "action_name": "generate_report",
        "action_type": "llm_call",
        "agent_name": "report-agent",
        "model_id": "claude-sonnet-4-6",
        "result": "success",
        "input_data": {"period": "Q1 2026"},
        "outcome": {"pages": 12},
        "reasoning": {},
    },
    {
        "action_name": "send_alert",
        "action_type": "api_call",
        "agent_name": "fraud-agent",
        "model_id": "gpt-4o",
        "result": "failure",
        "error_message": "Slack API timeout",
        "input_data": {"channel": "#alerts"},
        "outcome": {},
        "reasoning": {},
    },
    {
        "action_name": "review_hiring",
        "action_type": "decision",
        "agent_name": "hr-agent",
        "model_id": "gpt-4o",
        "result": "success",
        "input_data": {"candidate": "Bob", "role": "engineer"},
        "outcome": {"recommended": True},
        "reasoning": {"confidence": 0.88},
    },
]

for a in actions:
    r = client.post("/v1/actions", json=a)
    print(f"  {r.status_code} — {a['action_name']}")

print("\nDone! Refresh http://localhost:3000")
