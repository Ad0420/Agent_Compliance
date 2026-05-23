import asyncio
import logging
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    ActionRecord,
    Agent,
    ChainState,
    Customer,
    CustomerAgent,
    Organization,
    PolicyViolation,
)
from ..schemas.action import ActionRecordCreate
from .hashing import canonicalize, compute_record_hash, extract_hashable_fields
from .policy_engine import evaluate_policies
from .email import send_policy_violation_alert
from .locks import get_org_lock
from .webhooks import dispatch_event

logger = logging.getLogger(__name__)


# Auto-discovery default when the SDK has not classified the action.
# Matches the v1-implementation-plan X4 guidance:
# "Unknown action classes land as `unclassified`, not silently create
# new coverage categories."
_DEFAULT_AGENT_TYPE = "unclassified"


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
        # ── Phase 1 PR 1: promoted columns ──
        # These three were previously stored inside ``metadata_`` and silently
        # dropped here, leaving the new indexed columns NULL even when the
        # SDK supplied values. The hash is computed over these fields
        # (see HASHABLE_FIELDS), so wiring them through is required for
        # both query indexing AND hash correctness.
        tenant_id=data.tenant_id,
        domain=data.domain,
        action_class=data.action_class,
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


async def _auto_discover_customer_and_agent(
    session: AsyncSession,
    *,
    org_id: str,
    tenant_id: str,
    agent_id: str,
    action_class: str | None,
    now: datetime,
) -> None:
    """Auto-create / touch Customer + CustomerAgent rows on action insert.

    Phase 1 PR 2 Stream B item B2.

    Contract:
      * If no Customer exists for ``(org_id, tenant_id)``, create one with
        ``status='pending_setup'``, ``baa_status='missing'``,
        ``display_name=tenant_id``, and ``first_seen_at=last_seen_at=now``.
      * If a Customer already exists, only advance ``last_seen_at`` —
        never rewrite ``display_name`` or ``status`` (the operator may
        have edited the display_name from the dashboard, and lifecycle
        state is owned by Phase 1 PR 3).
      * Stamp / touch a CustomerAgent row keyed on
        ``(customer_id, agent_type)``. ``agent_type`` is derived from
        ``data.action_class`` if present, otherwise ``"unclassified"``
        (matches X4 in v1-implementation-plan). The stamp is HISTORICAL
        per Codex E1: subsequent actions with the same triple only
        update ``last_seen_at``; the agent_type and agent_id columns are
        never rewritten.

    Cross-org tenant_id collision (a different org's customers table
    already holds this tenant_id) is logged as a warning. The webhook
    event emission is intentionally deferred to Phase 1 PR 3 — that PR
    owns ``new_customer_detected`` / ``cross_org_collision`` events.

    All inserts happen on the same session as the caller's. The caller
    runs inside the org lock and commits after this returns — if the
    parent commit fails, these rows roll back too (transactional safety
    per the test_plan "auto-discover transactional" row).
    """
    if not tenant_id:
        return

    # ── Customer: find-or-create ────────────────────────────────
    existing = await session.execute(
        select(Customer).where(
            Customer.org_id == org_id,
            Customer.tenant_id == tenant_id,
        )
    )
    customer = existing.scalar_one_or_none()
    if customer is None:
        # Cross-org collision detection. NB: we do NOT share or block —
        # tenant_id is org-scoped on purpose (one operator's "abridge"
        # may legitimately be a different operator's "abridge"). PR 3
        # will emit a webhook for ops review; PR 2 just logs.
        collision = await session.execute(
            select(Customer.org_id).where(
                Customer.tenant_id == tenant_id,
                Customer.org_id != org_id,
            ).limit(1)
        )
        other_org = collision.scalar_one_or_none()
        if other_org is not None:
            # TODO(PR 3): emit ``customer.cross_org_collision`` webhook
            # event so ops can review whether the operators are pointing
            # at the same downstream customer (a legitimate multi-tenant
            # setup) or whether someone typo'd a competitor's identifier.
            logger.warning(
                "cross-org tenant_id collision: org_id=%s auto-discovered "
                "tenant_id=%s which already exists under org_id=%s",
                org_id,
                tenant_id,
                other_org,
            )

        customer = Customer(
            org_id=org_id,
            tenant_id=tenant_id,
            display_name=tenant_id,
            status="pending_setup",
            baa_status="missing",
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(customer)
        try:
            await session.flush()
        except IntegrityError:
            # Concurrent insert (same tenant under same org) won the
            # race — re-read so we work with the surviving row.
            await session.rollback()
            again = await session.execute(
                select(Customer).where(
                    Customer.org_id == org_id,
                    Customer.tenant_id == tenant_id,
                )
            )
            customer = again.scalar_one()
            customer.last_seen_at = now
    else:
        customer.last_seen_at = now

    # ── CustomerAgent: stamp historically ────────────────────────
    # ``action_class`` is the most action-shaped signal we have today.
    # X4 (Codex DX) calls for an explicit ``agent_type`` parameter at
    # ``vera.init(...)`` in a later PR; until then ``unclassified``
    # is the safe default that doesn't silently invent coverage
    # categories.
    agent_type = (action_class or _DEFAULT_AGENT_TYPE).strip().lower() \
        or _DEFAULT_AGENT_TYPE

    ca_existing = await session.execute(
        select(CustomerAgent).where(
            CustomerAgent.customer_id == customer.id,
            # Compare to the normalised form to match the validates() hook.
            CustomerAgent.agent_type == agent_type,
        )
    )
    ca = ca_existing.scalar_one_or_none()
    if ca is None:
        ca = CustomerAgent(
            customer_id=customer.id,
            agent_id=agent_id,
            agent_type=agent_type,
            first_seen_at=now,
            last_seen_at=now,
            source="auto_discovered",
            confidence="high",
            status="active",
        )
        session.add(ca)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            again = await session.execute(
                select(CustomerAgent).where(
                    CustomerAgent.customer_id == customer.id,
                    CustomerAgent.agent_type == agent_type,
                )
            )
            ca = again.scalar_one()
            ca.last_seen_at = now
    else:
        # Touch only; do NOT rewrite agent_id or agent_type — those are
        # the historical stamp (Codex E1). If the same logical agent
        # later changes its metadata, the past coverage stays intact.
        ca.last_seen_at = now


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

    # Fire webhook events for every triggered policy. dispatch_event is itself
    # fire-and-forget (it schedules tasks and returns), so this loop does not
    # block the request.
    for result in triggered:
        await dispatch_event(
            session,
            org_id,
            "policy.violation",
            {
                "policy_id": result.get("policy_id"),
                "policy_name": result["policy_name"],
                "condition_type": result["condition_type"],
                "severity": result["severity"],
                "context": result.get("context", {}),
                "record_id": record_id,
            },
        )



async def build_and_insert_record(
    session: AsyncSession, org_id: str, data: ActionRecordCreate
) -> ActionRecord:
    """Build a single chained action record and insert it.

    Returns the inserted ``ActionRecord``. Raises ``HTTPException(409)``
    if a policy with ``action="block"`` fires — but only **after** the
    record has been committed with ``result="blocked"`` so the audit
    trail captures the attempted action and the chain stays intact.
    """
    lock = await get_org_lock(org_id)
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

        # [POLICY ENGINE] Detect any triggered BLOCK policies. The action
        # record is still inserted (so the regulator/dashboard can see what
        # was attempted) but with ``result="blocked"`` — the field is part
        # of the hashable payload, so the override must happen before
        # ``_create_record``.
        blocking_policies = [
            r for r in policy_results
            if r.get("triggered") and r.get("action") == "block"
        ]
        if blocking_policies:
            data = data.model_copy(update={"result": "blocked"})

        agent_id = await _get_or_create_agent(session, org_id, data.agent_name, data.agent_version)

        record = _create_record(org_id, data, new_sequence, previous_hash, now, agent_id)
        session.add(record)

        # [AUTO-DISCOVERY] Per Phase 1 PR 2 B2 — Customer + CustomerAgent
        # rows are created/touched as part of the SAME transaction as the
        # ActionRecord. If the ActionRecord commit below fails, these rows
        # roll back too (covers the "auto-discover transactional" test
        # case in v1-test-plan.md).
        if data.tenant_id:
            await _auto_discover_customer_and_agent(
                session,
                org_id=org_id,
                tenant_id=data.tenant_id,
                agent_id=agent_id,
                action_class=data.action_class,
                now=now,
            )

        chain_state.latest_sequence = new_sequence
        chain_state.latest_hash = record.record_hash
        chain_state.updated_at = now

        await session.commit()
        await session.refresh(record)

    # [POLICY ENGINE] Store violations + send emails (outside lock, separate commit)
    if policy_results:
        await _store_violations_and_notify(session, org_id, record.id, policy_results)

    # [POLICY ENGINE] If a BLOCK fired, raise AFTER the audit record is
    # durably committed and violations have been written. The 409 reaches
    # the SDK caller; the audit row + violation row stay behind.
    if blocking_policies:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "policy_block",
                "message": "Action blocked by policy",
                "record_id": record.id,
                "blocking_policies": [
                    {
                        "policy_id": r.get("policy_id"),
                        "policy_name": r.get("policy_name"),
                        "condition_type": r.get("condition_type"),
                        "severity": r.get("severity"),
                        "context": r.get("context", {}),
                    }
                    for r in blocking_policies
                ],
            },
        )

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
    lock = await get_org_lock(org_id)
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

            # [AUTO-DISCOVERY] Same Customer/CustomerAgent touch path as
            # the single-record API. Runs inside the batch's atomic
            # transaction — if any record's commit fails, the whole batch
            # rolls back including the customer/customer_agent rows.
            if data.tenant_id:
                await _auto_discover_customer_and_agent(
                    session,
                    org_id=org_id,
                    tenant_id=data.tenant_id,
                    agent_id=agent_id,
                    action_class=data.action_class,
                    now=now,
                )

            chain_state.latest_sequence = new_sequence
            chain_state.latest_hash = record.record_hash
            records.append(record)

        chain_state.updated_at = now
        await session.commit()
        for record in records:
            await session.refresh(record)
        return records
