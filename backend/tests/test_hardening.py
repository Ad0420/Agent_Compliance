"""Hardening tests — immutability, concurrency, isolation, tampering, edge cases."""

import asyncio
from datetime import datetime, timezone, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, text, update, delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base, Organization, ChainState, ActionRecord
from app.models.checkpoint import Checkpoint
from app.schemas.action import ActionRecordCreate
from app.services.auth import generate_api_key
from app.services.chain import build_and_insert_record, build_and_insert_batch
from app.services.checkpoint import create_checkpoint, verify_checkpoint
from app.services.hashing import verify_record_hash
from app.services.immutability import install_sqlite_triggers
from app.services.verification import verify_chain


def _make_action(**kwargs) -> ActionRecordCreate:
    defaults = {
        "action_name": "test_action",
        "action_type": "function_call",
        "agent_name": "test-agent",
        "result": "success",
    }
    defaults.update(kwargs)
    return ActionRecordCreate(**defaults)


# ── Database-level immutability tests ─────────────────────


@pytest.mark.asyncio
async def test_update_action_record_blocked_by_trigger(db_engine):
    """UPDATE on action_records must be rejected by the DB trigger."""
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )

    # Setup org + record
    async with session_factory() as session:
        org = Organization(name="immutability-update-test")
        session.add(org)
        await session.flush()
        cs = ChainState(org_id=org.id)
        session.add(cs)
        await session.commit()
        org_id = org.id

    async with session_factory() as session:
        record = await build_and_insert_record(
            session, org_id, _make_action(action_name="immutable_record")
        )
        record_id = record.id

    # Attempt raw SQL UPDATE — must fail
    async with session_factory() as session:
        with pytest.raises(Exception, match="immutable"):
            await session.execute(
                text("UPDATE action_records SET action_name = 'tampered' WHERE id = :id"),
                {"id": record_id},
            )
            await session.commit()


@pytest.mark.asyncio
async def test_delete_action_record_blocked_by_trigger(db_engine):
    """DELETE on action_records must be rejected by the DB trigger."""
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        org = Organization(name="immutability-delete-test")
        session.add(org)
        await session.flush()
        cs = ChainState(org_id=org.id)
        session.add(cs)
        await session.commit()
        org_id = org.id

    async with session_factory() as session:
        record = await build_and_insert_record(
            session, org_id, _make_action(action_name="undeletable_record")
        )
        record_id = record.id

    # Attempt raw SQL DELETE — must fail
    async with session_factory() as session:
        with pytest.raises(Exception, match="immutable"):
            await session.execute(
                text("DELETE FROM action_records WHERE id = :id"),
                {"id": record_id},
            )
            await session.commit()


@pytest.mark.asyncio
async def test_chain_state_cannot_decrease(db_engine):
    """chain_state.latest_sequence must not decrease (monotonic trigger)."""
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        org = Organization(name="monotonic-test")
        session.add(org)
        await session.flush()
        cs = ChainState(org_id=org.id)
        session.add(cs)
        await session.commit()
        org_id = org.id

    # Insert a record so sequence goes to 1
    async with session_factory() as session:
        await build_and_insert_record(
            session, org_id, _make_action(action_name="seq_test")
        )

    # Try to set sequence back to 0 — must fail
    async with session_factory() as session:
        with pytest.raises(Exception, match="monotonically increasing"):
            await session.execute(
                text("UPDATE chain_state SET latest_sequence = 0 WHERE org_id = :oid"),
                {"oid": org_id},
            )
            await session.commit()


# ── Tamper detection tests ────────────────────────────────


@pytest.mark.asyncio
async def test_verification_detects_tampered_record_content(db_engine):
    """If a record's data is modified (bypassing triggers), verification must detect it."""
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )

    # Setup
    async with session_factory() as session:
        org = Organization(name="tamper-detect-test")
        session.add(org)
        await session.flush()
        cs = ChainState(org_id=org.id)
        session.add(cs)
        await session.commit()
        org_id = org.id

    # Insert 5 records
    async with session_factory() as session:
        for i in range(5):
            await build_and_insert_record(
                session, org_id, _make_action(action_name=f"record_{i}")
            )

    # Verify chain is valid first
    async with session_factory() as session:
        result = await verify_chain(session, org_id)
        assert result.is_valid is True
        assert result.records_checked == 5

    # Now tamper: drop trigger, modify record #3, re-add trigger
    async with db_engine.begin() as conn:
        await conn.execute(text("DROP TRIGGER IF EXISTS no_update_action_records"))
        await conn.execute(
            text(
                "UPDATE action_records SET action_name = 'TAMPERED' "
                "WHERE org_id = :oid AND sequence_number = 3"
            ),
            {"oid": org_id},
        )
        # Re-install trigger
        await conn.run_sync(install_sqlite_triggers)

    # Verification must now FAIL at sequence 3
    async with session_factory() as session:
        result = await verify_chain(session, org_id)
        assert result.is_valid is False
        assert result.first_invalid_sequence == 3
        assert "hash mismatch" in result.message.lower() or "3" in result.message


@pytest.mark.asyncio
async def test_verification_detects_broken_chain_link(db_engine):
    """If a record's previous_hash is modified, chain verification must detect it."""
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        org = Organization(name="chain-link-tamper-test")
        session.add(org)
        await session.flush()
        cs = ChainState(org_id=org.id)
        session.add(cs)
        await session.commit()
        org_id = org.id

    async with session_factory() as session:
        for i in range(3):
            await build_and_insert_record(
                session, org_id, _make_action(action_name=f"link_{i}")
            )

    # Tamper: change previous_hash on record #2 to break the chain
    async with db_engine.begin() as conn:
        await conn.execute(text("DROP TRIGGER IF EXISTS no_update_action_records"))
        await conn.execute(
            text(
                "UPDATE action_records SET previous_hash = 'FAKE_HASH' "
                "WHERE org_id = :oid AND sequence_number = 2"
            ),
            {"oid": org_id},
        )
        await conn.run_sync(install_sqlite_triggers)

    async with session_factory() as session:
        result = await verify_chain(session, org_id)
        assert result.is_valid is False
        assert result.first_invalid_sequence == 2


@pytest.mark.asyncio
async def test_single_record_verification_detects_tamper(db_engine):
    """verify_record_hash must return False for a tampered record."""
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        org = Organization(name="single-tamper-test")
        session.add(org)
        await session.flush()
        cs = ChainState(org_id=org.id)
        session.add(cs)
        await session.commit()
        org_id = org.id

    async with session_factory() as session:
        record = await build_and_insert_record(
            session, org_id, _make_action(action_name="will_be_tampered")
        )
        record_id = record.id

    # Tamper via raw SQL
    async with db_engine.begin() as conn:
        await conn.execute(text("DROP TRIGGER IF EXISTS no_update_action_records"))
        await conn.execute(
            text("UPDATE action_records SET result = 'failure' WHERE id = :id"),
            {"id": record_id},
        )
        await conn.run_sync(install_sqlite_triggers)

    # Reload and verify
    async with session_factory() as session:
        result = await session.execute(
            select(ActionRecord).where(ActionRecord.id == record_id)
        )
        tampered_record = result.scalar_one()
        assert verify_record_hash(tampered_record) is False


# ── Concurrent insertion tests ─────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_inserts_produce_sequential_sequences(db_engine):
    """Multiple concurrent inserts for the same org must produce gap-free sequences."""
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        org = Organization(name="concurrency-test-org")
        session.add(org)
        await session.flush()
        chain_state = ChainState(org_id=org.id)
        session.add(chain_state)
        await session.commit()
        org_id = org.id

    async def insert_one(idx: int):
        async with session_factory() as session:
            return await build_and_insert_record(
                session, org_id, _make_action(action_name=f"concurrent_{idx}")
            )

    # Fire 10 concurrent inserts
    results = await asyncio.gather(*[insert_one(i) for i in range(10)])

    sequences = sorted(r.sequence_number for r in results)
    assert sequences == list(range(1, 11)), f"Expected 1-10, got {sequences}"

    # Verify chain integrity
    async with session_factory() as session:
        verification = await verify_chain(session, org_id)
        assert verification.is_valid is True
        assert verification.records_checked == 10


# ── Cross-org data isolation ───────────────────────────────


@pytest.mark.asyncio
async def test_cross_org_data_isolation(db_engine):
    """Records from one org must not be visible to another org."""
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        org_a = Organization(name="org-a")
        org_b = Organization(name="org-b")
        session.add_all([org_a, org_b])
        await session.flush()
        cs_a = ChainState(org_id=org_a.id)
        cs_b = ChainState(org_id=org_b.id)
        session.add_all([cs_a, cs_b])
        await session.commit()
        org_a_id, org_b_id = org_a.id, org_b.id

    async with session_factory() as session:
        for i in range(3):
            await build_and_insert_record(
                session, org_a_id, _make_action(action_name=f"org_a_action_{i}")
            )

    async with session_factory() as session:
        for i in range(2):
            await build_and_insert_record(
                session, org_b_id, _make_action(action_name=f"org_b_action_{i}")
            )

    async with session_factory() as session:
        result = await session.execute(
            select(ActionRecord).where(ActionRecord.org_id == org_a_id)
        )
        org_a_records = result.scalars().all()
        assert len(org_a_records) == 3
        assert all(r.action_name.startswith("org_a_") for r in org_a_records)

    async with session_factory() as session:
        result = await session.execute(
            select(ActionRecord).where(ActionRecord.org_id == org_b_id)
        )
        org_b_records = result.scalars().all()
        assert len(org_b_records) == 2
        assert all(r.action_name.startswith("org_b_") for r in org_b_records)

    async with session_factory() as session:
        v_a = await verify_chain(session, org_a_id)
        v_b = await verify_chain(session, org_b_id)
        assert v_a.is_valid is True
        assert v_b.is_valid is True
        assert v_a.records_checked == 3
        assert v_b.records_checked == 2


# ── Checkpoint tampering detection ─────────────────────────


@pytest.mark.asyncio
async def test_tampered_checkpoint_signature_fails(db_session, org_and_key):
    """A checkpoint with a modified signature must fail verification."""
    org, _, _ = org_and_key

    await build_and_insert_record(
        db_session, org.id, _make_action(action_name="for_checkpoint")
    )

    checkpoint = await create_checkpoint(db_session, org.id)
    assert checkpoint.signature is not None

    # Tamper with the signature
    checkpoint.signature = "0" * 64
    is_valid = await verify_checkpoint(db_session, checkpoint)
    assert is_valid is False


@pytest.mark.asyncio
async def test_tampered_checkpoint_hash_fails(db_session, org_and_key):
    """A checkpoint with a modified hash_at_checkpoint must fail verification."""
    org, _, _ = org_and_key

    await build_and_insert_record(
        db_session, org.id, _make_action(action_name="for_hash_tamper")
    )

    checkpoint = await create_checkpoint(db_session, org.id)

    # Tamper with the stored hash
    checkpoint.hash_at_checkpoint = "0" * 64
    is_valid = await verify_checkpoint(db_session, checkpoint)
    assert is_valid is False


# ── Hash consistency after DB round-trip ───────────────────


@pytest.mark.asyncio
async def test_hash_survives_db_roundtrip(db_engine, org_and_key):
    """Record hash must still verify after being read back from the database."""
    org, _, _ = org_and_key
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        record = await build_and_insert_record(
            session, org.id,
            _make_action(action_name="roundtrip_test", duration_ms=42),
        )
        original_hash = record.record_hash
        record_id = record.id

    async with session_factory() as session:
        result = await session.execute(
            select(ActionRecord).where(ActionRecord.id == record_id)
        )
        reloaded = result.scalar_one()

        assert reloaded.record_hash == original_hash
        assert verify_record_hash(reloaded) is True


# ── Permission matrix ──────────────────────────────────────


@pytest.mark.asyncio
async def test_read_key_cannot_write(async_client, org_and_key, db_session):
    """A read-only API key must be rejected on write endpoints."""
    org, _, _ = org_and_key
    raw_key, _ = await generate_api_key(db_session, org.id, "reader", ["read"])

    resp = await async_client.post(
        "/v1/actions",
        json={"action_name": "x", "action_type": "y", "agent_name": "z", "result": "success"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_read_key_cannot_admin(async_client, org_and_key, db_session):
    """A read-only API key must be rejected on admin endpoints."""
    org, _, _ = org_and_key
    raw_key, _ = await generate_api_key(db_session, org.id, "reader2", ["read"])

    resp = await async_client.post(
        "/v1/api-keys",
        json={"name": "sneaky", "permissions": ["read", "write", "admin"]},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_write_key_cannot_admin(async_client, org_and_key, db_session):
    """A write-only API key must be rejected on admin endpoints."""
    org, _, _ = org_and_key
    raw_key, _ = await generate_api_key(db_session, org.id, "writer", ["read", "write"])

    resp = await async_client.post(
        "/v1/api-keys",
        json={"name": "sneaky", "permissions": ["admin"]},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_write_key_can_read(async_client, org_and_key, db_session):
    """A write key with read permission should be able to read."""
    org, _, _ = org_and_key
    raw_key, _ = await generate_api_key(db_session, org.id, "rw", ["read", "write"])

    resp = await async_client.get(
        "/v1/actions",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200


# ── Input validation ───────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_action_name_rejected(async_client, org_and_key):
    """Empty action_name must be rejected by validation."""
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/actions",
        json={"action_name": "", "action_type": "test", "agent_name": "a", "result": "success"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_batch_over_100_rejected(async_client, org_and_key):
    """Batch with more than 100 records must be rejected."""
    _, raw_key, _ = org_and_key
    records = [
        {"action_name": f"batch_{i}", "action_type": "test", "agent_name": "a", "result": "success"}
        for i in range(101)
    ]
    resp = await async_client.post(
        "/v1/actions/batch",
        json={"records": records},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_empty_batch_rejected(async_client, org_and_key):
    """Batch with zero records must be rejected."""
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/actions/batch",
        json={"records": []},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_negative_duration_rejected(async_client, org_and_key):
    """Negative duration_ms must be rejected."""
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "neg_dur", "action_type": "test",
            "agent_name": "a", "result": "success", "duration_ms": -1,
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 422


# ── Batch atomicity ────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_sequences_are_contiguous(async_client, org_and_key):
    """Batch insert must produce contiguous sequence numbers."""
    _, raw_key, _ = org_and_key
    records = [
        {"action_name": f"contiguous_{i}", "action_type": "test",
         "agent_name": "a", "result": "success"}
        for i in range(10)
    ]
    resp = await async_client.post(
        "/v1/actions/batch",
        json={"records": records},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    seqs = [r["sequence_number"] for r in data]
    for i in range(1, len(seqs)):
        assert seqs[i] == seqs[i - 1] + 1, f"Gap at index {i}: {seqs}"
    for i in range(1, len(data)):
        assert data[i]["previous_hash"] == data[i - 1]["record_hash"]


# ── API key expiration ─────────────────────────────────────


@pytest.mark.asyncio
async def test_expired_key_is_rejected(async_client, org_and_key, db_session):
    """A key whose expires_at is in the past must be rejected with 401."""
    org, _, _ = org_and_key
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    raw_key, _ = await generate_api_key(
        db_session, org.id, "expired-key", ["read", "write"], expires_at=past
    )

    resp = await async_client.get(
        "/v1/actions",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_future_expiry_key_is_accepted(async_client, org_and_key, db_session):
    """A key whose expires_at is in the future must still be accepted."""
    org, _, _ = org_and_key
    future = datetime.now(timezone.utc) + timedelta(days=365)
    raw_key, _ = await generate_api_key(
        db_session, org.id, "future-key", ["read", "write"], expires_at=future
    )

    resp = await async_client.get(
        "/v1/actions",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_key_without_expiry_never_expires(async_client, org_and_key, db_session):
    """A key with no expires_at must remain valid indefinitely."""
    org, _, _ = org_and_key
    raw_key, _ = await generate_api_key(
        db_session, org.id, "no-expiry-key", ["read"], expires_at=None
    )

    resp = await async_client.get(
        "/v1/actions",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_create_api_key_with_expires_at(async_client, org_and_key):
    """Creating a key via the API endpoint with expires_at stores it correctly."""
    _, raw_key, _ = org_and_key
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

    resp = await async_client.post(
        "/v1/api-keys",
        json={"name": "expiring-key", "permissions": ["read"], "expires_at": future},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["expires_at"] is not None


# ── data_subject_id filtering ──────────────────────────────


@pytest.mark.asyncio
async def test_data_subject_id_filter_returns_only_matching_records(async_client, org_and_key):
    """GET /v1/actions?data_subject_id=X must return only records for that subject."""
    _, raw_key, _ = org_and_key

    # Record for subject A
    await async_client.post(
        "/v1/actions",
        json={
            "action_name": "action_for_alice",
            "action_type": "decision",
            "agent_name": "agent",
            "result": "success",
            "data_subject_id": "user_alice",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    # Record for subject B
    await async_client.post(
        "/v1/actions",
        json={
            "action_name": "action_for_bob",
            "action_type": "decision",
            "agent_name": "agent",
            "result": "success",
            "data_subject_id": "user_bob",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    # Record with no subject
    await async_client.post(
        "/v1/actions",
        json={
            "action_name": "no_subject_action",
            "action_type": "function_call",
            "agent_name": "agent",
            "result": "success",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    resp = await async_client.get(
        "/v1/actions?data_subject_id=user_alice",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["records"][0]["data_subject_id"] == "user_alice"
    assert data["records"][0]["action_name"] == "action_for_alice"


@pytest.mark.asyncio
async def test_data_subject_id_stored_in_record(async_client, org_and_key):
    """data_subject_id written on creation must be returned in the response."""
    _, raw_key, _ = org_and_key

    resp = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "dsid_test",
            "action_type": "decision",
            "agent_name": "agent",
            "result": "success",
            "data_subject_id": "subject_xyz",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data_subject_id"] == "subject_xyz"


# ── Agent auto-registration ────────────────────────────────


@pytest.mark.asyncio
async def test_recording_action_auto_creates_agent(async_client, org_and_key):
    """Recording an action must auto-create the agent if it doesn't already exist."""
    _, raw_key, _ = org_and_key

    await async_client.post(
        "/v1/actions",
        json={
            "action_name": "auto_register_test",
            "action_type": "function_call",
            "agent_name": "auto-agent",
            "result": "success",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    resp = await async_client.get(
        "/v1/agents",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    agents = resp.json()
    agent_names = [a["name"] for a in agents]
    assert "auto-agent" in agent_names


@pytest.mark.asyncio
async def test_repeated_actions_same_agent_no_duplicate(async_client, org_and_key):
    """Multiple actions from the same agent must not create duplicate agent rows."""
    _, raw_key, _ = org_and_key

    for _ in range(3):
        await async_client.post(
            "/v1/actions",
            json={
                "action_name": "repeated",
                "action_type": "function_call",
                "agent_name": "dedup-agent",
                "result": "success",
            },
            headers={"Authorization": f"Bearer {raw_key}"},
        )

    resp = await async_client.get(
        "/v1/agents",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    dedup_agents = [a for a in resp.json() if a["name"] == "dedup-agent"]
    assert len(dedup_agents) == 1


# ── Actions filtering ──────────────────────────────────────


@pytest.mark.asyncio
async def test_filter_actions_by_result(async_client, org_and_key):
    """GET /v1/actions?result=failure must return only failure records."""
    _, raw_key, _ = org_and_key

    await async_client.post(
        "/v1/actions",
        json={"action_name": "ok", "action_type": "f", "agent_name": "a", "result": "success"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    await async_client.post(
        "/v1/actions",
        json={"action_name": "fail", "action_type": "f", "agent_name": "a", "result": "failure"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    resp = await async_client.get(
        "/v1/actions?result=failure",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert all(r["result"] == "failure" for r in data["records"])


@pytest.mark.asyncio
async def test_filter_actions_by_agent_name(async_client, org_and_key):
    """GET /v1/actions?agent_name=X must return only records from that agent."""
    _, raw_key, _ = org_and_key

    await async_client.post(
        "/v1/actions",
        json={"action_name": "a1", "action_type": "f", "agent_name": "filter-agent", "result": "success"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    await async_client.post(
        "/v1/actions",
        json={"action_name": "a2", "action_type": "f", "agent_name": "other-agent", "result": "success"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    resp = await async_client.get(
        "/v1/actions?agent_name=filter-agent",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert all(r["agent_name"] == "filter-agent" for r in data["records"])


@pytest.mark.asyncio
async def test_filter_actions_by_action_type(async_client, org_and_key):
    """GET /v1/actions?action_type=decision must return only decision records."""
    _, raw_key, _ = org_and_key

    await async_client.post(
        "/v1/actions",
        json={"action_name": "d1", "action_type": "decision", "agent_name": "a", "result": "success"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    await async_client.post(
        "/v1/actions",
        json={"action_name": "f1", "action_type": "function_call", "agent_name": "a", "result": "success"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    resp = await async_client.get(
        "/v1/actions?action_type=decision",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert all(r["action_type"] == "decision" for r in data["records"])


@pytest.mark.asyncio
async def test_actions_pagination(async_client, org_and_key):
    """limit and offset must correctly page through results."""
    _, raw_key, _ = org_and_key

    for i in range(5):
        await async_client.post(
            "/v1/actions",
            json={"action_name": f"page_{i}", "action_type": "f", "agent_name": "a", "result": "success"},
            headers={"Authorization": f"Bearer {raw_key}"},
        )

    page1 = await async_client.get(
        "/v1/actions?limit=2&offset=0",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    page2 = await async_client.get(
        "/v1/actions?limit=2&offset=2",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert page1.status_code == 200
    assert page2.status_code == 200
    ids1 = {r["id"] for r in page1.json()["records"]}
    ids2 = {r["id"] for r in page2.json()["records"]}
    assert ids1.isdisjoint(ids2), "Pages must not overlap"
