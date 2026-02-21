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
    assert raw_key.startswith("al_live_")
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
