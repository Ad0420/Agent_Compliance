import asyncio
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ActionRecord, ChainState
from ..schemas.action import ActionRecordCreate
from .hashing import canonicalize, compute_record_hash, extract_hashable_fields

# Per-org locks for concurrency safety — prevents Org A from blocking Org B.
# NOTE: These are in-process only. For multi-instance deployments, the
# SELECT FOR UPDATE on chain_state provides the real concurrency guarantee.
_chain_locks: dict[str, asyncio.Lock] = {}
_locks_lock = asyncio.Lock()


async def _get_org_lock(org_id: str) -> asyncio.Lock:
    """Get or create a per-org lock."""
    async with _locks_lock:
        if org_id not in _chain_locks:
            _chain_locks[org_id] = asyncio.Lock()
        return _chain_locks[org_id]


def _is_sqlite(session: AsyncSession) -> bool:
    """Check if the session is using SQLite (which doesn't support FOR UPDATE)."""
    url = str(session.bind.url) if session.bind else ""
    return "sqlite" in url


async def _lock_chain_state(session: AsyncSession, org_id: str) -> ChainState:
    """Read chain_state with a row-level lock (PostgreSQL) or plain read (SQLite).

    PostgreSQL: SELECT ... FOR UPDATE prevents concurrent reads until commit.
    SQLite: No row locking, relies on the in-process asyncio lock.
    """
    if _is_sqlite(session):
        result = await session.execute(
            select(ChainState).where(ChainState.org_id == org_id)
        )
    else:
        result = await session.execute(
            select(ChainState)
            .where(ChainState.org_id == org_id)
            .with_for_update()
        )
    chain_state = result.scalar_one_or_none()
    if chain_state is None:
        raise HTTPException(
            status_code=404,
            detail=f"Chain state not found for organization {org_id}. Was the org initialized correctly?",
        )
    return chain_state


def _create_record(
    org_id: str, data: ActionRecordCreate, new_sequence: int, previous_hash: str, now: datetime
) -> ActionRecord:
    """Create an ActionRecord instance and compute its hash."""
    action_timestamp = data.action_timestamp or now

    record = ActionRecord(
        org_id=org_id,
        sequence_number=new_sequence,
        previous_hash=previous_hash,
        agent_name=data.agent_name,
        agent_version=data.agent_version,
        model_id=data.model_id,
        model_version=data.model_version,
        framework=data.framework,
        framework_version=data.framework_version,
        action_type=data.action_type,
        action_name=data.action_name,
        action_description=data.action_description,
        action_timestamp=action_timestamp,
        target_system=data.target_system,
        target_resource=data.target_resource,
        authorized_by=data.authorized_by,
        authorization_scope=data.authorization_scope,
        delegation_chain=data.delegation_chain,
        result=data.result,
        error_message=data.error_message,
        duration_ms=data.duration_ms,
        input_data=data.input_data,
        policies_applied=data.policies_applied,
        environment=data.environment,
        reasoning=data.reasoning,
        outcome=data.outcome,
        metadata_=data.metadata,
    )

    fields = extract_hashable_fields(record)
    canonical = canonicalize(fields)
    record.record_hash = compute_record_hash(canonical, previous_hash)
    return record


async def build_and_insert_record(
    session: AsyncSession, org_id: str, data: ActionRecordCreate
) -> ActionRecord:
    """Build a single chained action record and insert it."""
    lock = await _get_org_lock(org_id)
    async with lock:
        chain_state = await _lock_chain_state(session, org_id)

        new_sequence = chain_state.latest_sequence + 1
        previous_hash = chain_state.latest_hash
        now = datetime.now(timezone.utc)

        record = _create_record(org_id, data, new_sequence, previous_hash, now)
        session.add(record)

        chain_state.latest_sequence = new_sequence
        chain_state.latest_hash = record.record_hash
        chain_state.updated_at = now

        await session.commit()
        await session.refresh(record)
        return record


async def build_and_insert_batch(
    session: AsyncSession, org_id: str, records_data: list[ActionRecordCreate]
) -> list[ActionRecord]:
    """Build and insert a batch of chained action records atomically.

    The entire batch is inserted under a single lock hold, ensuring
    no interleaving with concurrent requests for the same org.
    """
    lock = await _get_org_lock(org_id)
    async with lock:
        chain_state = await _lock_chain_state(session, org_id)

        now = datetime.now(timezone.utc)
        records = []

        for data in records_data:
            new_sequence = chain_state.latest_sequence + 1
            previous_hash = chain_state.latest_hash

            record = _create_record(org_id, data, new_sequence, previous_hash, now)
            session.add(record)

            chain_state.latest_sequence = new_sequence
            chain_state.latest_hash = record.record_hash
            records.append(record)

        chain_state.updated_at = now
        await session.commit()
        for record in records:
            await session.refresh(record)
        return records
