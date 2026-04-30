"""Smoke test for the TriageGuard backend.

Boots the full FastAPI app, stubs out:
  * the Vera client → in-memory recorder + canned approval responses
  * the LLM provider → deterministic canned text keyed off the symptom blob
…and drives the workflow end-to-end through HTTP. Asserts:
  1. Login flips the cookie + /me returns the user label
  2. Anonymous requests are 401
  3. POST /api/sessions returns 201 immediately and persists a row
  4. The chest-pain fixture trips the HITL gate; nurse confirm/escalate
     drive the right final level
  5. The easy fixture skips HITL entirely
  6. The SSE stream replays the full history once a session has terminated
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Optional

import pytest
from fastapi.testclient import TestClient


# Force a per-run sqlite file BEFORE any backend module is imported so the
# engine is built with the right URL.
_TEST_DB = f"/tmp/triageguard_test_{uuid.uuid4().hex}.db"
os.environ["TRIAGEGUARD_DB_URL"] = f"sqlite+aiosqlite:///{_TEST_DB}"
os.environ.setdefault("TRIAGEGUARD_PASSKEY", "test-passkey-123")
# Tight review timeout so a test that leaves a workflow at the HITL gate
# without deciding doesn't hang teardown for the full prod default (300s).
# Workflows auto-escalate after this and `bus.close()` lets TestClient exit.
os.environ.setdefault("TRIAGEGUARD_REVIEW_TIMEOUT_SECONDS", "5")


# ── Fakes ──────────────────────────────────────────────────────────────────


class FakeLLMResponse:
    def __init__(self, text: str, model: str):
        self.text = text
        self.input_tokens = 10
        self.output_tokens = 20
        self.model = model
        self.duration_ms = 5


class FakeOpenAILLM:
    """Triage classifier fake. Picks a level based on the symptom narrative."""

    model = "gpt-4o-mini-fake"

    def chat(self, system: str, user: str, max_tokens: int = 512) -> FakeLLMResponse:
        blob = user.lower()
        if "chest" in blob and "jaw" in blob:
            level = "virtual_visit"
            reasoning = "Chest pressure with mild jaw radiation; worth a video visit."
            confidence = 0.55
        elif "runny nose" in blob or "low-grade fever" in blob:
            level = "self_care"
            reasoning = "Mild upper-respiratory symptoms; self-care appropriate."
            confidence = 0.85
        else:
            level = "virtual_visit"
            reasoning = "Symptoms warrant a virtual visit."
            confidence = 0.7

        return FakeLLMResponse(
            text=json.dumps(
                {
                    "level": level,
                    "reasoning": reasoning,
                    "confidence": confidence,
                }
            ),
            model=self.model,
        )


class FakeAnthropicLLM:
    """Red-flag detector fake. Flags chest-pain narratives."""

    model = "claude-fake"

    def chat(self, system: str, user: str, max_tokens: int = 512) -> FakeLLMResponse:
        blob = user.lower()
        if "chest" in blob and ("jaw" in blob or "diaphor" in blob or "sweating" in blob):
            payload = {
                "flagged": True,
                "terms": ["chest pain", "diaphoresis", "jaw radiation"],
                "recommended_override": "ER",
                "reasoning": (
                    "Chest pain with diaphoresis and jaw radiation in a "
                    "middle-aged male — ACS until proven otherwise."
                ),
            }
        else:
            payload = {
                "flagged": False,
                "terms": [],
                "recommended_override": None,
                "reasoning": "No high-risk red-flag terms identified.",
            }

        return FakeLLMResponse(
            text=json.dumps(payload),
            model=self.model,
        )


def fake_llm_factory(name: str):
    if name == "openai":
        return FakeOpenAILLM()
    if name == "anthropic":
        return FakeAnthropicLLM()
    raise ValueError(name)


class FakeVeraClient:
    """Records every action; resolves approvals when the test pokes it."""

    # All instances share an approval registry so the route handler can
    # find the pending approval even though each agent has its own client.
    _approvals: dict[str, dict] = {}
    _approval_lock = threading.Lock()

    def __init__(
        self,
        *,
        agent_name: str,
        model_id: Optional[str] = None,
        framework: Optional[str] = None,
    ):
        self.agent_name = agent_name
        self.model_id = model_id
        self.framework = framework
        self.records: list[dict] = []

    def record_action(self, **kwargs) -> dict:
        rec = {
            "id": f"rec_{uuid.uuid4().hex[:12]}",
            "sequence_number": len(self.records) + 1,
            **kwargs,
        }
        self.records.append(rec)
        return rec

    def request_approval(self, **kwargs) -> dict:
        approval_id = f"apr_{uuid.uuid4().hex[:12]}"
        approval = {
            "id": approval_id,
            "status": "pending",
            "context": kwargs.get("context", {}),
            "risk_tier": kwargs.get("risk_tier"),
        }
        with FakeVeraClient._approval_lock:
            FakeVeraClient._approvals[approval_id] = approval
        return approval

    @property
    def _client(self):  # mimics the SDK's underlying httpx client
        return self  # we'll intercept .post below

    def post(self, path: str, json: dict | None = None):  # noqa: A002
        # Match _decide_approval_via_api's call shape.
        approval_id = path.split("/")[-2]
        with FakeVeraClient._approval_lock:
            approval = FakeVeraClient._approvals.get(approval_id)
            if approval is not None:
                approval["status"] = (
                    "approved" if json["decision"] == "approve" else "rejected"
                )
                approval["approver"] = json["approver"]
                approval["note"] = json.get("note")

        class _Resp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self_inner):  # noqa: N805
                return approval

        return _Resp()

    def wait_for_approval(
        self, approval_id: str, timeout: float = 10.0, poll_interval: float = 0.5
    ) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with FakeVeraClient._approval_lock:
                approval = FakeVeraClient._approvals.get(approval_id, {})
            if approval.get("status") in ("approved", "rejected", "expired"):
                if approval["status"] == "rejected":
                    from vera import ApprovalRejectedError
                    raise ApprovalRejectedError(approval)
                return approval
            time.sleep(poll_interval)
        raise TimeoutError(f"approval {approval_id} did not resolve in {timeout}s")

    def close(self) -> None:
        pass


def fake_vera_factory(
    *,
    agent_name: str,
    model_id: Optional[str] = None,
    framework: Optional[str] = None,
):
    return FakeVeraClient(
        agent_name=agent_name, model_id=model_id, framework=framework,
    )


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture()
def app_with_stubs():
    # Reset module-level singletons before each test.
    from simulator.customers.triageguard.backend import auth as auth_mod
    from simulator.customers.triageguard.backend import db as db_mod
    from simulator.customers.triageguard.backend import events as events_mod
    from simulator.customers.triageguard.backend import workflow_runner

    auth_mod.reset_sessions_for_tests()
    events_mod.reset_bus_for_tests()
    workflow_runner.reset_pending_for_tests()
    db_mod.reset_engine_for_tests()
    FakeVeraClient._approvals.clear()

    workflow_runner.install_test_factories(
        vera_factory=fake_vera_factory,
        llm_factory=fake_llm_factory,
    )

    # We must import main AFTER env vars are set and engine is reset.
    from simulator.customers.triageguard.backend.main import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client

    workflow_runner.restore_default_factories()


def _login(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"passkey": "test-passkey-123"})
    assert r.status_code == 204


def _wait_for_review(client: TestClient, ses_id: str, timeout: float = 15.0) -> str:
    """Poll the snapshot endpoint until vera_approval_id appears. Returns it."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/sessions/{ses_id}")
        assert r.status_code == 200
        body = r.json()
        if body["vera_approval_id"]:
            return body["vera_approval_id"]
        time.sleep(0.05)
    raise AssertionError("workflow never reached nurse_review_requested")


def _wait_for_terminal(client: TestClient, ses_id: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/sessions/{ses_id}").json()
        if body["status"] in ("routed", "routing_blocked", "error"):
            return body
        time.sleep(0.05)
    raise AssertionError("workflow did not terminate")


# ── Tests ─────────────────────────────────────────────────────────────────


def test_health(app_with_stubs):
    r = app_with_stubs.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "service": "triageguard-backend"}


def test_anon_routes_are_401(app_with_stubs):
    assert app_with_stubs.get("/api/auth/me").status_code == 401
    assert app_with_stubs.get("/api/sessions").status_code == 401


def test_login_bad_passkey(app_with_stubs):
    r = app_with_stubs.post("/api/auth/login", json={"passkey": "wrong"})
    assert r.status_code == 401


def test_full_flow_confirm(app_with_stubs):
    """Chest-pain fixture: classifier under-triages to virtual_visit;
    detector flags; nurse CONFIRMS the AI level. Final = AI level."""
    client = app_with_stubs
    _login(client)

    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["signed_in_as"] == "Nurse Rivera, RN"

    r = client.post("/api/sessions", json={"fixture": "red_flag_chest_pain"})
    assert r.status_code == 201
    ses = r.json()
    ses_id = ses["id"]
    assert ses["status"] == "running"

    approval_id = _wait_for_review(client, ses_id)

    # Patient summary should be populated with safe summary fields.
    body = client.get(f"/api/sessions/{ses_id}").json()
    assert body["patient_summary"] is not None
    assert body["patient_summary"].get("mrn", "").startswith("MRN-")

    r = client.post(
        f"/api/reviews/{approval_id}/decide",
        json={
            "decision": "confirm",
            "nurse": "Nurse Rivera, RN",
            "note": "Confirming AI's call.",
        },
    )
    assert r.status_code == 200
    assert r.json()["received"] is True

    final = _wait_for_terminal(client, ses_id)
    assert final["status"] == "routed"
    out = final["terminal_outcome"]
    assert out["routing_committed"] is True
    assert out["red_flag_fired"] is True
    assert out["initial_level"] == "virtual_visit"
    # nurse confirmed → final = AI's level
    assert out["final_level"] == "virtual_visit"
    assert out["nurse_status"] == "confirm"

    types = [e["event"] for e in final["events"]]
    assert types[:4] == [
        "session_started",
        "triage_classified",
        "red_flag_evaluated",
        "nurse_review_requested",
    ]
    assert "nurse_decided" in types
    assert "routed" in types


def test_full_flow_escalate(app_with_stubs):
    """Chest-pain fixture: nurse ESCALATES → final = ER override."""
    client = app_with_stubs
    _login(client)

    r = client.post("/api/sessions", json={"fixture": "red_flag_chest_pain"})
    ses_id = r.json()["id"]

    approval_id = _wait_for_review(client, ses_id)

    r = client.post(
        f"/api/reviews/{approval_id}/decide",
        json={
            "decision": "escalate",
            "nurse": "Nurse Rivera, RN",
            "note": "ACS until proven otherwise — ER.",
        },
    )
    assert r.status_code == 200

    final = _wait_for_terminal(client, ses_id)
    assert final["status"] == "routed"
    out = final["terminal_outcome"]
    assert out["routing_committed"] is True
    assert out["nurse_status"] == "escalate"
    assert out["final_level"] == "ER"
    assert out["recommended_override"] == "ER"
    assert out["risk_tier"] == "critical"


def test_no_hitl_when_clear(app_with_stubs):
    """Easy fixture: classifier=self_care, detector=unflagged → no HITL gate."""
    client = app_with_stubs
    _login(client)

    r = client.post("/api/sessions", json={"fixture": "easy_self_care"})
    ses_id = r.json()["id"]

    final = _wait_for_terminal(client, ses_id)
    assert final["status"] == "routed"
    assert final["vera_approval_id"] is None
    out = final["terminal_outcome"]
    assert out["red_flag_fired"] is False
    assert out["nurse_status"] == "auto"
    assert out["final_level"] == "self_care"
    assert out["risk_tier"] == "low"

    types = [e["event"] for e in final["events"]]
    assert "nurse_review_requested" not in types
    assert "routed" in types


def test_sse_replay(app_with_stubs):
    """Drive the session to terminal first, then drain SSE — bus is
    already closed, so replay returns persisted events without ever
    blocking on a live tail. Same anti-deadlock pattern as ScribeMD."""
    client = app_with_stubs
    _login(client)

    r = client.post("/api/sessions", json={"fixture": "red_flag_chest_pain"})
    ses_id = r.json()["id"]

    approval_id = _wait_for_review(client, ses_id)
    client.post(
        f"/api/reviews/{approval_id}/decide",
        json={"decision": "escalate", "nurse": "Nurse Rivera, RN"},
    )
    final = _wait_for_terminal(client, ses_id)
    assert final["status"] == "routed"

    seen: list[str] = []
    with client.stream("GET", f"/api/events/{ses_id}") as s:
        for line in s.iter_lines():
            if isinstance(line, bytes):
                line = line.decode("utf-8")
            if line.startswith("event:"):
                seen.append(line.split(":", 1)[1].strip())

    for required in (
        "session_started",
        "triage_classified",
        "red_flag_evaluated",
        "nurse_review_requested",
        "nurse_decided",
        "routed",
    ):
        assert required in seen, f"missing event: {required}"


def test_decide_unknown_review_404(app_with_stubs):
    _login(app_with_stubs)
    r = app_with_stubs.post(
        "/api/reviews/apr_does_not_exist/decide",
        json={"decision": "confirm", "nurse": "x"},
    )
    assert r.status_code == 404


def test_create_requires_one_input(app_with_stubs):
    _login(app_with_stubs)
    r = app_with_stubs.post("/api/sessions", json={})
    assert r.status_code == 400


def test_list_sessions(app_with_stubs):
    client = app_with_stubs
    _login(client)

    r = client.post("/api/sessions", json={"fixture": "ambiguous"})
    ses_id = r.json()["id"]

    r = client.get("/api/sessions")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert any(s["id"] == ses_id for s in body["sessions"])
