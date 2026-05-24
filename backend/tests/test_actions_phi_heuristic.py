"""Integration tests for the PHI-shape heuristic on POST /v1/actions.

Phase 1 PR 5 (Stream C item C3). Covers:

* Live-key path — every pattern family reject with 422 +
  ``code='phi_shape_in_tenant_id'`` and never echo the value.
* Test-key path — same families warn + emit ``phi_shape_warning``
  webhook event, request still succeeds with 200.
* PHI-safety on the event payload — the value itself never appears,
  only ``tenant_id_length`` + ``pattern_name``.
* Idempotency choice (once-per-action documented in PR description).
* Clerk humans behave like test keys (warn + event, no reject).
* Batch endpoint mirrors the single-record path.

These tests work alongside the bridge-guard regression tests in
``test_actions_tenant_validation.py`` (which exercise the live-key
reject path with the original 5 bridge-guard families).
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select

from app.config import settings
from app.models import (
    APIKey,
    BAAAgreement,
    BAAScope,
    ChainState,
    Customer,
    Organization,
    OrgMembership,
    WebhookSubscription,
)
from app.services import auth as auth_service
from app.services import baa as baa_service


HEADERS = lambda raw: {"Authorization": f"Bearer {raw}"}


# Representative tenant_id per family — the full coverage of pattern
# matching itself lives in test_phi_detector.py. These integration tests
# only need one example per family to confirm wire-up.
#
# Note on the ``email`` family: emails contain ``@`` + ``.`` which the
# ``tenant_id`` format regex (``^[a-zA-Z0-9_-]{1,64}$``) rejects with a
# 422 BEFORE the PHI detector runs. So email is provably unreachable
# via the action route — the detector still owns it (covered in
# ``test_phi_detector.py``) so a future surface that bypasses the
# format regex (e.g. a hypothetical free-form ``data_subject_id``
# heuristic) stays safe.
_PHI_BY_FAMILY = [
    ("ssn", "ssn_123-45-6789"),
    ("date_ymd", "patient_19720314"),
    ("date_mdy", "patient_03-14-1972"),
    ("name_pair", "John_Doe"),
    ("address", "1234_Maple_Lane"),
    ("phone", "phone_555-867-5309"),
    ("mrn", "MRN1234567"),
    ("high_entropy", "Js5g8Lpq2bN9"),
]


# ── Fixtures: live + test API keys with subscription on phi_shape_warning ──


def _now_naive_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _seed_active_baa(db_session, org_id: str) -> None:
    """Live keys need an active BAA to clear the PR 4 / C2 gate."""
    now = _now_naive_utc()
    customer = Customer(org_id=org_id, tenant_id="baa_seed_holder")
    db_session.add(customer)
    await db_session.flush()
    baa = BAAAgreement(
        org_id=org_id,
        customer_id=customer.id,
        status="active",
        effective_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=365),
    )
    db_session.add(baa)
    await db_session.flush()
    db_session.add(
        BAAScope(
            baa_agreement_id=baa.id,
            covered_services=["chart_entry"],
            covered_agent_types=["scribe"],
            granted_at=now,
        )
    )
    await db_session.commit()


@pytest_asyncio.fixture
async def org_live(db_session):
    """Org with active BAA + live-kind API key."""
    baa_service._reset_baa_freshness_cache_for_tests()
    org = Organization(name="phi-int-live")
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))
    await db_session.commit()
    await db_session.refresh(org)

    await _seed_active_baa(db_session, org.id)

    raw_key, api_key = await auth_service.generate_api_key(
        db_session,
        org.id,
        "phi-int-live-bearer",
        ["read", "write"],
        kind="live",
    )
    yield {"org": org, "raw_key": raw_key, "api_key": api_key}
    baa_service._reset_baa_freshness_cache_for_tests()


@pytest_asyncio.fixture
async def warning_sub(db_session, org_and_key):
    """Subscribe ``org_and_key``'s org to ``phi_shape_warning``."""
    org, _, _ = org_and_key
    sub = WebhookSubscription(
        org_id=org.id,
        url="https://hooks.example.com/phi-warn",
        secret="phi-secret",
        event_types=["phi_shape_warning"],
        is_active=True,
    )
    db_session.add(sub)
    await db_session.commit()
    return sub


def _ok_mock_client():
    response = MagicMock()
    response.status_code = 200
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=response)
    return client


async def _flush_tasks():
    """Drain ``asyncio.create_task`` work — mirror of test_webhooks.py."""
    for _ in range(100):
        pending = [
            t
            for t in asyncio.all_tasks()
            if t is not asyncio.current_task() and not t.done()
        ]
        if not pending:
            return
        await asyncio.wait(
            pending, timeout=0.05, return_when=asyncio.FIRST_COMPLETED
        )


def _phi_warning_envelopes(mock_client) -> list[dict]:
    """Extract the phi_shape_warning envelopes from the captured POSTs."""
    out: list[dict] = []
    for call in mock_client.post.await_args_list:
        body = call.kwargs.get("content")
        if not body:
            continue
        env = json.loads(body.decode("utf-8"))
        if env.get("event_type") == "phi_shape_warning":
            out.append(env)
    return out


# ── Live-key rejection: every family produces 422 ────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("family,phi_tenant_id", _PHI_BY_FAMILY)
async def test_live_key_rejects_each_phi_family(
    async_client, org_live, family, phi_tenant_id
):
    """Every pattern family that matches in the detector unit tests must
    also produce a 422 + ``phi_shape_in_tenant_id`` on the live-key
    integration path."""
    resp = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "x",
            "agent_name": "scribe",
            "result": "success",
            "tenant_id": phi_tenant_id,
        },
        headers=HEADERS(org_live["raw_key"]),
    )
    assert resp.status_code == 422, (
        f"family={family} value={phi_tenant_id}: {resp.text}"
    )
    body = resp.json()
    assert body.get("code") == "phi_shape_in_tenant_id", body
    # PHI safety: the value MUST NOT appear in the error body anywhere.
    rendered = json.dumps(body)
    assert phi_tenant_id not in rendered, (
        f"PHI value leaked into error body for family={family}: {body!r}"
    )
    # Pattern name SHOULD appear in developer_reason (diagnostic).
    assert body.get("developer_reason"), body


# ── Test-key warning: every family warns + emits, request succeeds ────────


@pytest.mark.asyncio
@pytest.mark.parametrize("family,phi_tenant_id", _PHI_BY_FAMILY)
async def test_test_key_warns_and_emits_for_each_family(
    async_client, org_and_key, warning_sub, family, phi_tenant_id
):
    """Test keys take the warn path: the action insert succeeds (200)
    AND a ``phi_shape_warning`` event is emitted to subscribed
    endpoints."""
    _, raw_key, _ = org_and_key

    mock_client = _ok_mock_client()
    with patch(
        "app.services.webhooks.httpx.AsyncClient", return_value=mock_client
    ):
        resp = await async_client.post(
            "/v1/actions",
            json={
                "action_name": "x",
                "agent_name": "scribe",
                "result": "success",
                "tenant_id": phi_tenant_id,
            },
            headers=HEADERS(raw_key),
        )
        await _flush_tasks()

    assert resp.status_code == 200, (
        f"family={family} value={phi_tenant_id}: {resp.text}"
    )
    envs = _phi_warning_envelopes(mock_client)
    assert len(envs) == 1, (
        f"family={family} expected one phi_shape_warning, got {envs!r}"
    )
    payload = envs[0]["data"]
    assert payload["pattern_name"] is not None
    assert payload["severity"] in {"high", "medium", "low"}
    assert payload["tenant_id_length"] == len(phi_tenant_id)


# ── Payload PHI-safety: value is NEVER in the event ──────────────────────


@pytest.mark.asyncio
async def test_phi_warning_payload_omits_tenant_id_value(
    async_client, org_and_key, warning_sub
):
    """The whole point of the warning event: it MUST carry length +
    pattern only. The value is exactly the data we flagged — echoing
    it back would make the heuristic pointless."""
    org, raw_key, _ = org_and_key
    phi_value = "patient_19720314_clinic"

    mock_client = _ok_mock_client()
    with patch(
        "app.services.webhooks.httpx.AsyncClient", return_value=mock_client
    ):
        resp = await async_client.post(
            "/v1/actions",
            json={
                "action_name": "x",
                "agent_name": "scribe",
                "result": "success",
                "tenant_id": phi_value,
            },
            headers=HEADERS(raw_key),
        )
        await _flush_tasks()

    assert resp.status_code == 200, resp.text
    envs = _phi_warning_envelopes(mock_client)
    assert len(envs) == 1
    payload = envs[0]["data"]

    # Strict schema: ONLY these keys in the payload.
    assert set(payload.keys()) == {
        "event_type",
        "org_id",
        "tenant_id_length",
        "pattern_name",
        "severity",
        "detected_at",
    }
    assert payload["event_type"] == "phi_shape_warning"
    assert payload["org_id"] == org.id
    assert payload["tenant_id_length"] == len(phi_value)

    # Defensive: serialise the WHOLE envelope and confirm the value is
    # nowhere in the body (no accidental ``data.context``, log echo, etc).
    full_body = json.dumps(envs[0])
    assert phi_value not in full_body, (
        f"PHI value leaked in event body: {full_body}"
    )


# ── Idempotency: once-per-action (documented choice) ─────────────────────


@pytest.mark.asyncio
async def test_phi_warning_fires_per_action_not_per_customer(
    async_client, org_and_key, warning_sub
):
    """Documented choice: ONCE PER ACTION. A second action with the
    same PHI-shaped tenant_id emits a second event. Per-customer dedup
    would need persistent state we don't carry today (Phase 2 dashboard
    banner owns that)."""
    _, raw_key, _ = org_and_key
    phi_value = "John_Doe_19720314"

    mock_client = _ok_mock_client()
    with patch(
        "app.services.webhooks.httpx.AsyncClient", return_value=mock_client
    ):
        for _ in range(2):
            resp = await async_client.post(
                "/v1/actions",
                json={
                    "action_name": "x",
                    "agent_name": "scribe",
                    "result": "success",
                    "tenant_id": phi_value,
                },
                headers=HEADERS(raw_key),
            )
            assert resp.status_code == 200, resp.text
        await _flush_tasks()

    envs = _phi_warning_envelopes(mock_client)
    assert len(envs) == 2, f"expected two events, got {envs!r}"


# ── Opaque IDs do NOT warn ───────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "safe_value",
    [
        "acme_corp_us_east_2",
        "cleveland_clinic",
        "tenant_42",
    ],
)
async def test_opaque_tenant_id_no_warning(
    async_client, org_and_key, warning_sub, safe_value
):
    """The most important regression: pilot SDKs that send opaque
    IDs MUST NOT trigger the warning event."""
    _, raw_key, _ = org_and_key

    mock_client = _ok_mock_client()
    with patch(
        "app.services.webhooks.httpx.AsyncClient", return_value=mock_client
    ):
        resp = await async_client.post(
            "/v1/actions",
            json={
                "action_name": "x",
                "agent_name": "scribe",
                "result": "success",
                "tenant_id": safe_value,
            },
            headers=HEADERS(raw_key),
        )
        await _flush_tasks()

    assert resp.status_code == 200, resp.text
    assert _phi_warning_envelopes(mock_client) == []


# ── Batch endpoint: live rejects whole batch ─────────────────────────────


@pytest.mark.asyncio
async def test_batch_live_key_rejects_whole_batch_on_any_phi_record(
    async_client, org_live
):
    """One PHI-shaped tenant_id in a batch rejects the entire batch on
    live keys (the batch is atomic — partial acceptance would lie)."""
    resp = await async_client.post(
        "/v1/actions/batch",
        json={
            "records": [
                {
                    "action_name": "ok",
                    "agent_name": "scribe",
                    "result": "success",
                    "tenant_id": "acme_corp",
                },
                {
                    "action_name": "bad",
                    "agent_name": "scribe",
                    "result": "success",
                    "tenant_id": "patient_19720314",
                },
            ]
        },
        headers=HEADERS(org_live["raw_key"]),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json().get("code") == "phi_shape_in_tenant_id"


@pytest.mark.asyncio
async def test_batch_test_key_warns_per_phi_record(
    async_client, org_and_key, warning_sub
):
    """A batch with two PHI-shaped records on a test key emits two
    warning events AFTER the batch commits."""
    _, raw_key, _ = org_and_key

    mock_client = _ok_mock_client()
    with patch(
        "app.services.webhooks.httpx.AsyncClient", return_value=mock_client
    ):
        resp = await async_client.post(
            "/v1/actions/batch",
            json={
                "records": [
                    {
                        "action_name": "a",
                        "agent_name": "scribe",
                        "result": "success",
                        "tenant_id": "John_Doe",
                    },
                    {
                        "action_name": "b",
                        "agent_name": "scribe",
                        "result": "success",
                        "tenant_id": "acme_corp",
                    },
                    {
                        "action_name": "c",
                        "agent_name": "scribe",
                        "result": "success",
                        "tenant_id": "patient_19720314",
                    },
                ]
            },
            headers=HEADERS(raw_key),
        )
        await _flush_tasks()

    assert resp.status_code == 200, resp.text
    envs = _phi_warning_envelopes(mock_client)
    # Two PHI-shaped records → two events.
    assert len(envs) == 2, f"expected 2 events, got {envs!r}"


# ── Subscription endpoint accepts the new event type ─────────────────────


@pytest.mark.asyncio
async def test_subscription_endpoint_accepts_phi_shape_warning(
    async_client, org_and_key
):
    """``ALLOWED_EVENT_TYPES`` extension is wired through to the
    subscription POST validator without further code changes."""
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/webhooks",
        json={
            "url": "https://hooks.example.com/phi-sub",
            "event_types": ["phi_shape_warning"],
            "description": "PHI-shape warnings",
        },
        headers=HEADERS(raw_key),
    )
    assert resp.status_code == 200, resp.text
    assert "phi_shape_warning" in resp.json()["event_types"]


# ── Clerk humans behave like test keys ───────────────────────────────────

_CLERK_ISSUER = "https://phi-int-clerk.example.com"
_CLERK_KID = "phi-int-kid"


@pytest.fixture(scope="module")
def keypair():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(priv.public_key()))
    jwk.update({"kid": _CLERK_KID, "alg": "RS256", "use": "sig"})
    return {"priv": priv, "jwk": jwk}


@pytest.fixture
def _configure_clerk(monkeypatch, keypair):
    monkeypatch.setattr(settings, "clerk_jwks_url", "https://fixture/jwks.json")
    monkeypatch.setattr(settings, "clerk_issuer", _CLERK_ISSUER)
    monkeypatch.setattr(settings, "clerk_audience", None)
    auth_service._reset_jwks_cache_for_tests()

    async def _fake_fetch(_url: str) -> dict:
        return {"keys": [keypair["jwk"]]}

    monkeypatch.setattr(auth_service, "_fetch_jwks", _fake_fetch)
    yield
    auth_service._reset_jwks_cache_for_tests()


def _sign_clerk(priv, *, sub: str, org_id: str) -> str:
    iat = int(time.time())
    return jwt.encode(
        {
            "sub": sub,
            "iss": _CLERK_ISSUER,
            "iat": iat,
            "exp": iat + 300,
            "org_id": org_id,
        },
        priv,
        algorithm="RS256",
        headers={"kid": _CLERK_KID},
    )


@pytest_asyncio.fixture
async def clerk_admin_session(db_session, keypair, _configure_clerk):
    """Clerk admin user bound to a fresh backend org (NO API key)."""
    org = Organization(name="clerk-phi-org", clerk_org_id="org_clerk_phi")
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))
    db_session.add(
        OrgMembership(
            org_id=org.id,
            clerk_user_id="user_clerk_phi",
            clerk_org_id="org_clerk_phi",
            role="admin",
        )
    )
    await db_session.commit()
    await db_session.refresh(org)
    db_session.add(
        WebhookSubscription(
            org_id=org.id,
            url="https://hooks.example.com/clerk-phi",
            secret="clerk-phi-secret",
            event_types=["phi_shape_warning"],
            is_active=True,
        )
    )
    await db_session.commit()
    token = _sign_clerk(
        keypair["priv"], sub="user_clerk_phi", org_id="org_clerk_phi"
    )
    return {"org": org, "token": token}


@pytest.mark.asyncio
async def test_clerk_human_behaves_like_test_key(
    async_client, clerk_admin_session
):
    """A Clerk-authenticated human POSTing an action with a PHI-shaped
    tenant_id MUST NOT be rejected (they're not on the live tier). They
    should warn + emit, exactly like a test key.

    This matches the BAA-gate convention (Clerk humans skip the BAA
    gate) — otherwise an operator debugging a PHI contamination could
    be locked out of their own dashboard."""
    phi_value = "John_Doe_19720314"

    mock_client = _ok_mock_client()
    with patch(
        "app.services.webhooks.httpx.AsyncClient", return_value=mock_client
    ):
        resp = await async_client.post(
            "/v1/actions",
            json={
                "action_name": "x",
                "agent_name": "scribe",
                "result": "success",
                "tenant_id": phi_value,
            },
            headers=HEADERS(clerk_admin_session["token"]),
        )
        await _flush_tasks()

    assert resp.status_code == 200, resp.text
    envs = _phi_warning_envelopes(mock_client)
    assert len(envs) == 1


# ── No subscription = warn-but-no-delivery ──────────────────────────────


@pytest.mark.asyncio
async def test_phi_warning_no_subscription_no_delivery(
    async_client, org_and_key
):
    """Without a ``phi_shape_warning`` subscription, the action still
    succeeds and the server-side warning log fires, but no HTTP POST
    is made to any endpoint."""
    _, raw_key, _ = org_and_key

    mock_client = _ok_mock_client()
    with patch(
        "app.services.webhooks.httpx.AsyncClient", return_value=mock_client
    ):
        resp = await async_client.post(
            "/v1/actions",
            json={
                "action_name": "x",
                "agent_name": "scribe",
                "result": "success",
                "tenant_id": "John_Doe",
            },
            headers=HEADERS(raw_key),
        )
        await _flush_tasks()

    assert resp.status_code == 200, resp.text
    mock_client.post.assert_not_awaited()


# ── Live-key rejection leaves no DB residue ──────────────────────────────


@pytest.mark.asyncio
async def test_live_key_reject_does_not_auto_discover_customer(
    async_client, org_live, db_session
):
    """A live-key 422 must short-circuit BEFORE the chain advances —
    no Customer row, no CustomerAgent row, no ActionRecord. If we leaked
    a Customer row with ``display_name=tenant_id``, the dashboard's AI
    Coverage Matrix would surface the PHI shape we just blocked."""
    from app.models import ActionRecord, CustomerAgent

    phi_value = "John_Doe_19720314"

    resp = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "x",
            "agent_name": "scribe",
            "result": "success",
            "tenant_id": phi_value,
        },
        headers=HEADERS(org_live["raw_key"]),
    )
    assert resp.status_code == 422

    # No Customer for the PHI value.
    customer_row = (
        await db_session.execute(
            select(Customer).where(
                Customer.org_id == org_live["org"].id,
                Customer.tenant_id == phi_value,
            )
        )
    ).scalar_one_or_none()
    assert customer_row is None

    # No ActionRecord for the PHI value either.
    action_row = (
        await db_session.execute(
            select(ActionRecord).where(
                ActionRecord.org_id == org_live["org"].id,
                ActionRecord.tenant_id == phi_value,
            )
        )
    ).scalar_one_or_none()
    assert action_row is None


# ── ActionRecord is persisted on the test-key path (warning doesn't block) ──


@pytest.mark.asyncio
async def test_test_key_phi_warning_does_not_block_insert(
    async_client, org_and_key, db_session, warning_sub
):
    """The whole point of the warn-not-reject path: the action lands
    in the chain so customers can see what was captured. A PHI-shape
    warning is informational; the audit trail still wins."""
    from app.models import ActionRecord

    _, raw_key, _ = org_and_key
    phi_value = "patient_19720314"

    mock_client = _ok_mock_client()
    with patch(
        "app.services.webhooks.httpx.AsyncClient", return_value=mock_client
    ):
        resp = await async_client.post(
            "/v1/actions",
            json={
                "action_name": "x",
                "agent_name": "scribe",
                "result": "success",
                "tenant_id": phi_value,
            },
            headers=HEADERS(raw_key),
        )
        await _flush_tasks()

    assert resp.status_code == 200
    record_id = resp.json()["id"]
    stored = (
        await db_session.execute(
            select(ActionRecord).where(ActionRecord.id == record_id)
        )
    ).scalar_one()
    assert stored.tenant_id == phi_value
