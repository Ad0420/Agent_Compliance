"""Tests for the Review Inbox routes (W2.1 in-band HITL).

Covers:
  * Auth — unauthenticated request → 401 on all routes
  * GET /api/reviews lists what the webhook persisted
  * POST /api/reviews/{id}/decide calls Vera's SDK ``complete_review``
    helper with the right shape
  * Approve flow → SDK invoked + row stamped with decided_by
  * Reject flow with note → SDK invoked, note forwarded
  * 404 on unknown review id
  * 409 on already-decided row
  * 403 surfaces when the SDK raises ReviewerCredentialsInsufficient
  * End-to-end loop: webhook creates pending row → clinician decides →
    SDK called → simulated review.completed webhook flips row terminal
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient


os.environ.setdefault("SCRIBEMD_PASSKEY", "test-passkey-123")
os.environ.setdefault("SCRIBEMD_APPROVAL_TIMEOUT_SECONDS", "5")

_WEBHOOK_SECRET = "test-webhook-secret-please-rotate"
os.environ["SCRIBEMD_VERA_WEBHOOK_SECRET"] = _WEBHOOK_SECRET


def _sign(secret: str, body: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def _envelope(event_type: str, data: dict) -> dict:
    return {
        "event_id": uuid.uuid4().hex,
        "delivery_id": uuid.uuid4().hex,
        "event_type": event_type,
        "org_id": "org_test",
        "attempt": 1,
        "occurred_at": "2026-05-26T12:00:00+00:00",
        "data": data,
    }


def _post_webhook(client: TestClient, envelope: dict):
    body = json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode()
    return client.post(
        "/vera/webhooks",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Vera-Signature": _sign(_WEBHOOK_SECRET, body),
        },
    )


# ── Fake SDK client ─────────────────────────────────────────────────────────


class FakeVeraSDKClient:
    """In-memory recorder for the SDK's ``complete_review`` calls.

    Tests configure ``RAISE_ON_NEXT`` to simulate a branded error.
    """

    last_call: dict[str, Any] | None = None
    RAISE_ON_NEXT: Exception | None = None

    def __init__(self, *, agent_name: str, **_):
        self.agent_name = agent_name

    def complete_review(self, **kwargs):
        if FakeVeraSDKClient.RAISE_ON_NEXT is not None:
            exc = FakeVeraSDKClient.RAISE_ON_NEXT
            FakeVeraSDKClient.RAISE_ON_NEXT = None
            raise exc
        FakeVeraSDKClient.last_call = dict(kwargs)
        return {
            "id": kwargs["review_id"],
            "status": "approved" if kwargs["decision"] == "approve" else "rejected",
        }

    def close(self):
        pass


def fake_sdk_factory(*, agent_name: str, **_):
    return FakeVeraSDKClient(agent_name=agent_name)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def app_client(monkeypatch):
    db_path = f"/tmp/scribemd_inbox_test_{uuid.uuid4().hex}.db"
    monkeypatch.setenv("SCRIBEMD_DB_URL", f"sqlite+aiosqlite:///{db_path}")

    from simulator.customers.scribemd.backend import (
        auth as auth_mod,
        db as db_mod,
        events as events_mod,
        workflow_runner,
    )
    from simulator.customers.scribemd.backend.routes import reviews as reviews_route

    auth_mod.reset_sessions_for_tests()
    events_mod.reset_bus_for_tests()
    workflow_runner.reset_pending_for_tests()
    db_mod.reset_engine_for_tests()
    FakeVeraSDKClient.last_call = None
    FakeVeraSDKClient.RAISE_ON_NEXT = None
    reviews_route.install_test_vera_factory(fake_sdk_factory)

    from simulator.customers.scribemd.backend.main import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client

    reviews_route.restore_default_vera_factory()


@pytest.fixture()
def signed_in_client(app_client):
    r = app_client.post("/api/auth/login", json={"passkey": "test-passkey-123"})
    assert r.status_code == 204
    return app_client


def _seed_pending(client: TestClient, approval_id: str = "apr_demo") -> None:
    env = _envelope(
        "review.requested",
        {
            "review_id": approval_id,
            "action_name": "commit_orders",
            "risk_tier": "high",
            "required_role": "attending_physician",
            "agent_name": "scribemd-chart-committer",
            "data_subject_id": "pt_test",
            "requested_at": "2026-05-26T11:30:00+00:00",
            "expires_at": "2026-05-26T15:30:00+00:00",
            "context_excerpt": {
                "diagnoses": ["Acute pancreatitis"],
                "medication_orders": ["Ondansetron 4mg IV q6h PRN"],
            },
        },
    )
    r = _post_webhook(client, env)
    assert r.status_code == 200


# ── Auth ────────────────────────────────────────────────────────────────────


def test_anon_listing_401(app_client):
    assert app_client.get("/api/reviews").status_code == 401


def test_anon_decide_401(app_client):
    r = app_client.post(
        "/api/reviews/apr_x/decide",
        json={"decision": "approve"},
    )
    assert r.status_code == 401


# ── Listing ─────────────────────────────────────────────────────────────────


def test_list_returns_pending_after_webhook(signed_in_client):
    _seed_pending(signed_in_client, "apr_list_1")
    listing = signed_in_client.get("/api/reviews").json()
    assert listing["total"] == 1
    assert listing["items"][0]["approval_id"] == "apr_list_1"


def test_list_status_filter_all(signed_in_client):
    _seed_pending(signed_in_client, "apr_p1")
    # Mark one expired via webhook
    expired = _envelope(
        "review.expired",
        {"review_id": "apr_p1", "final_status": "expired",
         "expired_at": "2026-05-26T15:30:01+00:00"},
    )
    r = _post_webhook(signed_in_client, expired)
    assert r.status_code == 200

    all_listing = signed_in_client.get("/api/reviews?status=all").json()
    assert any(
        i["approval_id"] == "apr_p1" and i["status"] == "expired"
        for i in all_listing["items"]
    )
    pending_listing = signed_in_client.get("/api/reviews?status=pending").json()
    assert all(i["approval_id"] != "apr_p1" for i in pending_listing["items"])


def test_get_unknown_review_404(signed_in_client):
    assert signed_in_client.get("/api/reviews/apr_missing").status_code == 404


# ── Decide flow ─────────────────────────────────────────────────────────────


def test_decide_approve_calls_sdk_complete_review(signed_in_client):
    _seed_pending(signed_in_client, "apr_dec_1")

    r = signed_in_client.post(
        "/api/reviews/apr_dec_1/decide",
        json={"decision": "approve", "note": "looks correct"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["approval_id"] == "apr_dec_1"
    assert body["decided_by"] == "Dr. Adams"
    assert body["decision_note"] == "looks correct"

    # The SDK helper got called with the right args.
    call = FakeVeraSDKClient.last_call
    assert call is not None
    assert call["review_id"] == "apr_dec_1"
    assert call["decision"] == "approve"
    assert call["reviewer_role"] == "attending_physician"
    assert call["reviewer_id"] == "Dr. Adams"
    assert call["note"] == "looks correct"
    assert call.get("decided_at"), "decided_at not forwarded to SDK"


def test_decide_reject_with_role_override(signed_in_client):
    _seed_pending(signed_in_client, "apr_dec_2")

    r = signed_in_client.post(
        "/api/reviews/apr_dec_2/decide",
        json={
            "decision": "reject",
            "reviewer_role": "dea_licensed_physician",
            "note": "controlled substance not warranted",
        },
    )
    assert r.status_code == 200

    call = FakeVeraSDKClient.last_call
    assert call["decision"] == "reject"
    assert call["reviewer_role"] == "dea_licensed_physician"
    assert call["note"] == "controlled substance not warranted"


def test_decide_unknown_review_404(signed_in_client):
    r = signed_in_client.post(
        "/api/reviews/apr_missing/decide",
        json={"decision": "approve"},
    )
    assert r.status_code == 404


def test_decide_already_resolved_409(signed_in_client):
    _seed_pending(signed_in_client, "apr_taken")
    # Resolve via webhook before the clinician acts.
    done = _envelope(
        "review.completed",
        {
            "review_id": "apr_taken",
            "final_status": "approved",
            "resolved_at": "2026-05-26T12:05:00+00:00",
        },
    )
    assert _post_webhook(signed_in_client, done).status_code == 200

    r = signed_in_client.post(
        "/api/reviews/apr_taken/decide",
        json={"decision": "approve"},
    )
    assert r.status_code == 409


def test_decide_role_insufficient_surfaces_403(signed_in_client):
    """The SDK's branded `ReviewerCredentialsInsufficient` maps to HTTP 403."""
    from vera.errors import ReviewerCredentialsInsufficient

    _seed_pending(signed_in_client, "apr_role_fail")
    FakeVeraSDKClient.RAISE_ON_NEXT = ReviewerCredentialsInsufficient(
        review_id="apr_role_fail",
        reviewer_role="medical_student",
        required_role="attending_physician",
    )

    r = signed_in_client.post(
        "/api/reviews/apr_role_fail/decide",
        json={"decision": "approve", "reviewer_role": "medical_student"},
    )
    assert r.status_code == 403


def test_end_to_end_inband_loop(signed_in_client):
    """Webhook → list → decide via SDK → completion webhook → terminal."""
    _seed_pending(signed_in_client, "apr_e2e")

    # 1. The clinician sees the row.
    listing = signed_in_client.get("/api/reviews").json()
    assert any(i["approval_id"] == "apr_e2e" for i in listing["items"])

    # 2. The clinician hits Approve. SDK gets called.
    r = signed_in_client.post(
        "/api/reviews/apr_e2e/decide",
        json={"decision": "approve", "note": "ok"},
    )
    assert r.status_code == 200
    assert FakeVeraSDKClient.last_call["review_id"] == "apr_e2e"
    # The local row is optimistically stamped but still "pending" until
    # Vera's webhook arrives — so the dashboard never shows a "decided"
    # state that disagrees with the canonical audit chain.
    assert r.json()["status"] == "pending"
    assert r.json()["decided_by"] == "Dr. Adams"

    # 3. Vera fires review.completed back at us.
    confirm = _envelope(
        "review.completed",
        {
            "review_id": "apr_e2e",
            "final_status": "approved",
            "resolved_at": "2026-05-26T12:05:00+00:00",
            "decisions": [
                {
                    "reviewer_id": "Dr. Adams",
                    "note": "ok",
                    "decided_at": "2026-05-26T12:04:59+00:00",
                }
            ],
        },
    )
    assert _post_webhook(signed_in_client, confirm).status_code == 200

    # 4. The row flips terminal.
    item = signed_in_client.get("/api/reviews/apr_e2e").json()
    assert item["status"] == "approved"
