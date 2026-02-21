"""Integration tests for the chain building service."""

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models import ActionRecord, ChainState
from app.schemas.action import ActionRecordCreate
from app.services.chain import build_and_insert_record, build_and_insert_batch
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


@pytest.mark.asyncio
async def test_single_record_insertion(db_session, org_and_key):
    org, _, _ = org_and_key
    data = _make_action(action_name="first_action")
    record = await build_and_insert_record(db_session, org.id, data)

    assert record.sequence_number == 1
    assert record.previous_hash == "GENESIS"
    assert record.record_hash is not None
    assert len(record.record_hash) == 64


@pytest.mark.asyncio
async def test_sequential_chain_building(db_session, org_and_key):
    org, _, _ = org_and_key

    # Get current sequence to handle fixture reuse
    result = await db_session.execute(
        select(ChainState).where(ChainState.org_id == org.id)
    )
    chain_state = result.scalar_one()
    start_seq = chain_state.latest_sequence

    r1 = await build_and_insert_record(db_session, org.id, _make_action(action_name="action_a"))
    r2 = await build_and_insert_record(db_session, org.id, _make_action(action_name="action_b"))
    r3 = await build_and_insert_record(db_session, org.id, _make_action(action_name="action_c"))

    assert r1.sequence_number == start_seq + 1
    assert r2.sequence_number == start_seq + 2
    assert r3.sequence_number == start_seq + 3

    # Each record's previous_hash links to the prior record's hash
    assert r2.previous_hash == r1.record_hash
    assert r3.previous_hash == r2.record_hash


@pytest.mark.asyncio
async def test_batch_insert(db_session, org_and_key):
    org, _, _ = org_and_key

    records_data = [
        _make_action(action_name=f"batch_{i}") for i in range(5)
    ]
    records = await build_and_insert_batch(db_session, org.id, records_data)

    assert len(records) == 5
    for i in range(1, len(records)):
        assert records[i].previous_hash == records[i - 1].record_hash
        assert records[i].sequence_number == records[i - 1].sequence_number + 1


@pytest.mark.asyncio
async def test_chain_verification_passes(db_session, org_and_key):
    org, _, _ = org_and_key

    for i in range(3):
        await build_and_insert_record(
            db_session, org.id, _make_action(action_name=f"verify_{i}")
        )

    result = await verify_chain(db_session, org.id)
    assert result.is_valid is True
    assert result.records_checked > 0
