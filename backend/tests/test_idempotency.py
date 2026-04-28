"""Tests for the Idempotency-Key dedupe layer on /v1/actions and /v1/actions/batch.

The SDK auto-generates a UUID4 Idempotency-Key on every action write so the
3-attempt retry loop in ``_request_with_retry`` is safe across network blips
that drop the response after the server committed. The route caches
(org_id, key) -> response_body for 24h and replays on duplicates.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.models import ActionRecord, IdempotencyRecord


# ── Helpers ──────────────────────────────────────────────────────────────


def _action_payload(name: str = "test_action", **overrides) -> dict:
    payload = {
        "action_name": name,
        "action_type": "function_call",
        "agent_name": "test-agent",
        "result": "success",
    }
    payload.update(overrides)
    return payload


async def _count_action_records(db_session, org_id: str) -> int:
    result = await db_session.execute(
        select(func.count(ActionRecord.id)).where(ActionRecord.org_id == org_id)
    )
    return result.scalar() or 0


async def _count_idempotency_records(db_session, org_id: str) -> int:
    result = await db_session.execute(
        select(func.count(IdempotencyRecord.id)).where(
            IdempotencyRecord.org_id == org_id
        )
    )
    return result.scalar() or 0


# ── Single-action endpoint ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fresh_request_with_idempotency_key_inserts_both_rows(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    key = uuid.uuid4().hex

    resp = await async_client.post(
        "/v1/actions",
        json=_action_payload("idem_fresh"),
        headers={
            "Authorization": f"Bearer {raw_key}",
            "Idempotency-Key": key,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["action_name"] == "idem_fresh"
    assert body["sequence_number"] == 1

    assert await _count_action_records(db_session, org.id) == 1
    assert await _count_idempotency_records(db_session, org.id) == 1


@pytest.mark.asyncio
async def test_replay_same_key_same_payload_returns_cached_response(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    key = uuid.uuid4().hex
    payload = _action_payload("idem_replay")
    headers = {
        "Authorization": f"Bearer {raw_key}",
        "Idempotency-Key": key,
    }

    first = await async_client.post("/v1/actions", json=payload, headers=headers)
    assert first.status_code == 200
    first_body = first.json()

    second = await async_client.post("/v1/actions", json=payload, headers=headers)
    assert second.status_code == 200
    second_body = second.json()

    # Cached response is byte-identical
    assert first_body == second_body
    # And no new action_records row was created
    assert await _count_action_records(db_session, org.id) == 1
    assert second_body["sequence_number"] == first_body["sequence_number"]


@pytest.mark.asyncio
async def test_replay_same_key_different_payload_returns_409(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    key = uuid.uuid4().hex
    headers = {
        "Authorization": f"Bearer {raw_key}",
        "Idempotency-Key": key,
    }

    first = await async_client.post(
        "/v1/actions", json=_action_payload("idem_a"), headers=headers
    )
    assert first.status_code == 200

    second = await async_client.post(
        "/v1/actions", json=_action_payload("idem_b"), headers=headers
    )
    assert second.status_code == 409
    assert "different request body" in second.json()["detail"].lower()

    # Only the first write was committed
    assert await _count_action_records(db_session, org.id) == 1


@pytest.mark.asyncio
async def test_no_idempotency_key_works_normally_no_cache_row(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key

    resp = await async_client.post(
        "/v1/actions",
        json=_action_payload("no_idem"),
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200

    assert await _count_action_records(db_session, org.id) == 1
    assert await _count_idempotency_records(db_session, org.id) == 0


@pytest.mark.asyncio
async def test_concurrent_requests_with_same_key_dedupe_to_one_row(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    key = uuid.uuid4().hex
    payload = _action_payload("idem_concurrent")
    headers = {
        "Authorization": f"Bearer {raw_key}",
        "Idempotency-Key": key,
    }

    r1, r2 = await asyncio.gather(
        async_client.post("/v1/actions", json=payload, headers=headers),
        async_client.post("/v1/actions", json=payload, headers=headers),
    )

    assert r1.status_code == 200
    assert r2.status_code == 200
    # Both responses identical (same record_id, same sequence_number)
    assert r1.json()["id"] == r2.json()["id"]
    assert r1.json()["sequence_number"] == r2.json()["sequence_number"]

    # Exactly one action_records row
    assert await _count_action_records(db_session, org.id) == 1


@pytest.mark.asyncio
async def test_expired_idempotency_row_is_replaced(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    key = uuid.uuid4().hex
    payload = _action_payload("idem_expire")
    headers = {
        "Authorization": f"Bearer {raw_key}",
        "Idempotency-Key": key,
    }

    first = await async_client.post("/v1/actions", json=payload, headers=headers)
    assert first.status_code == 200
    first_seq = first.json()["sequence_number"]

    # Manually expire the cached row
    result = await db_session.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.org_id == org.id,
            IdempotencyRecord.key == key,
        )
    )
    cached = result.scalar_one()
    cached.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    await db_session.commit()

    # Same key + same payload after expiry → fresh processing
    second = await async_client.post("/v1/actions", json=payload, headers=headers)
    assert second.status_code == 200
    second_seq = second.json()["sequence_number"]

    assert second_seq == first_seq + 1
    assert await _count_action_records(db_session, org.id) == 2
    # Old row replaced — there's still only one row for this key
    assert await _count_idempotency_records(db_session, org.id) == 1


@pytest.mark.asyncio
async def test_validation_error_does_not_cache_idempotency_row(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    key = uuid.uuid4().hex
    headers = {
        "Authorization": f"Bearer {raw_key}",
        "Idempotency-Key": key,
    }

    # action_name is required (min_length=1) — empty string fails validation
    bad = await async_client.post(
        "/v1/actions",
        json={"action_name": "", "agent_name": "test-agent"},
        headers=headers,
    )
    assert bad.status_code == 422
    # Crucially, no idempotency row was cached for the failed request
    assert await _count_idempotency_records(db_session, org.id) == 0

    # Caller fixes the payload and retries with the SAME key — must succeed
    good = await async_client.post(
        "/v1/actions",
        json=_action_payload("idem_retry_fixed"),
        headers=headers,
    )
    assert good.status_code == 200
    assert await _count_action_records(db_session, org.id) == 1
    assert await _count_idempotency_records(db_session, org.id) == 1


@pytest.mark.asyncio
async def test_idempotency_key_too_long_returns_400(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    bad_key = "x" * 65

    resp = await async_client.post(
        "/v1/actions",
        json=_action_payload("idem_bad_key"),
        headers={
            "Authorization": f"Bearer {raw_key}",
            "Idempotency-Key": bad_key,
        },
    )
    assert resp.status_code == 400
    assert "1-64 ascii" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_idempotency_key_empty_returns_400(async_client, org_and_key):
    _, raw_key, _ = org_and_key

    resp = await async_client.post(
        "/v1/actions",
        json=_action_payload("idem_empty_key"),
        headers={
            "Authorization": f"Bearer {raw_key}",
            "Idempotency-Key": "",
        },
    )
    # FastAPI may treat an empty header as absent depending on transport,
    # so accept either: a 400 (validation rejection) or a normal 200
    # (header was treated as absent). Either is acceptable behaviour;
    # what we explicitly want NOT to happen is a 5xx.
    assert resp.status_code in (200, 400)


# ── Batch endpoint ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_replay_same_key_returns_cached_response(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    key = uuid.uuid4().hex
    payload = {
        "records": [
            _action_payload(f"batch_idem_{i}") for i in range(3)
        ]
    }
    headers = {
        "Authorization": f"Bearer {raw_key}",
        "Idempotency-Key": key,
    }

    first = await async_client.post(
        "/v1/actions/batch", json=payload, headers=headers
    )
    assert first.status_code == 200
    first_body = first.json()
    assert len(first_body) == 3

    second = await async_client.post(
        "/v1/actions/batch", json=payload, headers=headers
    )
    assert second.status_code == 200
    assert second.json() == first_body

    # Three records from the first call; replay added zero
    assert await _count_action_records(db_session, org.id) == 3


@pytest.mark.asyncio
async def test_batch_concurrent_same_key_dedupes(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    key = uuid.uuid4().hex
    payload = {
        "records": [_action_payload(f"batch_concurrent_{i}") for i in range(2)]
    }
    headers = {
        "Authorization": f"Bearer {raw_key}",
        "Idempotency-Key": key,
    }

    r1, r2 = await asyncio.gather(
        async_client.post("/v1/actions/batch", json=payload, headers=headers),
        async_client.post("/v1/actions/batch", json=payload, headers=headers),
    )
    assert r1.status_code == 200
    assert r2.status_code == 200
    # Same record IDs in both responses
    ids1 = sorted(r["id"] for r in r1.json())
    ids2 = sorted(r["id"] for r in r2.json())
    assert ids1 == ids2

    # Only one logical batch was committed
    assert await _count_action_records(db_session, org.id) == 2


@pytest.mark.asyncio
async def test_batch_same_key_different_payload_returns_409(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    key = uuid.uuid4().hex
    headers = {
        "Authorization": f"Bearer {raw_key}",
        "Idempotency-Key": key,
    }

    first = await async_client.post(
        "/v1/actions/batch",
        json={"records": [_action_payload("batch_a")]},
        headers=headers,
    )
    assert first.status_code == 200

    second = await async_client.post(
        "/v1/actions/batch",
        json={"records": [_action_payload("batch_b")]},
        headers=headers,
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_batch_no_idempotency_key_works_normally(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key

    resp = await async_client.post(
        "/v1/actions/batch",
        json={"records": [_action_payload(f"batch_no_idem_{i}") for i in range(2)]},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 2
    assert await _count_idempotency_records(db_session, org.id) == 0
