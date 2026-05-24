import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from ..database import get_db
from ..models import ActionRecord, APIKey, IdempotencyRecord
from ..schemas.action import (
    ActionRecordCreate,
    ActionRecordResponse,
    ActionRecordBatchCreate,
    ActionRecordListResponse,
    _detect_phi_shape,
)
from ..services.auth import require_permission
from ..services.chain import build_and_insert_record, build_and_insert_batch
from ..services.hashing import canonicalize

router = APIRouter(prefix="/actions", tags=["actions"])


# ── Idempotency helpers ──────────────────────────────────────────────────
IDEMPOTENCY_TTL = timedelta(hours=24)

# Per-(org_id, key) asyncio locks serialize duplicate-key requests within a
# single process — the first request in does the real work, subsequent
# requests block, then find the cached response. This is the in-process
# guarantee. Across processes, the UniqueConstraint on (org_id, key) plus
# the IntegrityError handler in _store_idempotent_response is the fallback.
_idem_locks: dict[tuple[str, str], asyncio.Lock] = {}
_idem_locks_lock = asyncio.Lock()


async def _get_idem_lock(org_id: str, key: str) -> asyncio.Lock:
    """Get or create a lock for the (org_id, key) pair."""
    async with _idem_locks_lock:
        composite = (org_id, key)
        if composite not in _idem_locks:
            _idem_locks[composite] = asyncio.Lock()
        return _idem_locks[composite]


def _validate_idempotency_key(key: str) -> None:
    """Reject malformed Idempotency-Key headers with 400."""
    if not (1 <= len(key) <= 64) or not key.isascii():
        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key must be 1-64 ASCII characters",
        )


# TODO(PR 5): replace with full heuristic from policy_engine.
# Until PR 5 lands the full kind-aware (live key blocks, test key warns)
# heuristic, the schema's base regex would still let DOB / SSN shapes
# slip through (``john_doe_19720314`` matches ``^[A-Za-z0-9_-]+$``). On
# first action, auto-discovery sets ``display_name=tenant_id`` which
# surfaces that shape in the AI Coverage Matrix. We reject obvious
# shapes uniformly (kind-aware behavior lands with PR 4 + PR 5).
def _reject_phi_shape_in_tenant_id(tenant_id: Optional[str]) -> None:
    """Raise 422 with code='phi_shape_in_tenant_id' if shape looks PHI-y.

    Forward-compat: emits the same error code PR 5 will use, so SDK +
    dashboard error handling does not need to change when the full
    heuristic ships.
    """
    if not tenant_id:
        return
    if not _detect_phi_shape(tenant_id):
        return
    raise HTTPException(
        status_code=422,
        detail={
            "code": "phi_shape_in_tenant_id",
            "message": (
                "tenant_id contains a PHI-like shape; use an opaque "
                "identifier instead. See "
                "docs.usevera.xyz/customers/tenant-id-guidance."
            ),
        },
    )


def _request_hash(payload: dict) -> str:
    """SHA-256 of canonical JSON of the request body."""
    canonical = canonicalize(payload)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _lookup_cached_response(
    session: AsyncSession,
    org_id: str,
    key: str,
    request_hash: str,
) -> Optional[IdempotencyRecord]:
    """Find an existing idempotency row for (org_id, key).

    Returns:
      - The cached row if it's still fresh and the request_hash matches.
      - None if there is no row, or if the row was expired (caller should
        fall through to fresh processing — the expired row has been deleted).

    Raises:
      HTTPException(409) if the row is fresh but the request body differs.
    """
    result = await session.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.org_id == org_id,
            IdempotencyRecord.key == key,
        )
    )
    cached = result.scalar_one_or_none()
    if cached is None:
        return None

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if cached.expires_at < now:
        # Stale — drop it and fall through to fresh processing
        await session.delete(cached)
        await session.commit()
        return None

    if cached.request_hash != request_hash:
        raise HTTPException(
            status_code=409,
            detail="Idempotency-Key reused with different request body",
        )

    return cached


async def _store_idempotent_response(
    session: AsyncSession,
    org_id: str,
    key: str,
    request_hash: str,
    status_code: int,
    response_body: dict | list,
) -> dict | list:
    """Insert an IdempotencyRecord. On UniqueViolation (concurrent insert won),
    re-read the winning row and return its response_body so both racers see
    the same answer.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    expires_at = now + IDEMPOTENCY_TTL

    record = IdempotencyRecord(
        org_id=org_id,
        key=key,
        request_hash=request_hash,
        status_code=status_code,
        response_body=response_body,
        expires_at=expires_at,
    )
    session.add(record)
    try:
        await session.commit()
        return response_body
    except IntegrityError:
        await session.rollback()
        # Concurrent insert won the race — return the winning response.
        result = await session.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.org_id == org_id,
                IdempotencyRecord.key == key,
            )
        )
        winner = result.scalar_one()
        return winner.response_body


def _record_to_response(record: ActionRecord) -> ActionRecordResponse:
    return ActionRecordResponse(
        id=record.id,
        org_id=record.org_id,
        sequence_number=record.sequence_number,
        previous_hash=record.previous_hash,
        record_hash=record.record_hash,
        recorded_at=record.recorded_at,
        agent_name=record.agent_name,
        agent_version=record.agent_version,
        agent_id=record.agent_id,
        data_subject_id=record.data_subject_id,
        model_id=record.model_id,
        model_version=record.model_version,
        framework=record.framework,
        framework_version=record.framework_version,
        action_type=record.action_type,
        action_name=record.action_name,
        action_description=record.action_description,
        action_timestamp=record.action_timestamp,
        target_system=record.target_system,
        target_resource=record.target_resource,
        # Phase 1 PR 1: surface promoted columns to API consumers so the
        # SDK round-trip + dashboard scoping work without needing to
        # re-derive these from metadata_.
        tenant_id=record.tenant_id,
        domain=record.domain,
        action_class=record.action_class,
        authorized_by=record.authorized_by,
        authorization_scope=record.authorization_scope,
        delegation_chain=record.delegation_chain or [],
        result=record.result,
        error_message=record.error_message,
        duration_ms=record.duration_ms,
        input_data=record.input_data or {},
        policies_applied=record.policies_applied or [],
        environment=record.environment or {},
        outcome=record.outcome or {},
        reasoning=record.reasoning or {},
        metadata=record.metadata_ or {},
    )


async def _create_action_impl(
    session: AsyncSession,
    org_id: str,
    data: ActionRecordCreate,
) -> dict:
    record = await build_and_insert_record(session, org_id, data)
    return _record_to_response(record).model_dump(mode="json")


async def _create_batch_impl(
    session: AsyncSession,
    org_id: str,
    data: ActionRecordBatchCreate,
) -> list[dict]:
    records = await build_and_insert_batch(session, org_id, data.records)
    return [_record_to_response(r).model_dump(mode="json") for r in records]


async def _run_with_idempotency(
    session: AsyncSession,
    org_id: str,
    idempotency_key: Optional[str],
    payload_for_hash: dict,
    do_work,
):
    """Wrap a write operation with idempotency dedupe.

    Cache lookups + the actual write + cache write all run under a per-
    (org_id, key) lock so concurrent retries within a single process are
    serialized: first request wins and inserts, second sees the cached
    response. Across processes, the UniqueConstraint on (org_id, key) is
    the fallback (see _store_idempotent_response).

    Policy BLOCK note: ``do_work`` may raise ``HTTPException(409)`` after
    the audit record is committed (a block-action policy fired). When that
    happens we still cache the 409 response — replays of the same
    Idempotency-Key must observe the same outcome.
    """
    if idempotency_key is None:
        # Plain path — no cache, no lock
        body = await do_work()
        return JSONResponse(status_code=200, content=body)

    _validate_idempotency_key(idempotency_key)
    request_hash = _request_hash(payload_for_hash)

    lock = await _get_idem_lock(org_id, idempotency_key)
    async with lock:
        cached = await _lookup_cached_response(
            session, org_id, idempotency_key, request_hash
        )
        if cached is not None:
            return JSONResponse(
                status_code=cached.status_code,
                content=cached.response_body,
            )

        # Do the real work. We only cache deterministic outcomes:
        #   - 200 success (record inserted)
        #   - 409 policy block (record inserted with result="blocked",
        #     then HTTPException raised to surface the block)
        # Any other exception (validation, DB error, transient failure)
        # bubbles up uncached so the client can retry with the same key.
        try:
            body = await do_work()
        except HTTPException as exc:
            if exc.status_code == 409 and isinstance(exc.detail, dict) \
                    and exc.detail.get("error") == "policy_block":
                # Cache the policy_block response. The audit record is
                # already committed; replays must surface the same 409.
                cached_body = await _store_idempotent_response(
                    session,
                    org_id=org_id,
                    key=idempotency_key,
                    request_hash=request_hash,
                    status_code=409,
                    response_body=exc.detail,
                )
                return JSONResponse(status_code=409, content=cached_body)
            raise

        body = await _store_idempotent_response(
            session,
            org_id=org_id,
            key=idempotency_key,
            request_hash=request_hash,
            status_code=200,
            response_body=body,
        )
        return JSONResponse(status_code=200, content=body)


@router.post("")
async def create_action(
    data: ActionRecordCreate,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("write")),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    org_id, _ = auth

    # Bridge guard until PR 5 lands the full PHI heuristic.
    _reject_phi_shape_in_tenant_id(data.tenant_id)

    async def do_work() -> dict:
        return await _create_action_impl(session, org_id, data)

    return await _run_with_idempotency(
        session=session,
        org_id=org_id,
        idempotency_key=idempotency_key,
        payload_for_hash=data.model_dump(mode="json"),
        do_work=do_work,
    )


@router.post("/batch")
async def create_action_batch(
    data: ActionRecordBatchCreate,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("write")),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    org_id, _ = auth

    # Bridge guard until PR 5 lands the full PHI heuristic. Check every
    # record's tenant_id — any single PHI-shaped value rejects the whole
    # batch (the batch is atomic anyway; partial acceptance would lie).
    for record in data.records:
        _reject_phi_shape_in_tenant_id(record.tenant_id)

    async def do_work() -> list[dict]:
        return await _create_batch_impl(session, org_id, data)

    return await _run_with_idempotency(
        session=session,
        org_id=org_id,
        idempotency_key=idempotency_key,
        payload_for_hash=data.model_dump(mode="json"),
        do_work=do_work,
    )


def _escape_like(s: str) -> str:
    """Escape special LIKE pattern characters."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("", response_model=ActionRecordListResponse)
async def list_actions(
    agent_name: Optional[str] = None,
    action_type: Optional[str] = None,
    result: Optional[str] = None,
    data_subject_id: Optional[str] = None,
    # Phase 1 PR 13: per-customer filter for the Customer detail page's
    # decisions stream. The promoted ``tenant_id`` column on ActionRecord
    # already has an index (idx_ar_org_tenant_seq) so this is cheap.
    tenant_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    authorized_by: Optional[str] = None,
    search: Optional[str] = Query(default=None, max_length=200),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("read")),
):
    org_id, _ = auth

    query = select(ActionRecord).where(ActionRecord.org_id == org_id)
    count_query = select(func.count(ActionRecord.id)).where(ActionRecord.org_id == org_id)

    if agent_name:
        query = query.where(ActionRecord.agent_name == agent_name)
        count_query = count_query.where(ActionRecord.agent_name == agent_name)
    if action_type:
        query = query.where(ActionRecord.action_type == action_type)
        count_query = count_query.where(ActionRecord.action_type == action_type)
    if result:
        query = query.where(ActionRecord.result == result)
        count_query = count_query.where(ActionRecord.result == result)
    if authorized_by:
        query = query.where(ActionRecord.authorized_by == authorized_by)
        count_query = count_query.where(ActionRecord.authorized_by == authorized_by)
    if data_subject_id:
        query = query.where(ActionRecord.data_subject_id == data_subject_id)
        count_query = count_query.where(ActionRecord.data_subject_id == data_subject_id)
    if tenant_id:
        query = query.where(ActionRecord.tenant_id == tenant_id)
        count_query = count_query.where(ActionRecord.tenant_id == tenant_id)
    if start_date:
        query = query.where(ActionRecord.action_timestamp >= start_date)
        count_query = count_query.where(ActionRecord.action_timestamp >= start_date)
    if end_date:
        query = query.where(ActionRecord.action_timestamp <= end_date)
        count_query = count_query.where(ActionRecord.action_timestamp <= end_date)
    if search:
        escaped = _escape_like(search)
        pattern = f"%{escaped}%"
        search_filter = ActionRecord.action_name.ilike(pattern)
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)

    total_result = await session.execute(count_query)
    total = total_result.scalar()

    query = query.order_by(ActionRecord.sequence_number.desc()).limit(limit).offset(offset)
    records_result = await session.execute(query)
    records = records_result.scalars().all()

    return ActionRecordListResponse(
        records=[_record_to_response(r) for r in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{record_id}", response_model=ActionRecordResponse)
async def get_action(
    record_id: str,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("read")),
):
    org_id, _ = auth
    result = await session.execute(
        select(ActionRecord).where(
            ActionRecord.id == record_id,
            ActionRecord.org_id == org_id,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Action record not found")
    return _record_to_response(record)
