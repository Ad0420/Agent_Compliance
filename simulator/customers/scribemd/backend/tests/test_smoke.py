"""Smoke test for the ScribeMD backend.

We boot the full FastAPI app, stub out:
  * the Vera client → in-memory recorder + canned approval responses
  * the LLM provider → deterministic canned text
…and drive the workflow end-to-end through HTTP. Asserts:
  1. Login flips the cookie + /me returns the user label
  2. Anonymous requests are 401
  3. POST /api/encounters returns 201 immediately and persists a row
  4. SSE stream emits events in order through the HITL gate
  5. POST /api/approvals/.../decide unblocks the worker; workflow terminates
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import uuid
from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient


# Force a per-run sqlite file BEFORE any backend module is imported so the
# engine is built with the right URL.
_TEST_DB = f"/tmp/scribemd_test_{uuid.uuid4().hex}.db"
os.environ["SCRIBEMD_DB_URL"] = f"sqlite+aiosqlite:///{_TEST_DB}"
os.environ.setdefault("SCRIBEMD_PASSKEY", "test-passkey-123")
# Tight approval timeout so a test that leaves a workflow at the HITL gate
# without deciding doesn't hang teardown for the full prod default (300s).
# Workflows auto-reject after this and `bus.close()` lets TestClient exit.
os.environ.setdefault("SCRIBEMD_APPROVAL_TIMEOUT_SECONDS", "5")


# ── Fakes ───────────────────────────────────────────────────────────────────


class FakeLLMResponse:
    def __init__(self, text: str, model: str):
        self.text = text
        self.input_tokens = 10
        self.output_tokens = 20
        self.model = model
        self.duration_ms = 5


class FakeOpenAILLM:
    model = "gpt-4o-mini-fake"

    def chat(self, system: str, user: str, max_tokens: int = 512) -> FakeLLMResponse:
        return FakeLLMResponse(
            text=(
                "SUBJECTIVE: Patient reports severe epigastric pain.\n"
                "OBJECTIVE: Tender to palpation, guarding present.\n"
                "ASSESSMENT: Possible: acute pancreatitis.\n"
                "PLAN: NPO, IV fluids, ondansetron, admit for observation."
            ),
            model=self.model,
        )


class FakeAnthropicLLM:
    model = "claude-fake"

    def chat(self, system: str, user: str, max_tokens: int = 512) -> FakeLLMResponse:
        return FakeLLMResponse(
            text=json.dumps(
                {
                    "diagnoses": ["Acute pancreatitis"],
                    "medication_orders": ["Ondansetron 4mg IV q6h PRN"],
                    "lab_or_imaging_orders": ["Lipase", "CBC", "Abdominal US"],
                }
            ),
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

    # All instances share an approval registry so the route handler can find
    # the pending approval even though each agent has its own client.
    _approvals: dict[str, dict] = {}
    _approval_lock = threading.Lock()

    def __init__(self, *, agent_name: str, model_id: Optional[str] = None,
                 framework: Optional[str] = None):
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

    def wait_for_approval(self, approval_id: str, timeout: float = 10.0,
                          poll_interval: float = 0.5) -> dict:
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


def fake_vera_factory(*, agent_name: str, model_id: Optional[str] = None,
                      framework: Optional[str] = None):
    return FakeVeraClient(
        agent_name=agent_name, model_id=model_id, framework=framework,
    )


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def app_with_stubs():
    # Reset module-level singletons before each test.
    from simulator.customers.scribemd.backend import auth as auth_mod
    from simulator.customers.scribemd.backend import db as db_mod
    from simulator.customers.scribemd.backend import events as events_mod
    from simulator.customers.scribemd.backend import workflow_runner

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
    from simulator.customers.scribemd.backend.main import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client

    workflow_runner.restore_default_factories()


# ── Tests ───────────────────────────────────────────────────────────────────


def test_health(app_with_stubs):
    r = app_with_stubs.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "service": "scribemd-backend"}


def test_anon_routes_are_401(app_with_stubs):
    assert app_with_stubs.get("/api/auth/me").status_code == 401
    assert app_with_stubs.get("/api/encounters").status_code == 401


def test_login_bad_passkey(app_with_stubs):
    r = app_with_stubs.post("/api/auth/login", json={"passkey": "wrong"})
    assert r.status_code == 401


def test_full_flow_approve(app_with_stubs):
    client = app_with_stubs

    # 1. login
    r = client.post("/api/auth/login", json={"passkey": "test-passkey-123"})
    assert r.status_code == 204

    # 2. /me
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["signed_in_as"] == "Dr. Adams"

    # 3. create encounter (fixture)
    r = client.post("/api/encounters", json={"fixture": "pancreatitis"})
    assert r.status_code == 201
    enc = r.json()
    enc_id = enc["id"]
    assert enc["status"] == "running"

    # 4. wait until the workflow is sitting at the HITL gate, scraping the
    # row's last_event so we know the approval id is captured.
    deadline = time.time() + 15
    approval_id = None
    while time.time() < deadline:
        r = client.get(f"/api/encounters/{enc_id}")
        assert r.status_code == 200
        body = r.json()
        if body["vera_approval_id"]:
            approval_id = body["vera_approval_id"]
            break
        time.sleep(0.05)
    assert approval_id, "workflow never reached approval_requested"

    # 5. (SSE assertion lives in test_sse_replay below — TestClient's portal
    #    can hang if a streaming response is short-circuited mid-iteration,
    #    and the snapshot endpoint's `events` column carries the same data
    #    we'd assert here, so we use that for the happy-path test instead.)

    # 6. decide
    r = client.post(
        f"/api/approvals/{approval_id}/decide",
        json={"decision": "approve", "approver": "Dr. Adams", "note": "lgtm"},
    )
    assert r.status_code == 200
    assert r.json()["received"] is True

    # 7. wait for terminal state
    deadline = time.time() + 15
    final = None
    while time.time() < deadline:
        r = client.get(f"/api/encounters/{enc_id}")
        body = r.json()
        if body["status"] in ("committed", "blocked", "auto_committed", "error"):
            final = body
            break
        time.sleep(0.05)
    assert final is not None, "workflow did not terminate"
    assert final["status"] == "committed"
    assert final["terminal_outcome"]["chart_committed"] is True
    assert final["terminal_outcome"]["approval_status"] == "approved"

    # Events column has the full ordered history
    types = [e["event"] for e in final["events"]]
    assert types[:4] == [
        "draft_started",
        "draft_complete",
        "orders_extracted",
        "approval_requested",
    ]
    assert "approval_decided" in types
    assert "chart_committed" in types


def test_full_flow_reject(app_with_stubs):
    client = app_with_stubs

    client.post("/api/auth/login", json={"passkey": "test-passkey-123"})

    r = client.post("/api/encounters", json={"fixture": "pancreatitis"})
    enc_id = r.json()["id"]

    deadline = time.time() + 15
    approval_id = None
    while time.time() < deadline:
        body = client.get(f"/api/encounters/{enc_id}").json()
        if body["vera_approval_id"]:
            approval_id = body["vera_approval_id"]
            break
        time.sleep(0.05)
    assert approval_id

    r = client.post(
        f"/api/approvals/{approval_id}/decide",
        json={"decision": "reject", "approver": "Dr. Adams", "note": "no"},
    )
    assert r.status_code == 200

    deadline = time.time() + 15
    final = None
    while time.time() < deadline:
        body = client.get(f"/api/encounters/{enc_id}").json()
        if body["status"] in ("committed", "blocked", "auto_committed", "error"):
            final = body
            break
        time.sleep(0.05)
    assert final is not None
    assert final["status"] == "blocked"
    assert "chart_blocked" in [e["event"] for e in final["events"]]


def test_decide_unknown_approval_404(app_with_stubs):
    app_with_stubs.post("/api/auth/login", json={"passkey": "test-passkey-123"})
    r = app_with_stubs.post(
        "/api/approvals/apr_does_not_exist/decide",
        json={"decision": "approve", "approver": "x"},
    )
    assert r.status_code == 404


def test_create_requires_one_input(app_with_stubs):
    app_with_stubs.post("/api/auth/login", json={"passkey": "test-passkey-123"})
    r = app_with_stubs.post("/api/encounters", json={})
    assert r.status_code == 400


def test_sse_replay(app_with_stubs):
    """Verify the SSE endpoint replays the full event history once an
    encounter has terminated. We drive the encounter to terminal state via
    decide first, *then* open the stream — this way the bus is already
    closed and the stream returns the persisted events without ever
    blocking on a live tail. Avoids TestClient's known portal-hang behavior
    when a streaming response is short-circuited mid-iteration."""
    client = app_with_stubs
    client.post("/api/auth/login", json={"passkey": "test-passkey-123"})

    r = client.post("/api/encounters", json={"fixture": "pancreatitis"})
    enc_id = r.json()["id"]

    # Wait for HITL gate
    deadline = time.time() + 15
    approval_id = None
    while time.time() < deadline:
        body = client.get(f"/api/encounters/{enc_id}").json()
        if body["vera_approval_id"]:
            approval_id = body["vera_approval_id"]
            break
        time.sleep(0.05)
    assert approval_id

    # Decide → drive to terminal state
    client.post(
        f"/api/approvals/{approval_id}/decide",
        json={"decision": "approve", "approver": "Dr. Adams"},
    )
    deadline = time.time() + 15
    while time.time() < deadline:
        if client.get(f"/api/encounters/{enc_id}").json()["status"] == "committed":
            break
        time.sleep(0.05)

    # Now stream — bus is closed, replay returns cleanly.
    seen: list[str] = []
    with client.stream("GET", f"/api/events/{enc_id}") as s:
        for line in s.iter_lines():
            if isinstance(line, bytes):
                line = line.decode("utf-8")
            if line.startswith("event:"):
                seen.append(line.split(":", 1)[1].strip())

    for required in (
        "draft_started",
        "draft_complete",
        "orders_extracted",
        "approval_requested",
        "approval_decided",
        "chart_committed",
    ):
        assert required in seen, f"missing event: {required}"


def test_list_encounters(app_with_stubs):
    client = app_with_stubs
    client.post("/api/auth/login", json={"passkey": "test-passkey-123"})

    r = client.post("/api/encounters", json={"fixture": "followup"})
    enc_id = r.json()["id"]

    # The followup fixture won't actually need approval (depends on extracted
    # orders) — just assert the list endpoint sees it.
    r = client.get("/api/encounters")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert any(e["id"] == enc_id for e in body["encounters"])
