"""Tests for /v1/dashboard/s3-export-* (Phase 3 Wave 3D.3).

Mirrors the JWT-fixture pattern from ``test_dashboard_api_keys.py`` so we
exercise the real ``require_clerk_role`` dependency end-to-end.

Coverage:
- GET /v1/dashboard/s3-export-config — admin + developer; returns
  current ARN + counts + recent exports + probe gate flag.
- PUT /v1/dashboard/s3-export-arn — admin-only; persists after syntax
  validation; rejects malformed ARN with the flat-error envelope.
- DELETE /v1/dashboard/s3-export-arn — admin-only; clears the column.
- POST /v1/dashboard/s3-export-arn/validate — admin-only; pure
  validation; never persists, never contacts AWS.
- POST /v1/dashboard/s3-export-arn/probe — admin-only; respects the
  ACTIONLEDGER_S3_TRUST_PROBE_ENABLED env-var gate.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import Any

import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select

from app.config import settings
from app.models import (
    ChainState,
    Checkpoint,
    CheckpointExport,
    Organization,
    OrgMembership,
)
from app.services import auth as auth_service


def _make_checkpoint(org_id: str, seq: int) -> Checkpoint:
    """Build a minimally-valid Checkpoint row.

    The recent-exports query joins on checkpoint_id via FK, so each
    CheckpointExport row needs a matching Checkpoint row. We don't
    actually exercise the chain/signature logic in this suite, so the
    payload fields are short placeholder strings.
    """
    return Checkpoint(
        id=f"cp-fixture-{seq}",
        org_id=org_id,
        sequence_at_checkpoint=seq,
        hash_at_checkpoint=f"hash{seq}",
        signature=f"sig{seq}",
    )


_TEST_ISSUER = "https://test-clerk.example.com"
_TEST_KID = "dash-s3-kid-1"


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

    async def _fake_fetch(_url: str) -> dict:
        return {"keys": [keypair["jwk"]]}

    monkeypatch.setattr(auth_service, "_fetch_jwks", _fake_fetch)
    from app.main import app

    # Clear the rate-limit middleware in-memory store so this file's
    # request volume doesn't trip the per-IP burst limit when run
    # alongside other suites.
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


def _sign(priv, *, sub: str, org_id: str, expires_in: int = 300) -> str:
    iat = int(time.time())
    claims = {
        "sub": sub,
        "iss": _TEST_ISSUER,
        "iat": iat,
        "exp": iat + expires_in,
        "org_id": org_id,
    }
    return jwt.encode(claims, priv, algorithm="RS256", headers={"kid": _TEST_KID})


@pytest_asyncio.fixture
async def clerk_org(db_session):
    org = Organization(
        name="s3-mirror-test-org", clerk_org_id="org_clerk_s3"
    )
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))
    admin = OrgMembership(
        org_id=org.id,
        clerk_user_id="user_admin_s3",
        clerk_org_id="org_clerk_s3",
        role="admin",
    )
    dev = OrgMembership(
        org_id=org.id,
        clerk_user_id="user_dev_s3",
        clerk_org_id="org_clerk_s3",
        role="developer",
    )
    db_session.add_all([admin, dev])
    await db_session.commit()
    await db_session.refresh(org)
    return {
        "org": org,
        "clerk_org_id": "org_clerk_s3",
        "admin_user_id": "user_admin_s3",
        "dev_user_id": "user_dev_s3",
    }


def _admin_token(keypair, clerk_org) -> str:
    return _sign(
        keypair["priv"],
        sub=clerk_org["admin_user_id"],
        org_id=clerk_org["clerk_org_id"],
    )


def _dev_token(keypair, clerk_org) -> str:
    return _sign(
        keypair["priv"],
        sub=clerk_org["dev_user_id"],
        org_id=clerk_org["clerk_org_id"],
    )


# ── GET /s3-export-config ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_config_get_empty(async_client, keypair, clerk_org):
    token = _admin_token(keypair, clerk_org)
    resp = await async_client.get(
        "/v1/dashboard/s3-export-config",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["arn"] is None
    assert body["success_total"] == 0
    assert body["failure_total"] == 0
    assert body["skipped_total"] == 0
    assert body["pending_total"] == 0
    assert body["recent_exports"] == []
    assert body["last_success_at"] is None
    assert body["last_failure_at"] is None
    # Probe gate defaults to OFF in tests — the conftest scrub keeps the
    # env var unset, and the stub-mode response should reflect that.
    assert body["probe_enabled"] is False
    # IAM role gate defaults to off in v1.
    assert body["iam_role_supported"] is False


@pytest.mark.asyncio
async def test_config_get_as_developer_works(async_client, keypair, clerk_org):
    """Developers can READ the config (debugging the SDK integration)
    but can't mutate. Matches the dashboard_api_keys.py read tier."""
    token = _dev_token(keypair, clerk_org)
    resp = await async_client.get(
        "/v1/dashboard/s3-export-config",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_config_get_unauthenticated_401(async_client):
    resp = await async_client.get("/v1/dashboard/s3-export-config")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_config_get_with_exports_rolls_up(
    async_client, keypair, clerk_org, db_session
):
    """Populate checkpoint_exports with success/failure/skipped rows;
    confirm the response surfaces counts + last-success/failure + the
    most recent 10 rows in DESC order by exported_at."""
    org_id = clerk_org["org"].id
    base = datetime(2026, 5, 1, 4, 0, 0)

    # Seed the parent checkpoint rows the FK requires.
    checkpoints = [_make_checkpoint(org_id, n) for n in (1, 2, 3, 4)]
    db_session.add_all(checkpoints)
    await db_session.flush()

    # Mix of statuses; exported_at strictly increasing so we can assert
    # ordering deterministically.
    rows = [
        CheckpointExport(
            checkpoint_id=checkpoints[0].id,
            org_id=org_id,
            status="success",
            duration_ms=120,
            record_count=42,
            exported_at=base,
        ),
        CheckpointExport(
            checkpoint_id=checkpoints[1].id,
            org_id=org_id,
            status="failure",
            reason="access_denied",
            error_detail="boto3: AccessDenied",
            duration_ms=80,
            exported_at=base + timedelta(hours=1),
        ),
        CheckpointExport(
            checkpoint_id=checkpoints[2].id,
            org_id=org_id,
            status="skipped",
            reason="bucket_not_configured",
            exported_at=base + timedelta(hours=2),
        ),
        CheckpointExport(
            checkpoint_id=checkpoints[3].id,
            org_id=org_id,
            status="success",
            duration_ms=95,
            record_count=17,
            exported_at=base + timedelta(hours=3),
        ),
    ]
    db_session.add_all(rows)
    await db_session.commit()

    token = _admin_token(keypair, clerk_org)
    resp = await async_client.get(
        "/v1/dashboard/s3-export-config",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success_total"] == 2
    assert body["failure_total"] == 1
    assert body["skipped_total"] == 1
    assert body["pending_total"] == 0
    # last_success is the most recent SUCCESS row, not the most recent
    # row overall.
    assert body["last_success_at"] is not None
    assert body["last_success_at"].startswith("2026-05-01T07:")
    assert body["last_failure_at"] is not None
    assert body["last_failure_reason"] == "access_denied"
    # Recent exports in DESC order — most recent first.
    statuses = [r["status"] for r in body["recent_exports"]]
    assert statuses == ["success", "skipped", "failure", "success"]


# ── PUT /s3-export-arn ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_arn_as_admin_persists(
    async_client, keypair, clerk_org, db_session
):
    token = _admin_token(keypair, clerk_org)
    resp = await async_client.put(
        "/v1/dashboard/s3-export-arn",
        json={"arn": "arn:aws:s3:::vera-mirror-customer-x/checkpoints"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["arn"] == "arn:aws:s3:::vera-mirror-customer-x/checkpoints"

    # Persisted on the row.
    org = (
        await db_session.execute(
            select(Organization).where(
                Organization.id == clerk_org["org"].id
            )
        )
    ).scalar_one()
    await db_session.refresh(org)
    assert org.s3_export_arn == (
        "arn:aws:s3:::vera-mirror-customer-x/checkpoints"
    )


@pytest.mark.asyncio
async def test_put_arn_as_developer_returns_403(
    async_client, keypair, clerk_org
):
    token = _dev_token(keypair, clerk_org)
    resp = await async_client.put(
        "/v1/dashboard/s3-export-arn",
        json={"arn": "arn:aws:s3:::valid"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_put_arn_rejects_malformed_with_flat_envelope(
    async_client, keypair, clerk_org
):
    """Server-side validation runs before persistence; failure surfaces
    as a 400 with the flat-error envelope ({code, message, hint?} at
    top level — NOT nested under detail)."""
    token = _admin_token(keypair, clerk_org)
    resp = await async_client.put(
        "/v1/dashboard/s3-export-arn",
        json={"arn": "not-a-real-arn"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "s3_arn_malformed"
    assert "message" in body
    assert "hint" in body
    # No nested detail wrapping the structured payload.
    assert not isinstance(body.get("detail"), dict)


@pytest.mark.asyncio
async def test_put_arn_idempotent(async_client, keypair, clerk_org, db_session):
    token = _admin_token(keypair, clerk_org)
    arn = "arn:aws:s3:::idempotent-bucket"
    first = await async_client.put(
        "/v1/dashboard/s3-export-arn",
        json={"arn": arn},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 200
    second = await async_client.put(
        "/v1/dashboard/s3-export-arn",
        json={"arn": arn},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 200
    assert second.json()["arn"] == arn


# ── DELETE /s3-export-arn ────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_arn_clears_column(
    async_client, keypair, clerk_org, db_session
):
    token = _admin_token(keypair, clerk_org)
    # Set it first.
    await async_client.put(
        "/v1/dashboard/s3-export-arn",
        json={"arn": "arn:aws:s3:::to-be-cleared"},
        headers={"Authorization": f"Bearer {token}"},
    )
    # Clear it.
    resp = await async_client.delete(
        "/v1/dashboard/s3-export-arn",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["arn"] is None

    org = (
        await db_session.execute(
            select(Organization).where(
                Organization.id == clerk_org["org"].id
            )
        )
    ).scalar_one()
    await db_session.refresh(org)
    assert org.s3_export_arn is None


@pytest.mark.asyncio
async def test_delete_arn_as_developer_returns_403(
    async_client, keypair, clerk_org
):
    token = _dev_token(keypair, clerk_org)
    resp = await async_client.delete(
        "/v1/dashboard/s3-export-arn",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ── POST /s3-export-arn/validate ─────────────────────────────────


@pytest.mark.asyncio
async def test_validate_accepts_valid_arn(async_client, keypair, clerk_org):
    token = _admin_token(keypair, clerk_org)
    resp = await async_client.post(
        "/v1/dashboard/s3-export-arn/validate",
        json={"arn": "arn:aws:s3:::valid-bucket"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    # Pure validation always surfaces stub=True — the probe is the
    # surface that flips this when the env-var gate is live.
    assert body["stub"] is True


@pytest.mark.asyncio
async def test_validate_accepts_valid_arn_with_role(
    async_client, keypair, clerk_org
):
    token = _admin_token(keypair, clerk_org)
    resp = await async_client.post(
        "/v1/dashboard/s3-export-arn/validate",
        json={
            "arn": "arn:aws:s3:::valid-bucket",
            "role_arn": "arn:aws:iam::123456789012:role/VeraMirror",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_validate_rejects_malformed(async_client, keypair, clerk_org):
    token = _admin_token(keypair, clerk_org)
    resp = await async_client.post(
        "/v1/dashboard/s3-export-arn/validate",
        json={"arn": "INVALID_UPPERCASE"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "code" in body
    # No nested {"detail": {...}}.
    assert not isinstance(body.get("detail"), dict)


@pytest.mark.asyncio
async def test_validate_rejects_malformed_role(
    async_client, keypair, clerk_org
):
    token = _admin_token(keypair, clerk_org)
    resp = await async_client.post(
        "/v1/dashboard/s3-export-arn/validate",
        json={
            "arn": "arn:aws:s3:::valid",
            "role_arn": "arn:aws:iam::not-12-digits:role/X",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "role_arn_malformed"


@pytest.mark.asyncio
async def test_validate_as_developer_returns_403(
    async_client, keypair, clerk_org
):
    token = _dev_token(keypair, clerk_org)
    resp = await async_client.post(
        "/v1/dashboard/s3-export-arn/validate",
        json={"arn": "arn:aws:s3:::valid"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ── POST /s3-export-arn/probe ────────────────────────────────────


@pytest.mark.asyncio
async def test_probe_stub_mode_returns_ok_with_stub_true(
    async_client, keypair, clerk_org, monkeypatch
):
    """Probe gate OFF — the underlying probe_s3_trust returns stub=True,
    and the route mirrors that to the client so the dashboard can
    render the 'syntax validated only' badge."""
    monkeypatch.delenv("ACTIONLEDGER_S3_TRUST_PROBE_ENABLED", raising=False)
    token = _admin_token(keypair, clerk_org)
    resp = await async_client.post(
        "/v1/dashboard/s3-export-arn/probe",
        json={"arn": "arn:aws:s3:::probe-bucket"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["stub"] is True


@pytest.mark.asyncio
async def test_probe_with_gate_enabled_surfaces_unimplemented(
    async_client, keypair, clerk_org, monkeypatch
):
    """When ACTIONLEDGER_S3_TRUST_PROBE_ENABLED=1 the underlying probe
    returns ok=False (boto3 path is a placeholder until ops wires real
    credentials). The route maps that to a 400 with the structured
    s3_trust_invalid envelope."""
    monkeypatch.setenv("ACTIONLEDGER_S3_TRUST_PROBE_ENABLED", "1")
    token = _admin_token(keypair, clerk_org)
    resp = await async_client.post(
        "/v1/dashboard/s3-export-arn/probe",
        json={"arn": "arn:aws:s3:::probe-bucket"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "s3_trust_invalid"
    assert "AWS reported" in body["hint"]


@pytest.mark.asyncio
async def test_probe_rejects_malformed_arn_before_calling_aws(
    async_client, keypair, clerk_org
):
    """Syntax validation runs before the probe call so a malformed ARN
    returns the structured ARN error, not a generic probe failure."""
    token = _admin_token(keypair, clerk_org)
    resp = await async_client.post(
        "/v1/dashboard/s3-export-arn/probe",
        json={"arn": "bad"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "s3_arn_malformed"


@pytest.mark.asyncio
async def test_probe_as_developer_returns_403(
    async_client, keypair, clerk_org
):
    token = _dev_token(keypair, clerk_org)
    resp = await async_client.post(
        "/v1/dashboard/s3-export-arn/probe",
        json={"arn": "arn:aws:s3:::probe-bucket"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_config_probe_enabled_flag_tracks_env(
    async_client, keypair, clerk_org, monkeypatch
):
    """probe_enabled in the config response mirrors the env-var gate;
    flipping the env at runtime is reflected on the next request."""
    monkeypatch.setenv("ACTIONLEDGER_S3_TRUST_PROBE_ENABLED", "1")
    token = _admin_token(keypair, clerk_org)
    resp = await async_client.get(
        "/v1/dashboard/s3-export-config",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["probe_enabled"] is True
