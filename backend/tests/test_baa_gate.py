"""Phase 1 PR 4 — api_keys.kind create + BAA gate tests.

Exercises Stream C items C1 (create accepts ``kind``) and C2
(``require_permission`` live-key BAA freshness gate). Companion to
``test_dashboard_api_keys.py`` (legacy create/list/revoke) and
``test_api_key_kind.py`` (column-level kind tests).

Each test sets up its own Clerk JWT / BAA fixtures so failures are
localised. The shared cache state in ``services.baa`` is reset around
every test via ``_reset_baa_freshness_cache_for_tests`` so cache TTL
behaviour is observable without test-order coupling.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any

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
)
from app.services import auth as auth_service
from app.services import baa as baa_service


_TEST_ISSUER = "https://test-clerk.example.com"
_TEST_KID = "baa-gate-kid"


def _now_naive_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _pubkey_to_jwk(public_key) -> dict[str, Any]:
    return json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public_key))


@pytest.fixture(scope="module")
def keypair():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = _pubkey_to_jwk(priv.public_key())
    jwk.update({"kid": _TEST_KID, "alg": "RS256", "use": "sig"})
    return {"priv": priv, "jwk": jwk}


@pytest.fixture(autouse=True)
def _configure_clerk(monkeypatch, keypair):
    monkeypatch.setattr(settings, "clerk_jwks_url", "https://fixture/jwks.json")
    monkeypatch.setattr(settings, "clerk_issuer", _TEST_ISSUER)
    monkeypatch.setattr(settings, "clerk_audience", None)
    auth_service._reset_jwks_cache_for_tests()
    # ALWAYS reset the BAA freshness cache so tests don't leak state
    # into each other. A stale cache could mask a real regression.
    baa_service._reset_baa_freshness_cache_for_tests()

    async def _fake_fetch(_url: str) -> dict:
        return {"keys": [keypair["jwk"]]}

    monkeypatch.setattr(auth_service, "_fetch_jwks", _fake_fetch)
    # Reset the in-memory rate-limit store so tests don't trip the
    # per-IP burst limit when run after the webhook test suite.
    from app.main import app

    stack = getattr(app, "middleware_stack", None)
    visited = set()
    while stack is not None and id(stack) not in visited:
        visited.add(id(stack))
        if type(stack).__name__ == "RateLimitMiddleware":
            requests = getattr(stack, "_requests", None)
            if requests is not None:
                requests.clear()
        stack = getattr(stack, "app", None)
    yield
    auth_service._reset_jwks_cache_for_tests()
    baa_service._reset_baa_freshness_cache_for_tests()


def _sign(priv, *, sub: str, org_id: str, expires_in: int = 300) -> str:
    iat = int(time.time())
    claims = {
        "sub": sub,
        "iss": _TEST_ISSUER,
        "iat": iat,
        "exp": iat + expires_in,
        "org_id": org_id,
    }
    return jwt.encode(
        claims, priv, algorithm="RS256", headers={"kid": _TEST_KID}
    )


@pytest_asyncio.fixture
async def admin_session(db_session, keypair):
    """A Clerk-authenticated admin user bound to a fresh backend org.

    Returns a dict carrying the org row, the admin JWT, and a helper
    for seeding active/expired BAAs against the org.
    """
    from app.models import OrgMembership

    org = Organization(name="baa-gate-org", clerk_org_id="org_baa_gate")
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))
    db_session.add(
        OrgMembership(
            org_id=org.id,
            clerk_user_id="user_baa_admin",
            clerk_org_id="org_baa_gate",
            role="admin",
        )
    )
    await db_session.commit()
    await db_session.refresh(org)

    token = _sign(
        keypair["priv"], sub="user_baa_admin", org_id="org_baa_gate"
    )
    return {"org": org, "token": token}


async def _seed_active_baa(db_session, org_id: str) -> BAAAgreement:
    """Create a Customer + active BAA + at least one BAAScope.

    Mirrors the "operator uploads signed BAA" workflow (Phase 1 PR 10).
    The combination of ``status='active'``, an in-range temporal window,
    and at least one scope is the canonical "gate-passes" shape.
    """
    customer = Customer(org_id=org_id, tenant_id="ci_customer")
    db_session.add(customer)
    await db_session.flush()

    now = _now_naive_utc()
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
    await db_session.refresh(baa)
    return baa


async def _seed_expired_baa(db_session, org_id: str) -> BAAAgreement:
    customer = Customer(org_id=org_id, tenant_id="ci_customer_exp")
    db_session.add(customer)
    await db_session.flush()
    now = _now_naive_utc()
    baa = BAAAgreement(
        org_id=org_id,
        customer_id=customer.id,
        status="active",
        effective_at=now - timedelta(days=400),
        expires_at=now - timedelta(days=1),
    )
    db_session.add(baa)
    await db_session.flush()
    db_session.add(
        BAAScope(
            baa_agreement_id=baa.id,
            covered_services=["chart_entry"],
            covered_agent_types=["scribe"],
            granted_at=now - timedelta(days=400),
        )
    )
    await db_session.commit()
    await db_session.refresh(baa)
    return baa


# ── C1: create endpoint accepts kind + enforces BAA gate at mint time ────────


@pytest.mark.asyncio
async def test_create_test_key_no_baa_succeeds(async_client, admin_session):
    """Sandbox (test) keys never require a BAA — that's the whole point of
    the sandbox tier."""
    resp = await async_client.post(
        "/v1/dashboard/api-keys",
        json={"name": "sandbox-key", "permissions": ["read", "write"]},
        headers={"Authorization": f"Bearer {admin_session['token']}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "test"
    assert body["raw_key"].startswith("al_test_")


@pytest.mark.asyncio
async def test_create_test_key_explicit_kind_succeeds(
    async_client, admin_session
):
    """Explicit ``kind='test'`` behaves the same as the default."""
    resp = await async_client.post(
        "/v1/dashboard/api-keys",
        json={"name": "sandbox-explicit", "kind": "test"},
        headers={"Authorization": f"Bearer {admin_session['token']}"},
    )
    assert resp.status_code == 200
    assert resp.json()["kind"] == "test"


@pytest.mark.asyncio
async def test_create_live_key_no_baa_rejected_with_baa_required_code(
    async_client, admin_session
):
    """The mint endpoint MUST reject ``kind='live'`` without an active BAA
    AND emit the structured ``baa_required`` code so SDK PR #194's
    error mapping fires automatically."""
    resp = await async_client.post(
        "/v1/dashboard/api-keys",
        json={"name": "prod-attempt", "kind": "live"},
        headers={"Authorization": f"Bearer {admin_session['token']}"},
    )
    assert resp.status_code == 403, resp.text
    body = resp.json()
    # The flat-envelope handler lifts dict-typed HTTPException.detail to the
    # top level so the SDK's body.get("code") dispatch sees the structured
    # code without unwrapping a "detail" layer.
    assert body.get("code") == "baa_required", f"expected flat envelope, got {body!r}"
    assert body.get("fix_url") == "/customers"


@pytest.mark.asyncio
async def test_create_live_key_active_baa_succeeds(
    async_client, admin_session, db_session
):
    """With an active BAA in place, the same call now succeeds and the
    response surfaces ``kind='live'`` so the dashboard can render the
    tier badge."""
    await _seed_active_baa(db_session, admin_session["org"].id)
    resp = await async_client.post(
        "/v1/dashboard/api-keys",
        json={"name": "prod-allowed", "kind": "live"},
        headers={"Authorization": f"Bearer {admin_session['token']}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "live"
    assert body["raw_key"].startswith("al_live_")


@pytest.mark.asyncio
async def test_create_live_key_invalid_kind_rejected_at_schema(
    async_client, admin_session
):
    """A typo like ``kind='production'`` returns 422 from the Pydantic
    schema before the BAA gate ever runs."""
    resp = await async_client.post(
        "/v1/dashboard/api-keys",
        json={"name": "typo", "kind": "production"},
        headers={"Authorization": f"Bearer {admin_session['token']}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_live_key_baa_with_no_scope_rejected(
    async_client, admin_session, db_session
):
    """An ``active`` BAA without any BAAScope rows does NOT count —
    Phase 2 gates won't be able to enforce anything, so the create
    endpoint refuses to mint a key that would be functionally useless."""
    # Active BAA but NO BAAScope. Per services.baa.is_org_baa_active we
    # require BOTH conditions.
    customer = Customer(org_id=admin_session["org"].id, tenant_id="no_scope")
    db_session.add(customer)
    await db_session.flush()
    db_session.add(
        BAAAgreement(
            org_id=admin_session["org"].id,
            customer_id=customer.id,
            status="active",
            effective_at=_now_naive_utc() - timedelta(days=1),
            expires_at=_now_naive_utc() + timedelta(days=365),
        )
    )
    await db_session.commit()

    resp = await async_client.post(
        "/v1/dashboard/api-keys",
        json={"name": "scopeless", "kind": "live"},
        headers={"Authorization": f"Bearer {admin_session['token']}"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "baa_required"


# ── C2: live-key per-request gate in require_permission ──────────────────────


@pytest_asyncio.fixture
async def org_with_live_key(db_session):
    """An org + an active live API key, no BAA. The live key exists because
    the BAA was revoked AFTER the key was minted — exactly the scenario
    C2's per-request gate is designed to catch."""
    org = Organization(name="live-key-org")
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))
    await db_session.commit()
    await db_session.refresh(org)

    raw_key, api_key = await auth_service.generate_api_key(
        db_session, org.id, "live-bearer", ["read", "write"], kind="live"
    )
    return {"org": org, "raw_key": raw_key, "api_key": api_key}


@pytest.mark.asyncio
async def test_live_key_no_baa_rejected_at_request_time(
    async_client, org_with_live_key
):
    """The live-key path through ``require_permission`` MUST reject with
    ``code='baa_expired'`` when no active BAA covers the org. SDK PR #194
    maps that code → ``PolicyBlock`` defensively."""
    # Hit any endpoint that goes through require_permission("read").
    resp = await async_client.get(
        "/v1/organizations/me",
        headers={"Authorization": f"Bearer {org_with_live_key['raw_key']}"},
    )
    assert resp.status_code == 403, resp.text
    body = resp.json()
    # Flat envelope (see backend/app/main.py::_flatten_dict_detail).
    assert body.get("code") == "baa_expired", f"expected flat envelope, got {body!r}"
    assert body.get("fix_url") == "/customers"


@pytest.mark.asyncio
async def test_live_key_active_baa_allowed(
    async_client, org_with_live_key, db_session
):
    """With an active BAA in place, the same live key now passes the gate."""
    await _seed_active_baa(db_session, org_with_live_key["org"].id)
    resp = await async_client.get(
        "/v1/organizations/me",
        headers={"Authorization": f"Bearer {org_with_live_key['raw_key']}"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_live_key_expired_baa_rejected(
    async_client, org_with_live_key, db_session
):
    """A BAA whose ``expires_at`` is in the past does NOT count as active,
    even with ``status='active'`` — the temporal window is the source of
    truth for freshness."""
    await _seed_expired_baa(db_session, org_with_live_key["org"].id)
    resp = await async_client.get(
        "/v1/organizations/me",
        headers={"Authorization": f"Bearer {org_with_live_key['raw_key']}"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "baa_expired"


@pytest.mark.asyncio
async def test_live_key_terminated_baa_rejected(
    async_client, org_with_live_key, db_session
):
    """A BAA whose status was flipped to ``terminated`` is no longer active
    even if the temporal window is still valid."""
    customer = Customer(
        org_id=org_with_live_key["org"].id, tenant_id="terminated_baa"
    )
    db_session.add(customer)
    await db_session.flush()
    now = _now_naive_utc()
    db_session.add(
        BAAAgreement(
            org_id=org_with_live_key["org"].id,
            customer_id=customer.id,
            status="terminated",
            effective_at=now - timedelta(days=30),
            expires_at=now + timedelta(days=30),
        )
    )
    await db_session.commit()

    resp = await async_client.get(
        "/v1/organizations/me",
        headers={"Authorization": f"Bearer {org_with_live_key['raw_key']}"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "baa_expired"


@pytest.mark.asyncio
async def test_test_key_no_baa_always_allowed(async_client, db_session):
    """Sandbox keys NEVER hit the BAA gate — that's the design contract."""
    org = Organization(name="test-key-org")
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))
    await db_session.commit()
    await db_session.refresh(org)

    raw_key, _ = await auth_service.generate_api_key(
        db_session, org.id, "sandbox-bearer", ["read"], kind="test"
    )
    resp = await async_client.get(
        "/v1/organizations/me",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_clerk_session_skips_baa_gate(async_client, admin_session):
    """Clerk humans browsing the dashboard MUST NOT hit the BAA gate —
    otherwise an operator could never sign in to upload the BAA that
    unblocks their own org."""
    # admin_session's org has NO BAA. A Clerk-bearer call to a route
    # using require_permission("read") should still succeed.
    resp = await async_client.get(
        "/v1/organizations/me",
        headers={"Authorization": f"Bearer {admin_session['token']}"},
    )
    assert resp.status_code == 200, resp.text


# ── BAA freshness cache TTL ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_baa_cache_hits_within_ttl(
    async_client, org_with_live_key, db_session, monkeypatch
):
    """Two back-to-back calls with the same live key should produce
    exactly ONE BAA DB query — the first populates the cache, the
    second hits it. Anything else means the cache isn't doing its job
    and we'd be hammering the DB on the hot path."""
    await _seed_active_baa(db_session, org_with_live_key["org"].id)

    call_count = {"n": 0}

    real_query = baa_service._query_active_baa

    async def _counted_query(session, *, org_id, now):
        call_count["n"] += 1
        return await real_query(session, org_id=org_id, now=now)

    monkeypatch.setattr(baa_service, "_query_active_baa", _counted_query)
    baa_service._reset_baa_freshness_cache_for_tests()

    # Two requests in quick succession.
    for _ in range(2):
        resp = await async_client.get(
            "/v1/organizations/me",
            headers={"Authorization": f"Bearer {org_with_live_key['raw_key']}"},
        )
        assert resp.status_code == 200, resp.text

    # Second call should have hit the cache, so exactly 1 DB query.
    assert call_count["n"] == 1, (
        f"expected cache hit on 2nd call, saw {call_count['n']} DB queries"
    )


@pytest.mark.asyncio
async def test_baa_cache_refreshes_after_ttl(
    org_with_live_key, db_session, monkeypatch
):
    """After the TTL elapses, the next call MUST re-query the DB. We
    drive the monotonic clock directly rather than sleep to keep the
    test fast."""
    await _seed_active_baa(db_session, org_with_live_key["org"].id)

    call_count = {"n": 0}

    real_query = baa_service._query_active_baa

    async def _counted_query(session, *, org_id, now):
        call_count["n"] += 1
        return await real_query(session, org_id=org_id, now=now)

    monkeypatch.setattr(baa_service, "_query_active_baa", _counted_query)
    baa_service._reset_baa_freshness_cache_for_tests()

    # Drive time forward in two phases. Start at t=0.
    now = [1000.0]
    monkeypatch.setattr(baa_service.time, "monotonic", lambda: now[0])

    # First call — populates cache.
    assert await baa_service.is_org_baa_active(
        db_session, org_with_live_key["org"].id
    )
    assert call_count["n"] == 1

    # Advance < TTL — should hit cache.
    now[0] += 30.0
    assert await baa_service.is_org_baa_active(
        db_session, org_with_live_key["org"].id
    )
    assert call_count["n"] == 1

    # Advance > TTL — should re-query DB.
    now[0] += 60.0
    assert await baa_service.is_org_baa_active(
        db_session, org_with_live_key["org"].id
    )
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_baa_cache_ttl_boundary_is_strict_less_than(
    org_with_live_key, db_session, monkeypatch
):
    """Pin down the exact TTL boundary semantics.

    ``services.baa.is_org_baa_active`` uses ``(time.monotonic() - cached_at)
    < _CACHE_TTL_SECONDS`` — strict less-than. So at the boundary:

    * ``elapsed = TTL - epsilon`` → cache HIT  (no DB query)
    * ``elapsed = TTL``           → cache MISS (DB re-query)

    This guards against a future refactor that flips ``<`` to ``<=`` (which
    would silently lengthen the staleness budget by one cache slot) or
    reads TTL from an int that drops the fractional epsilon.
    """
    await _seed_active_baa(db_session, org_with_live_key["org"].id)

    call_count = {"n": 0}
    real_query = baa_service._query_active_baa

    async def _counted_query(session, *, org_id, now):
        call_count["n"] += 1
        return await real_query(session, org_id=org_id, now=now)

    monkeypatch.setattr(baa_service, "_query_active_baa", _counted_query)
    baa_service._reset_baa_freshness_cache_for_tests()

    now = [1000.0]
    monkeypatch.setattr(baa_service.time, "monotonic", lambda: now[0])
    ttl = baa_service._CACHE_TTL_SECONDS  # 60.0 today; read live so the test
                                          # follows future TTL changes.

    org_id = org_with_live_key["org"].id

    # Populate cache.
    assert await baa_service.is_org_baa_active(db_session, org_id)
    assert call_count["n"] == 1

    # Just-under TTL (strict-less-than → hit).
    now[0] += ttl - 0.001
    assert await baa_service.is_org_baa_active(db_session, org_id)
    assert call_count["n"] == 1, (
        "expected cache hit just under TTL boundary"
    )

    # Exactly at TTL (strict-less-than → miss; re-query DB).
    now[0] = 1000.0 + ttl
    assert await baa_service.is_org_baa_active(db_session, org_id)
    assert call_count["n"] == 2, (
        "expected cache miss exactly at TTL boundary (< is strict)"
    )


@pytest.mark.asyncio
async def test_baa_cache_bypass_forces_db(
    org_with_live_key, db_session, monkeypatch
):
    """The create-key endpoint passes ``bypass_cache=True`` so a freshly
    uploaded BAA is visible immediately. Verify the bypass argument
    actually hits the DB even on a warm cache."""
    await _seed_active_baa(db_session, org_with_live_key["org"].id)

    call_count = {"n": 0}

    real_query = baa_service._query_active_baa

    async def _counted_query(session, *, org_id, now):
        call_count["n"] += 1
        return await real_query(session, org_id=org_id, now=now)

    monkeypatch.setattr(baa_service, "_query_active_baa", _counted_query)
    baa_service._reset_baa_freshness_cache_for_tests()

    org_id = org_with_live_key["org"].id
    await baa_service.is_org_baa_active(db_session, org_id)  # cache populate
    await baa_service.is_org_baa_active(db_session, org_id, bypass_cache=True)
    await baa_service.is_org_baa_active(db_session, org_id, bypass_cache=True)
    assert call_count["n"] == 3


# ── /v1/organizations/me/baa-status endpoint ─────────────────────────────────


@pytest.mark.asyncio
async def test_baa_status_endpoint_no_baa(async_client, admin_session):
    """The dialog endpoint returns ``active=false`` when no BAA is on file."""
    resp = await async_client.get(
        "/v1/organizations/me/baa-status",
        headers={"Authorization": f"Bearer {admin_session['token']}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["active"] is False
    assert body["fix_url"] == "/customers"


@pytest.mark.asyncio
async def test_baa_status_endpoint_active_baa(
    async_client, admin_session, db_session
):
    await _seed_active_baa(db_session, admin_session["org"].id)
    resp = await async_client.get(
        "/v1/organizations/me/baa-status",
        headers={"Authorization": f"Bearer {admin_session['token']}"},
    )
    assert resp.status_code == 200
    assert resp.json()["active"] is True


# ── PHI-safety on error response ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_baa_required_response_does_not_leak_phi(
    async_client, admin_session, db_session
):
    """A 403 from the gate path must NOT echo BAA document_uri or any
    customer-identifying field. Two leak vectors to cover:
    1. The 403 detail body (most obvious)
    2. The X-Request-ID is fine to include but no other BAA fields"""
    # Seed an active BAA with a document URI that contains a recognisable
    # canary string. If our 403 paths ever surface the document_uri we'd
    # see "PHI-LEAK-CANARY" in the response.
    customer = Customer(
        org_id=admin_session["org"].id,
        tenant_id="phi_test",
        contact_email="phi-leak-canary@example.com",
        contact_name="PHI Leak Canary",
    )
    db_session.add(customer)
    await db_session.flush()
    now = _now_naive_utc()
    # Make it EXPIRED so the live-key path rejects it.
    baa = BAAAgreement(
        org_id=admin_session["org"].id,
        customer_id=customer.id,
        status="active",
        effective_at=now - timedelta(days=400),
        expires_at=now - timedelta(days=1),
        document_uri="s3://baa-bucket/PHI-LEAK-CANARY.pdf",
    )
    db_session.add(baa)
    await db_session.flush()
    db_session.add(
        BAAScope(
            baa_agreement_id=baa.id,
            covered_services=["chart_entry"],
            covered_agent_types=["scribe"],
            granted_at=now - timedelta(days=400),
        )
    )
    await db_session.commit()

    # Try a live-key create — should 403 with baa_required.
    resp = await async_client.post(
        "/v1/dashboard/api-keys",
        json={"name": "phi-check", "kind": "live"},
        headers={"Authorization": f"Bearer {admin_session['token']}"},
    )
    assert resp.status_code == 403
    rendered = json.dumps(resp.json())
    assert "PHI-LEAK-CANARY" not in rendered
    assert "phi-leak-canary@example.com" not in rendered
    assert "PHI Leak Canary" not in rendered


# ── SDK error-mapping activation (end-to-end) ────────────────────────────────


@pytest.mark.asyncio
async def test_live_key_baa_gate_403_maps_to_sdk_policy_block(
    async_client, org_with_live_key
):
    """End-to-end: the backend 403 envelope MUST trigger SDK ``PolicyBlock``.

    PR #194 wired ``baa_required`` / ``baa_expired`` → ``PolicyBlock``
    defensively in ``vera.errors.CODE_TO_ERROR_CLASS``. PR #201 makes that
    mapping fire by emitting the structured payload from the backend. This
    test closes the loop: synthesise an httpx ``HTTPStatusError`` from the
    real 403 response and assert ``vera.client.wrap_httpx_error`` returns
    ``PolicyBlock`` (NOT ``VeraAuthError``).

    Without the flat-envelope handler in ``backend/app/main.py``, the body
    arrived as ``{"detail": {"code": "baa_expired", ...}}`` and the SDK's
    top-level ``body.get("code")`` lookup missed — the 403 fell through to
    the status-class mapping and produced ``VeraAuthError``. The headline
    value of this PR (activating the SDK's defensive mapping) was a no-op.
    """
    import httpx

    from vera.client import wrap_httpx_error
    from vera.errors import PolicyBlock, VeraAuthError

    resp = await async_client.get(
        "/v1/organizations/me",
        headers={"Authorization": f"Bearer {org_with_live_key['raw_key']}"},
    )
    assert resp.status_code == 403, resp.text
    body = resp.json()
    # Confirm the on-the-wire shape is flat — top-level ``code`` is the
    # contract the SDK reads.
    assert body.get("code") == "baa_expired", body

    # Build an httpx.HTTPStatusError carrying the real response so
    # wrap_httpx_error sees the same shape the SDK would in production.
    http_resp = httpx.Response(
        status_code=resp.status_code,
        content=resp.content,
        headers={"content-type": "application/json"},
        request=httpx.Request("GET", "http://test/v1/organizations/me"),
    )
    status_err = httpx.HTTPStatusError(
        "403 from gate", request=http_resp.request, response=http_resp
    )

    wrapped = wrap_httpx_error(status_err)
    assert isinstance(wrapped, PolicyBlock), (
        f"expected PolicyBlock from flat envelope, got {type(wrapped).__name__}"
    )
    # Regression guard: must NOT degrade to the generic 401/403 fallback.
    assert not isinstance(wrapped, VeraAuthError)
    assert wrapped.status_code == 403


# ── kind appears in list response ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_keys_surfaces_kind_for_both_tiers(
    async_client, admin_session, db_session
):
    """The list endpoint must surface ``kind`` so the dashboard can render
    distinct visual badges for sandbox and production keys."""
    await _seed_active_baa(db_session, admin_session["org"].id)
    # Mint one of each.
    await async_client.post(
        "/v1/dashboard/api-keys",
        json={"name": "the-sandbox", "kind": "test"},
        headers={"Authorization": f"Bearer {admin_session['token']}"},
    )
    await async_client.post(
        "/v1/dashboard/api-keys",
        json={"name": "the-production", "kind": "live"},
        headers={"Authorization": f"Bearer {admin_session['token']}"},
    )
    resp = await async_client.get(
        "/v1/dashboard/api-keys",
        headers={"Authorization": f"Bearer {admin_session['token']}"},
    )
    assert resp.status_code == 200
    kinds_by_name = {k["name"]: k["kind"] for k in resp.json()}
    assert kinds_by_name["the-sandbox"] == "test"
    assert kinds_by_name["the-production"] == "live"
