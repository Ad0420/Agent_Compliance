"""Tests for S3 ARN validation at onboarding (Wave 3A.d).

Covers:
- ``validate_s3_arn_syntax`` — pure regex check, no AWS call
- ``validate_iam_role_arn_syntax`` — companion IAM role validator
- ``POST /v1/organizations/me/off-vera-mirror/validate`` — flat-error
  envelope shape (PR #201 pattern), auth gating, syntax acceptance and
  rejection paths

The endpoint must return ``200 {ok, can_put, can_get, stub}`` on success
and ``400 {code, message, hint?}`` (flat envelope) on syntax failure.
"""

from __future__ import annotations

import pytest

from app.services.external_store import (
    S3ArnValidationError,
    validate_iam_role_arn_syntax,
    validate_s3_arn_syntax,
)


# ── validate_s3_arn_syntax — pure unit tests ───────────────────────


def test_validate_s3_arn_accepts_plain_bucket() -> None:
    # No raise — plain bucket ARN is the canonical happy path.
    validate_s3_arn_syntax("arn:aws:s3:::valid-bucket")


def test_validate_s3_arn_accepts_bucket_with_prefix() -> None:
    validate_s3_arn_syntax("arn:aws:s3:::valid-bucket/checkpoints/2026")


def test_validate_s3_arn_accepts_bucket_with_periods() -> None:
    # Periods are legal in bucket names per AWS rules (though they
    # affect SSL — we accept syntactically and let the customer choose).
    validate_s3_arn_syntax("arn:aws:s3:::my.vera.mirror")


def test_validate_s3_arn_rejects_empty_string() -> None:
    with pytest.raises(S3ArnValidationError) as exc_info:
        validate_s3_arn_syntax("")
    assert exc_info.value.code == "empty"
    assert exc_info.value.hint is not None


def test_validate_s3_arn_rejects_whitespace_only() -> None:
    with pytest.raises(S3ArnValidationError) as exc_info:
        validate_s3_arn_syntax("   ")
    assert exc_info.value.code == "empty"


def test_validate_s3_arn_rejects_non_arn_string() -> None:
    with pytest.raises(S3ArnValidationError) as exc_info:
        validate_s3_arn_syntax("not-an-arn")
    assert exc_info.value.code == "s3_arn_malformed"


def test_validate_s3_arn_rejects_uppercase_bucket() -> None:
    with pytest.raises(S3ArnValidationError) as exc_info:
        validate_s3_arn_syntax("arn:aws:s3:::INVALID_UPPERCASE")
    assert exc_info.value.code == "bucket_name_invalid"


def test_validate_s3_arn_rejects_wrong_service() -> None:
    with pytest.raises(S3ArnValidationError) as exc_info:
        validate_s3_arn_syntax("arn:aws:dynamodb:::wrong-service")
    assert exc_info.value.code == "wrong_service"


def test_validate_s3_arn_rejects_bucket_too_short() -> None:
    # S3 minimum is 3 characters.
    with pytest.raises(S3ArnValidationError) as exc_info:
        validate_s3_arn_syntax("arn:aws:s3:::bu")
    assert exc_info.value.code == "bucket_name_invalid"


def test_validate_s3_arn_rejects_bucket_too_long() -> None:
    # S3 max is 63 characters; 64 must fail.
    long_bucket = "x" * 64
    with pytest.raises(S3ArnValidationError) as exc_info:
        validate_s3_arn_syntax(f"arn:aws:s3:::{long_bucket}")
    assert exc_info.value.code == "bucket_name_invalid"


def test_validate_s3_arn_rejects_bucket_with_consecutive_periods() -> None:
    with pytest.raises(S3ArnValidationError) as exc_info:
        validate_s3_arn_syntax("arn:aws:s3:::my..bucket")
    assert exc_info.value.code == "bucket_name_invalid"


def test_validate_s3_arn_rejects_non_aws_partition() -> None:
    with pytest.raises(S3ArnValidationError) as exc_info:
        validate_s3_arn_syntax("arn:aws-us-gov:s3:::gov-bucket")
    assert exc_info.value.code == "s3_arn_malformed"


def test_validate_s3_arn_rejects_populated_region() -> None:
    # S3 bucket ARNs must have empty region + account fields.
    with pytest.raises(S3ArnValidationError) as exc_info:
        validate_s3_arn_syntax("arn:aws:s3:us-east-1::valid-bucket")
    assert exc_info.value.code == "s3_arn_malformed"


# ── validate_iam_role_arn_syntax ───────────────────────────────────


def test_validate_iam_role_arn_accepts_valid_role() -> None:
    validate_iam_role_arn_syntax("arn:aws:iam::123456789012:role/VeraMirror")


def test_validate_iam_role_arn_rejects_empty() -> None:
    with pytest.raises(S3ArnValidationError) as exc_info:
        validate_iam_role_arn_syntax("")
    assert exc_info.value.code == "role_arn_empty"


def test_validate_iam_role_arn_rejects_malformed() -> None:
    with pytest.raises(S3ArnValidationError) as exc_info:
        validate_iam_role_arn_syntax("arn:aws:iam::abc:role/Whatever")
    assert exc_info.value.code == "role_arn_malformed"


def test_validate_iam_role_arn_rejects_s3_arn_passed_by_mistake() -> None:
    with pytest.raises(S3ArnValidationError) as exc_info:
        validate_iam_role_arn_syntax("arn:aws:s3:::my-bucket")
    assert exc_info.value.code == "role_arn_malformed"


# ── POST /v1/organizations/me/off-vera-mirror/validate ─────────────


@pytest.mark.asyncio
async def test_off_vera_mirror_validate_accepts_valid_arn(
    async_client, org_and_key
):
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/organizations/me/off-vera-mirror/validate",
        json={"arn": "arn:aws:s3:::valid-mirror-bucket"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["can_put"] is True
    assert body["can_get"] is True
    # Stub mode is the default v1 deployment posture; the frontend
    # renders the "syntax validated only" badge off this flag.
    assert body["stub"] is True


@pytest.mark.asyncio
async def test_off_vera_mirror_validate_accepts_valid_arn_with_role(
    async_client, org_and_key
):
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/organizations/me/off-vera-mirror/validate",
        json={
            "arn": "arn:aws:s3:::valid-mirror-bucket/checkpoints",
            "role_arn": "arn:aws:iam::123456789012:role/VeraMirror",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_off_vera_mirror_validate_rejects_malformed_arn(
    async_client, org_and_key
):
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/organizations/me/off-vera-mirror/validate",
        json={"arn": "not-an-arn"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    # Flat error envelope (PR #201 pattern): code/message/hint at TOP
    # level, NOT nested under {"detail": {...}}.
    assert body["code"] == "s3_arn_malformed"
    assert "message" in body
    assert "hint" in body
    # The flat shape must NOT carry a nested ``detail`` dict — that's
    # the legacy/FastAPI-default wrapping the handler explicitly undoes.
    assert not isinstance(body.get("detail"), dict)


@pytest.mark.asyncio
async def test_off_vera_mirror_validate_rejects_empty_arn(
    async_client, org_and_key
):
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/organizations/me/off-vera-mirror/validate",
        json={"arn": ""},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "empty"


@pytest.mark.asyncio
async def test_off_vera_mirror_validate_rejects_wrong_service(
    async_client, org_and_key
):
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/organizations/me/off-vera-mirror/validate",
        json={"arn": "arn:aws:dynamodb:::table"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "wrong_service"


@pytest.mark.asyncio
async def test_off_vera_mirror_validate_rejects_malformed_role_arn(
    async_client, org_and_key
):
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/organizations/me/off-vera-mirror/validate",
        json={
            "arn": "arn:aws:s3:::valid-bucket",
            "role_arn": "arn:aws:iam::not-12-digits:role/Whatever",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "role_arn_malformed"


@pytest.mark.asyncio
async def test_off_vera_mirror_validate_requires_auth(async_client):
    # No Authorization header — must 401/403 before any validation runs.
    resp = await async_client.post(
        "/v1/organizations/me/off-vera-mirror/validate",
        json={"arn": "arn:aws:s3:::valid-bucket"},
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_off_vera_mirror_validate_rejects_non_admin_key(
    async_client, db_session
):
    """Read-only keys must not be able to validate mirror config — the
    mirror touches compliance posture so it's admin-only, same as BAA
    and alert-email writes."""
    from app.models import ChainState, Organization
    from app.services.auth import generate_api_key

    org = Organization(name="readonly-org")
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))
    await db_session.commit()
    await db_session.refresh(org)

    raw_key, _ = await generate_api_key(
        db_session, org.id, "read-only-key", ["read"]
    )

    resp = await async_client.post(
        "/v1/organizations/me/off-vera-mirror/validate",
        json={"arn": "arn:aws:s3:::valid-bucket"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_off_vera_mirror_validate_flat_error_envelope_shape(
    async_client, org_and_key
):
    """The 400 response must match PR #201's flat-error envelope: the
    top-level body has ``code`` + ``message`` + optional ``hint`` —
    NOT a nested ``{"detail": {"code": ...}}``."""
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/organizations/me/off-vera-mirror/validate",
        json={"arn": "arn:aws:s3:::INVALID_UPPERCASE"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert set(body.keys()) <= {"code", "message", "hint", "detail"}
    assert "code" in body
    assert "message" in body
    # No nested {"detail": {...}} — that's the legacy shape.
    assert not isinstance(body.get("detail"), dict)
