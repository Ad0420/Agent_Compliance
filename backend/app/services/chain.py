import asyncio
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ActionRecord, Agent, ChainState, Organization, PolicyViolation
from ..schemas.action import ActionRecordCreate
from .hashing import canonicalize, compute_record_hash, extract_hashable_fields
from .policy_engine import evaluate_policies
from .email import send_policy_violation_alert

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


async def _get_or_create_agent(
    session: AsyncSession, org_id: str, agent_name: str, agent_version: str | None
) -> str:
    """Return the agent ID for (org_id, agent_name), creating the agent if it doesn't exist."""
    result = await session.execute(
        select(Agent).where(Agent.org_id == org_id, Agent.name == agent_name)
    )
    agent = result.scalar_one_or_none()
    if agent is not None:
        return agent.id

    agent = Agent(org_id=org_id, name=agent_name)
    session.add(agent)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        result = await session.execute(
            select(Agent).where(Agent.org_id == org_id, Agent.name == agent_name)
        )
        agent = result.scalar_one()
    return agent.id


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
    org_id: str, data: ActionRecordCreate, new_sequence: int, previous_hash: str, now: datetime,
    agent_id: str | None = None,
) -> ActionRecord:
    """Create an ActionRecord instance and compute its hash."""
    action_timestamp = data.action_timestamp or now

    record = ActionRecord(
        org_id=org_id,
        sequence_number=new_sequence,
        previous_hash=previous_hash,
        agent_id=agent_id,
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
        data_subject_id=data.data_subject_id,
    )

    fields = extract_hashable_fields(record)
    canonical = canonicalize(fields)
    record.record_hash = compute_record_hash(canonical, previous_hash)
    return record


async def _store_violations_and_notify(
    session: AsyncSession,
    org_id: str,
    record_id: str,
    policy_results: list[dict],
) -> None:
    """Insert PolicyViolation rows for triggered policies and fire alert emails.

    This runs AFTER the main record commit, in a separate commit.
    If this fails, the violation context is still encoded in policies_applied
    inside the tamper-proof record — no audit data is truly lost.
    """
    triggered = [r for r in policy_results if r.get("triggered")]
    if not triggered:
        return

    # Fetch org for alert_email
    org = await session.get(Organization, org_id)

    for result in triggered:
        violation = PolicyViolation(
            org_id=org_id,
            policy_id=result.get("policy_id"),
            record_id=record_id,
            severity=result["severity"],
            context=result.get("context", {}),
        )
        session.add(violation)

    try:
        await session.commit()
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "Failed to store policy violations for record %s (org %s)", record_id, org_id
        )
        return

    # Fire-and-forget emails for email-action policies
    if org and org.alert_email:
        for result in triggered:
            if result.get("action") == "email":
                asyncio.create_task(
                    send_policy_violation_alert(
                        org_name=org.name,
                        org_id=org_id,
                        alert_email=org.alert_email,
                        policy_name=result["policy_name"],
                        condition_type=result["condition_type"],
                        severity=result["severity"],
                        record_id=record_id,
                        context=result.get("context", {}),
                    )
                )



async def build_and_insert_record(
    session: AsyncSession, org_id: str, data: ActionRecordCreate
) -> ActionRecord:
    """Build a single chained action record and insert it."""
    lock = await _get_org_lock(org_id)
    async with lock:
        chain_state = await _lock_chain_state(session, org_id)

        new_sequence = chain_state.latest_sequence + 1
        previous_hash = chain_state.latest_hash
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # [POLICY ENGINE] Evaluate policies BEFORE creating the agent.
        # unknown_agent must see the pre-insertion state — if we create the agent first,
        # the evaluator's SELECT finds the just-flushed row and reports registered=True.
        policy_results = await evaluate_policies(session, org_id, data)
        if policy_results:
            data = data.model_copy(update={"policies_applied": policy_results})

        agent_id = await _get_or_create_agent(session, org_id, data.agent_name, data.agent_version)

        record = _create_record(org_id, data, new_sequence, previous_hash, now, agent_id)
        session.add(record)

        chain_state.latest_sequence = new_sequence
        chain_state.latest_hash = record.record_hash
        chain_state.updated_at = now

        await session.commit()
        await session.refresh(record)

    # [POLICY ENGINE] Store violations + send emails (outside lock, separate commit)
    if policy_results:
        await _store_violations_and_notify(session, org_id, record.id, policy_results)

    return record


async def build_and_insert_batch(
    session: AsyncSession, org_id: str, records_data: list[ActionRecordCreate]
) -> list[ActionRecord]:
    """Build and insert a batch of chained action records atomically.

    The entire batch is inserted under a single lock hold, ensuring
    no interleaving with concurrent requests for the same org.

    TODO: Add policy evaluation for batch records in v2.
    Batch records have policies_applied = [] (no policy results).
    """
    lock = await _get_org_lock(org_id)
    async with lock:
        chain_state = await _lock_chain_state(session, org_id)

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        records = []

        for data in records_data:
            new_sequence = chain_state.latest_sequence + 1
            previous_hash = chain_state.latest_hash

            agent_id = await _get_or_create_agent(session, org_id, data.agent_name, data.agent_version)
            record = _create_record(org_id, data, new_sequence, previous_hash, now, agent_id)
            session.add(record)

            chain_state.latest_sequence = new_sequence
            chain_state.latest_hash = record.record_hash
            records.append(record)

        chain_state.updated_at = now
        await session.commit()
        for record in records:
            await session.refresh(record)
        return records
