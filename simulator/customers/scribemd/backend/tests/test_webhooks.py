"""Tests for POST /vera/webhooks (W2.1 in-band HITL).

Covers:
  * HMAC signature verification (good / bad / missing / wrong format)
  * Missing webhook secret → 503
  * approval.requested + review.requested both create one pending row
  * Duplicate delivery is idempotent on (approval_id, event_type)
  * approval.resolved → row flipped + encounter cascade
  * review.completed has the same effect (alias)
  * review.expired → row marked expired + encounter cascade
  * Unknown event types → 200 ignored
  * Malformed payloads → 4xx without mutation
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid

import pytest
from fastapi.testclient import TestClient


os.environ.setdefault("SCRIBEMD_PASSKEY", "test-passkey-123")
os.environ.setdefault("SCRIBEMD_APPROVAL_TIMEOUT_SECONDS", "5")

_WEBHOOK_SECRET = "test-webhook-secret-please-rotate"
os.environ["SCRIBEMD_VERA_WEBHOOK_SECRET"] = _WEBHOOK_SECRET


# ── Helpers ─────────────────────────────────────────────────────────────────


def _sign(secret: str, body: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def _envelope(event_type: str, data: dict, *, event_id: str | None = None) -> dict:
    return {
        "event_id": event_id or uuid.uuid4().hex,
        "delivery_id": event_id or uuid.uuid4().hex,
        "event_type": event_type,
        "org_id": "org_test",
        "attempt": 1,
        "occurred_at": "2026-05-26T12:00:00+00:00",
        "data": data,
    }


def _post(client: TestClient, envelope: dict, *, secret: str | None = None):
    secret = secret if secret is not None else _WEBHOOK_SECRET
    body = json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Vera-Event": envelope["event_type"],
        "X-Vera-Signature": _sign(secret, body),
    }
    return client.post("/vera/webhooks", content=body, headers=headers)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def app_client(monkeypatch):
    # Per-test sqlite file so multiple tests + multiple files share no
    # state. Set BEFORE backend modules build their engine.
    db_path = f"/tmp/scribemd_webhook_test_{uuid.uuid4().hex}.db"
    monkeypatch.setenv("SCRIBEMD_DB_URL", f"sqlite+aiosqlite:///{db_path}")

    from simulator.customers.scribemd.backend import (
        auth as auth_mod,
        db as db_mod,
        events as events_mod,
        workflow_runner,
    )

    auth_mod.reset_sessions_for_tests()
    events_mod.reset_bus_for_tests()
    workflow_runner.reset_pending_for_tests()
    db_mod.reset_engine_for_tests()

    from simulator.customers.scribemd.backend.main import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client


# ── Signature verification ──────────────────────────────────────────────────


def test_missing_signature_header_401(app_client):
    body = json.dumps(
        _envelope("review.requested", {"review_id": "apr_x"}),
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    r = app_client.post("/vera/webhooks", content=body, headers={
        "Content-Type": "application/json",
    })
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid_signature"


def test_bad_signature_401(app_client):
    env = _envelope("review.requested", {"review_id": "apr_x"})
    body = json.dumps(env, separators=(",", ":"), sort_keys=True).encode()
    r = app_client.post(
        "/vera/webhooks",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Vera-Signature": "sha256=deadbeef",
        },
    )
    assert r.status_code == 401


def test_wrong_signature_format_401(app_client):
    env = _envelope("review.requested", {"review_id": "apr_x"})
    body = json.dumps(env, separators=(",", ":"), sort_keys=True).encode()
    r = app_client.post(
        "/vera/webhooks",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Vera-Signature": _sign(_WEBHOOK_SECRET, body).split("=", 1)[1],  # missing prefix
        },
    )
    assert r.status_code == 401


def test_signature_uses_wrong_secret_401(app_client):
    env = _envelope("review.requested", {"review_id": "apr_x"})
    r = _post(app_client, env, secret="some-other-secret")
    assert r.status_code == 401


def test_missing_webhook_secret_returns_503(app_client):
    """If the operator misconfigures the deployment we fail closed."""
    from simulator.customers.scribemd.backend import config

    real_settings = config.get_settings

    def fake_settings():
        s = real_settings()
        return config.Settings(
            passkey=s.passkey,
            signed_in_as=s.signed_in_as,
            db_url=s.db_url,
            vera_url=s.vera_url,
            cors_origins=s.cors_origins,
            cookie_name=s.cookie_name,
            cookie_max_age_seconds=s.cookie_max_age_seconds,
            approval_timeout_seconds=s.approval_timeout_seconds,
            vera_webhook_secret=None,
        )

    # FastAPI's dependency override is the supported way to swap the
    # ``Depends(get_settings)`` resolution for one test.
    app_client.app.dependency_overrides[config.get_settings] = fake_settings
    try:
        env = _envelope("review.requested", {"review_id": "apr_x"})
        body = json.dumps(env, separators=(",", ":"), sort_keys=True).encode()
        # Sign with a real-looking signature; with no secret configured we
        # MUST reject before signature comparison anyway.
        headers = {
            "Content-Type": "application/json",
            "X-Vera-Signature": _sign(_WEBHOOK_SECRET, body),
        }
        r = app_client.post("/vera/webhooks", content=body, headers=headers)
        assert r.status_code == 503
        assert r.json()["detail"] == "webhook_secret_not_configured"
    finally:
        app_client.app.dependency_overrides.pop(config.get_settings, None)


# ── Happy-path event handling ───────────────────────────────────────────────


def test_review_requested_creates_inbox_row(app_client):
    env = _envelope(
        "review.requested",
        {
            "review_id": "apr_req_1",
            "action_name": "commit_orders",
            "agent_name": "scribemd-chart-committer",
            "risk_tier": "high",
            "required_role": "attending_physician",
            "data_subject_id": "pt_123",
            "requested_at": "2026-05-26T11:30:00+00:00",
            "expires_at": "2026-05-26T15:30:00+00:00",
            "context_excerpt": {
                "diagnoses": ["Acute pancreatitis"],
                "medication_orders": ["Ondansetron 4mg IV q6h PRN"],
                "encounter_id": "enc_local_1",
            },
        },
    )
    r = _post(app_client, env)
    assert r.status_code == 200
    assert r.json()["applied"] is True

    # Login and check via the API
    app_client.post("/api/auth/login", json={"passkey": "test-passkey-123"})
    listing = app_client.get("/api/reviews?status=pending").json()
    assert listing["total"] == 1
    item = listing["items"][0]
    assert item["approval_id"] == "apr_req_1"
    assert item["status"] == "pending"
    assert item["risk_tier"] == "high"
    assert item["required_role"] == "attending_physician"
    assert item["encounter_id"] == "enc_local_1"
    assert item["context_excerpt"]["diagnoses"] == ["Acute pancreatitis"]


def test_legacy_approval_requested_creates_row(app_client):
    """The legacy ``approval.requested`` payload still populates the inbox."""
    env = _envelope(
        "approval.requested",
        {
            "approval_id": "apr_legacy_1",
            "action_name": "commit_orders",
            "risk_tier": "medium",
        },
    )
    r = _post(app_client, env)
    assert r.status_code == 200
    assert r.json()["applied"] is True

    app_client.post("/api/auth/login", json={"passkey": "test-passkey-123"})
    listing = app_client.get("/api/reviews?status=pending").json()
    assert any(i["approval_id"] == "apr_legacy_1" for i in listing["items"])


def test_idempotent_on_approval_id_plus_event_type(app_client):
    """Vera retrying the same delivery must be a no-op the second time."""
    env_id = uuid.uuid4().hex
    env = _envelope(
        "review.requested",
        {"review_id": "apr_dup", "risk_tier": "high"},
        event_id=env_id,
    )
    r1 = _post(app_client, env)
    r2 = _post(app_client, env)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["applied"] is True
    assert r2.json()["applied"] is False
    assert r2.json()["reason"] == "duplicate"

    app_client.post("/api/auth/login", json={"passkey": "test-passkey-123"})
    listing = app_client.get("/api/reviews?status=pending").json()
    rows = [i for i in listing["items"] if i["approval_id"] == "apr_dup"]
    assert len(rows) == 1, "duplicate webhook created a second row"


def test_review_completed_flips_row(app_client):
    # Stage a pending row first.
    req = _envelope(
        "review.requested",
        {
            "review_id": "apr_done_1",
            "risk_tier": "high",
            "context_excerpt": {},
        },
    )
    assert _post(app_client, req).status_code == 200

    done = _envelope(
        "review.completed",
        {
            "review_id": "apr_done_1",
            "final_status": "approved",
            "resolved_at": "2026-05-26T12:05:00+00:00",
            "decisions": [
                {
                    "reviewer_id": "Dr. Adams",
                    "note": "looks good",
                    "decided_at": "2026-05-26T12:04:58+00:00",
                }
            ],
            "resolution_record_id": "rec_abc",
        },
    )
    r = _post(app_client, done)
    assert r.status_code == 200
    assert r.json()["applied"] is True

    app_client.post("/api/auth/login", json={"passkey": "test-passkey-123"})
    item = app_client.get("/api/reviews/apr_done_1").json()
    assert item["status"] == "approved"
    assert item["decided_by"] == "Dr. Adams"
    assert item["decision_note"] == "looks good"


def test_approval_resolved_alias_flips_row(app_client):
    """Legacy ``approval.resolved`` should resolve the same as ``review.completed``."""
    req = _envelope(
        "approval.requested",
        {"approval_id": "apr_legacy_done", "risk_tier": "low"},
    )
    assert _post(app_client, req).status_code == 200

    done = _envelope(
        "approval.resolved",
        {
            "approval_id": "apr_legacy_done",
            "final_status": "rejected",
            "resolved_at": "2026-05-26T12:05:00+00:00",
            "decisions": [],
        },
    )
    r = _post(app_client, done)
    assert r.status_code == 200

    app_client.post("/api/auth/login", json={"passkey": "test-passkey-123"})
    item = app_client.get("/api/reviews/apr_legacy_done").json()
    assert item["status"] == "rejected"


def test_review_expired_marks_row(app_client):
    req = _envelope(
        "review.requested",
        {"review_id": "apr_exp_1", "risk_tier": "critical"},
    )
    assert _post(app_client, req).status_code == 200

    expired = _envelope(
        "review.expired",
        {
            "review_id": "apr_exp_1",
            "final_status": "expired",
            "expired_at": "2026-05-26T15:30:01+00:00",
        },
    )
    r = _post(app_client, expired)
    assert r.status_code == 200

    app_client.post("/api/auth/login", json={"passkey": "test-passkey-123"})
    item = app_client.get("/api/reviews/apr_exp_1").json()
    assert item["status"] == "expired"


def test_unknown_event_type_returns_200_ignored(app_client):
    env = _envelope("policy.violation", {"approval_id": "apr_irrelevant"})
    r = _post(app_client, env)
    assert r.status_code == 200
    assert r.json()["applied"] is False
    assert r.json()["reason"] == "event_ignored"


def test_missing_event_type_400(app_client):
    body = json.dumps(
        {"event_id": "x", "data": {}},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    r = app_client.post(
        "/vera/webhooks",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Vera-Signature": _sign(_WEBHOOK_SECRET, body),
        },
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "missing_event_type"


def test_invalid_json_400(app_client):
    body = b"this is not JSON"
    r = app_client.post(
        "/vera/webhooks",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Vera-Signature": _sign(_WEBHOOK_SECRET, body),
        },
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_json"


def test_oversized_body_rejected_413(app_client):
    """A 100KB body should bounce before HMAC verification or DB writes.

    Defends against a malformed/malicious caller forcing us to buffer
    megabytes of bytes ahead of signature verification.
    """
    big_payload = {"event_type": "review.requested", "data": {"review_id": "x", "padding": "A" * 100_000}}
    body = json.dumps(big_payload, separators=(",", ":"), sort_keys=True).encode()
    assert len(body) > 64 * 1024
    r = app_client.post(
        "/vera/webhooks",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Vera-Signature": _sign(_WEBHOOK_SECRET, body),
        },
    )
    assert r.status_code == 413
    assert r.json()["detail"] == "payload_too_large"


def test_completed_without_pending_row_is_safe(app_client):
    """Out-of-order delivery: completed lands before requested.

    This shouldn't crash. The idempotency ledger advances so a later
    requested arrival creates the row but the completed mutation is
    a no-op (no row to flip)."""
    done = _envelope(
        "review.completed",
        {
            "review_id": "apr_orphan",
            "final_status": "approved",
            "resolved_at": "2026-05-26T12:05:00+00:00",
        },
    )
    r = _post(app_client, done)
    assert r.status_code == 200
    assert r.json()["applied"] is True

    app_client.post("/api/auth/login", json={"passkey": "test-passkey-123"})
    r = app_client.get("/api/reviews/apr_orphan")
    assert r.status_code == 404
