"""Integration tests for authentication and authorization."""

import pytest
import pytest_asyncio
from datetime import datetime, timezone

from app.services.auth import generate_api_key, authenticate_request, _hash_key


@pytest.mark.asyncio
async def test_key_generation_produces_valid_hash(db_session, org_and_key):
    org, _, _ = org_and_key
    raw_key, api_key = await generate_api_key(
        db_session, org.id, "test-key", ["read"]
    )
    # Default-kind keys land in the sandbox tier (Phase 1 PR 4): the raw
    # bearer surface visibly signals tier so a leaked key is identifiable
    # from the first 8 chars.
    assert raw_key.startswith("al_test_")
    assert api_key.kind == "test"
    assert api_key.key_hash == _hash_key(raw_key)
    assert api_key.key_prefix == raw_key[:12]


@pytest.mark.asyncio
async def test_authentication_succeeds_with_correct_key(db_session, org_and_key):
    org, raw_key, _ = org_and_key
    result = await authenticate_request(db_session, raw_key)
    assert result is not None
    assert result.org_id == org.id


@pytest.mark.asyncio
async def test_authentication_fails_with_wrong_key(db_session, org_and_key):
    result = await authenticate_request(db_session, "al_live_invalid_key_here")
    assert result is None


@pytest.mark.asyncio
async def test_revoked_key_is_rejected(db_session, org_and_key):
    org, _, _ = org_and_key
    raw_key, api_key = await generate_api_key(
        db_session, org.id, "revocable-key", ["read", "write"]
    )

    # Verify it works first
    result = await authenticate_request(db_session, raw_key)
    assert result is not None

    # Revoke it
    api_key.revoked_at = datetime.now(timezone.utc)
    await db_session.commit()

    # Should now be rejected
    result = await authenticate_request(db_session, raw_key)
    assert result is None


@pytest.mark.asyncio
async def test_permission_checking(db_session, org_and_key):
    org, _, _ = org_and_key

    # Create read-only key
    raw_key, api_key = await generate_api_key(
        db_session, org.id, "read-only-key", ["read"]
    )
    assert "read" in api_key.permissions
    assert "write" not in api_key.permissions
    assert "admin" not in api_key.permissions

    # Create full admin key
    raw_key2, api_key2 = await generate_api_key(
        db_session, org.id, "admin-key", ["read", "write", "admin"]
    )
    assert "admin" in api_key2.permissions


# ── HTTPBearer401: missing/malformed Authorization → 401 (not 403) ──────────
#
# Phase 4 acceptance Scenario 7 surfaced FastAPI's default ``HTTPBearer``
# raising HTTP 403 when no Authorization header is presented. That's
# semantically wrong (401 = no credentials, 403 = forbidden-after-auth).
# ``HTTPBearer401`` in ``app/services/auth.py`` overrides the default
# and adds ``WWW-Authenticate: Bearer`` per RFC 6750 §3. These tests
# pin that contract.


_RANDOM_AUDIT_UUID = "11111111-2222-3333-4444-555555555555"
_AUDIT_BODY = {
    "date_from": "2026-05-01",
    "date_to": "2026-05-27",
    "sections": ["cover"],
    "branding": "customer",
}


@pytest.mark.asyncio
async def test_missing_authorization_header_returns_401(async_client):
    """No Authorization header → 401 + WWW-Authenticate: Bearer."""
    resp = await async_client.post(
        f"/v1/audits/{_RANDOM_AUDIT_UUID}",
        json=_AUDIT_BODY,
    )
    assert resp.status_code == 401, resp.text
    assert resp.json() == {"detail": "Not authenticated"}
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


@pytest.mark.asyncio
async def test_malformed_authorization_header_returns_401(async_client):
    """Authorization with a non-Bearer scheme → 401 (was 403 with the
    stock ``HTTPBearer``). The override flips the status code; the
    detail body stays whatever FastAPI's HTTPBearer produces (currently
    ``{"detail": "Invalid authentication credentials"}``)."""
    resp = await async_client.post(
        f"/v1/audits/{_RANDOM_AUDIT_UUID}",
        headers={"Authorization": "NotBearer xyz"},
        json=_AUDIT_BODY,
    )
    assert resp.status_code == 401, resp.text
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


@pytest.mark.asyncio
async def test_invalid_bearer_token_returns_401(async_client):
    """Authorization: Bearer <garbage> still resolves to 401 via the
    application-layer credential check (``require_permission``). This
    path runs AFTER ``HTTPBearer401`` extracts the credential, so the
    override shouldn't have changed behaviour — pin it as a regression
    guard so we notice if the detail message ever shifts."""
    resp = await async_client.post(
        f"/v1/audits/{_RANDOM_AUDIT_UUID}",
        headers={"Authorization": "Bearer al_test_garbage_does_not_resolve"},
        json=_AUDIT_BODY,
    )
    assert resp.status_code == 401, resp.text
    body = resp.json()
    # The legacy API-key branch returns this detail; Clerk-JWT branch
    # would return "Invalid or expired session". The token above starts
    # with ``al_`` so we hit the API-key branch.
    assert body.get("detail") == "Invalid or revoked API key"
