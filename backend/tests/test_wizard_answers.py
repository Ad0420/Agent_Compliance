"""Tests for the 5-question onboarding wizard (Phase 1 PR 14, Stream F item F5).

Covers:
  - GET returns null/null for an org that has never opened the wizard.
  - POST partial save persists across GET round-trip.
  - POST completed=true with all fields stamps ``wizard_completed_at``.
  - POST completed=true with missing fields → 400 wizard_incomplete.
  - Idempotency: re-submitting completed=true does NOT bump
    ``wizard_completed_at`` after the first completion.
  - Multi-tenancy: org A cannot read/write org B's wizard answers.
  - ``extra="forbid"`` rejects pollution of the answer blob.
  - Validation: jurisdictions must include ``us_federal``; unknown
    tokens rejected; invalid email rejected; ``agent_type=other``
    without ``agent_type_other`` rejected on completion.
  - Auth: a ``read`` key cannot POST; ``admin`` key can.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.models import APIKey, ChainState, Organization
from app.services.auth import generate_api_key


# ── Fixtures ───────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def second_org_and_key(db_session):
    """A separate org + admin key so we can prove cross-org isolation."""
    org = Organization(name="second-org")
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))
    await db_session.commit()
    await db_session.refresh(org)
    raw_key, api_key = await generate_api_key(
        db_session, org.id, "second-admin", ["read", "write", "admin"]
    )
    return org, raw_key, api_key


@pytest_asyncio.fixture
async def read_only_key(db_session, org_and_key):
    """A read-only key on the same org so we can test the admin gate."""
    org, _, _ = org_and_key
    raw_key, api_key = await generate_api_key(
        db_session, org.id, "read-only", ["read"]
    )
    return raw_key, api_key


def _complete_payload() -> dict:
    return {
        "answers": {
            "agent_type": "scribe",
            "jurisdictions": ["us_federal", "us_ca"],
            "decision_volume": "10k_100k",
            "channel": "in_app_webhook",
            "privacy_officer": {
                "name": "Dr. Jane Doe",
                "email": "jane@example.org",
            },
        },
        "completed": True,
    }


# ── GET ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_returns_null_when_never_opened(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.get(
        "/v1/organizations/me/wizard-answers",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"answers": None, "completed_at": None}


# ── POST: partial + completed flows ───────────────────────────────


@pytest.mark.asyncio
async def test_partial_save_round_trips(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    headers = {"Authorization": f"Bearer {raw_key}"}

    # Save only Q1 + Q2.
    resp = await async_client.post(
        "/v1/organizations/me/wizard-answers",
        headers=headers,
        json={
            "answers": {
                "agent_type": "receptionist",
                "jurisdictions": ["us_federal"],
            },
            "completed": False,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["completed_at"] is None
    assert body["answers"]["agent_type"] == "receptionist"
    assert body["answers"]["jurisdictions"] == ["us_federal"]
    assert body["answers"]["channel"] is None

    # GET shows the same partial state.
    get_resp = await async_client.get(
        "/v1/organizations/me/wizard-answers", headers=headers
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["completed_at"] is None
    assert get_resp.json()["answers"]["agent_type"] == "receptionist"


@pytest.mark.asyncio
async def test_completed_stamps_timestamp(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    headers = {"Authorization": f"Bearer {raw_key}"}

    resp = await async_client.post(
        "/v1/organizations/me/wizard-answers",
        headers=headers,
        json=_complete_payload(),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["completed_at"] is not None
    assert body["answers"]["agent_type"] == "scribe"
    assert body["answers"]["privacy_officer"]["email"] == "jane@example.org"


@pytest.mark.asyncio
async def test_completed_missing_fields_400(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    headers = {"Authorization": f"Bearer {raw_key}"}

    resp = await async_client.post(
        "/v1/organizations/me/wizard-answers",
        headers=headers,
        json={
            "answers": {
                "agent_type": "scribe",
                "jurisdictions": ["us_federal"],
            },
            "completed": True,
        },
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    # The structured-error handler in main.py flattens dict-typed detail
    # to the top level, so ``code`` lives at the root.
    assert body.get("code") == "wizard_incomplete"
    missing = body.get("missing_fields", [])
    assert "decision_volume" in missing
    assert "channel" in missing
    assert "privacy_officer" in missing


@pytest.mark.asyncio
async def test_completed_other_requires_other_text(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    headers = {"Authorization": f"Bearer {raw_key}"}

    payload = _complete_payload()
    payload["answers"]["agent_type"] = "other"
    # No agent_type_other provided.
    resp = await async_client.post(
        "/v1/organizations/me/wizard-answers", headers=headers, json=payload
    )
    assert resp.status_code == 400
    assert "agent_type_other" in resp.json().get("missing_fields", [])

    # Adding the supplement makes it valid.
    payload["answers"]["agent_type_other"] = "AI clinical-trial recruiter"
    resp = await async_client.post(
        "/v1/organizations/me/wizard-answers", headers=headers, json=payload
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_idempotent_completion_does_not_bump_timestamp(
    async_client, org_and_key
):
    _, raw_key, _ = org_and_key
    headers = {"Authorization": f"Bearer {raw_key}"}

    first = await async_client.post(
        "/v1/organizations/me/wizard-answers",
        headers=headers,
        json=_complete_payload(),
    )
    assert first.status_code == 200
    first_ts = first.json()["completed_at"]
    assert first_ts is not None

    # Resubmit with a small edit — completed_at should NOT advance.
    payload = _complete_payload()
    payload["answers"]["privacy_officer"]["name"] = "Dr. Jane Doe-Smith"
    second = await async_client.post(
        "/v1/organizations/me/wizard-answers", headers=headers, json=payload
    )
    assert second.status_code == 200
    second_ts = second.json()["completed_at"]
    assert second_ts == first_ts, "completed_at must not bump on re-submit"
    assert second.json()["answers"]["privacy_officer"]["name"] == "Dr. Jane Doe-Smith"


# ── Validation ────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "jurisdictions,expect_field",
    [
        ([], "jurisdictions"),  # empty list rejected
        (["us_ca"], "us_federal"),  # missing us_federal
        (["us_federal", "ZZZ"], "unknown jurisdiction"),  # unknown token
    ],
)
async def test_jurisdiction_validation(
    async_client, org_and_key, jurisdictions, expect_field
):
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/organizations/me/wizard-answers",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"answers": {"jurisdictions": jurisdictions}, "completed": False},
    )
    assert resp.status_code == 422
    assert expect_field in resp.text


@pytest.mark.asyncio
async def test_email_validation(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/organizations/me/wizard-answers",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={
            "answers": {
                "privacy_officer": {"name": "Jane", "email": "not-an-email"},
            },
            "completed": False,
        },
    )
    assert resp.status_code == 422
    assert "@" in resp.text


@pytest.mark.asyncio
async def test_extra_fields_forbidden(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/organizations/me/wizard-answers",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={
            "answers": {"agent_type": "scribe", "secret_admin_flag": True},
            "completed": False,
        },
    )
    assert resp.status_code == 422
    assert "secret_admin_flag" in resp.text or "extra" in resp.text.lower()


# ── Multi-tenancy + RBAC ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_org_isolation(
    async_client, org_and_key, second_org_and_key
):
    _, raw_key_a, _ = org_and_key
    _, raw_key_b, _ = second_org_and_key

    # Org A submits.
    submit = await async_client.post(
        "/v1/organizations/me/wizard-answers",
        headers={"Authorization": f"Bearer {raw_key_a}"},
        json=_complete_payload(),
    )
    assert submit.status_code == 200

    # Org B GETs and sees nothing — proves the row is scoped by auth, not body.
    get_b = await async_client.get(
        "/v1/organizations/me/wizard-answers",
        headers={"Authorization": f"Bearer {raw_key_b}"},
    )
    assert get_b.status_code == 200
    assert get_b.json() == {"answers": None, "completed_at": None}


@pytest.mark.asyncio
async def test_read_key_cannot_write(async_client, org_and_key, read_only_key):
    raw_read_key, _ = read_only_key

    # GET works for read.
    resp = await async_client.get(
        "/v1/organizations/me/wizard-answers",
        headers={"Authorization": f"Bearer {raw_read_key}"},
    )
    assert resp.status_code == 200

    # POST does not.
    write = await async_client.post(
        "/v1/organizations/me/wizard-answers",
        headers={"Authorization": f"Bearer {raw_read_key}"},
        json={"answers": {"agent_type": "scribe"}, "completed": False},
    )
    assert write.status_code == 403
