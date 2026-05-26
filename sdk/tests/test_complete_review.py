"""Tests for ``VeraClient.complete_review`` (W2.1).

Wraps the ``POST /v1/reviews/{review_id}/complete`` endpoint with the
right body shape so customer EHRs can resolve a HITL approval via the
audited SDK rather than raw httpx.
"""

from __future__ import annotations

import json

import httpx
import pytest

import vera.client as client_mod
from vera import ReviewerCredentialsInsufficient, VeraClient


def _make_client(monkeypatch) -> VeraClient:
    monkeypatch.setattr(client_mod, "MAX_RETRIES", 1)
    monkeypatch.setattr(client_mod, "RETRY_BACKOFF_BASE", 0.0)
    return VeraClient(
        api_url="http://localhost:1",
        api_key="test",
        flush_interval=60.0,
        atexit_drain_timeout=0.1,
    )


def test_complete_review_posts_to_correct_url(monkeypatch):
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["method"] = req.method
        captured["body"] = json.loads(req.content.decode() or "{}")
        return httpx.Response(
            200,
            json={
                "id": "apr_x",
                "status": "approved",
                "resolution_record_id": "rec_y",
            },
        )

    c = _make_client(monkeypatch)
    c._client._transport = httpx.MockTransport(handler)
    try:
        result = c.complete_review(
            review_id="apr_x",
            decision="approve",
            reviewer_role="attending_physician",
            reviewer_id="dr.adams@hospital.example",
            note="orders look correct",
        )
    finally:
        c.close()

    assert captured["method"] == "POST"
    assert captured["url"].endswith("/v1/reviews/apr_x/complete")
    assert captured["body"] == {
        "decision": "approve",
        "reviewer_role": "attending_physician",
        "reviewer_id": "dr.adams@hospital.example",
        "note": "orders look correct",
    }
    assert result["status"] == "approved"


def test_complete_review_omits_optional_fields_when_unset(monkeypatch):
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.content.decode() or "{}")
        return httpx.Response(200, json={"id": "apr_x", "status": "rejected"})

    c = _make_client(monkeypatch)
    c._client._transport = httpx.MockTransport(handler)
    try:
        c.complete_review(
            review_id="apr_x",
            decision="reject",
            reviewer_role="attending_physician",
            reviewer_id="dr.smith",
        )
    finally:
        c.close()

    # Optional fields (`note`, `signature`, `decided_at`) shouldn't appear
    # in the body when omitted — keeps the backend's strict validators
    # happy.
    assert "note" not in captured["body"]
    assert "signature" not in captured["body"]
    assert "decided_at" not in captured["body"]


def test_complete_review_forwards_decided_at_and_signature(monkeypatch):
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.content.decode() or "{}")
        return httpx.Response(200, json={"id": "apr_x", "status": "approved"})

    c = _make_client(monkeypatch)
    c._client._transport = httpx.MockTransport(handler)
    try:
        c.complete_review(
            review_id="apr_x",
            decision="approve",
            reviewer_role="attending_physician",
            reviewer_id="dr.smith",
            signature="webauthn:opaque",
            decided_at="2026-05-26T12:00:00+00:00",
        )
    finally:
        c.close()

    assert captured["body"]["signature"] == "webauthn:opaque"
    assert captured["body"]["decided_at"] == "2026-05-26T12:00:00+00:00"


def test_complete_review_403_role_mismatch_raises_branded(monkeypatch):
    """The httpx wrapper maps ``reviewer_credentials_insufficient`` → branded class."""
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "code": "reviewer_credentials_insufficient",
                "review_id": "apr_x",
                "reviewer_role": "medical_student",
                "required_role": "attending_physician",
                "detail": "role insufficient",
            },
        )

    c = _make_client(monkeypatch)
    c._client._transport = httpx.MockTransport(handler)
    try:
        with pytest.raises(ReviewerCredentialsInsufficient) as ei:
            c.complete_review(
                review_id="apr_x",
                decision="approve",
                reviewer_role="medical_student",
                reviewer_id="trainee",
            )
        err = ei.value
        assert err.review_id == "apr_x"
        assert err.required_role == "attending_physician"
    finally:
        c.close()
