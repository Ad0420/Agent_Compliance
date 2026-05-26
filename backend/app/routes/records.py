"""``GET /v1/records/{action_record_id}/merkle-proof`` — Phase 3 Wave 3B.2.

Returns an independently-verifiable Merkle inclusion proof for a single
``ActionRecord``. See ``services/merkle_proof.py`` for the canonical
proof-building logic and the offline-verifier helper.

Error semantics:

* ``404`` — record doesn't exist OR is not in the caller's org (we don't
  distinguish: leaking "this id exists in some org" is a presence side-
  channel that customer-tier callers must not have).
* ``409 {"code": "checkpoint_pending"}`` with ``Retry-After: 60`` — record
  exists in the caller's org but is in the tail window (no checkpoint
  has been sealed at or above its sequence yet). Polite retry hint.
* ``403 {"code": "merkle_proof_phi_restricted"}`` — staff (``STAFF_READ_ONLY``)
  callers can never read the proof: the canonical form **must** match
  the hashed form (otherwise verification fails offline), and that form
  contains ``data_subject_id`` + ``input_data`` + ``metadata`` — i.e.
  PHI. Redacting the canonical form would lie about what was sealed;
  refusing the read is the only correct answer. Still writes a
  staff_audit_log row so the customer can see "Vera staff tried to pull
  a proof on record X but was blocked."
* ``500`` — only for true data-integrity bugs (proof root != sealed
  root, etc.); these are explicit ``ProofUnavailable`` codes from the
  service.

Why ``/v1/records/...`` and not ``/v1/actions/{id}/merkle-proof``:

The brief specifies ``/v1/records/{action_record_id}/merkle-proof`` and
treats the proof as a separate verification surface from the action-
record CRUD path. A standalone resource avoids tangling the proof
endpoint's IAM rules (staff-blocked) with the actions endpoint's rules
(staff-allowed-with-redaction).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import ActionRecord
from ..services.auth import AuthContext, require_permission_with_context
from ..services.iam import audit_staff_read
from ..services.merkle_proof import ProofUnavailable, build_proof

logger = logging.getLogger("vera.records.merkle_proof")


router = APIRouter(prefix="/records", tags=["records"])


@router.get("/{action_record_id}/merkle-proof")
async def get_merkle_proof(
    action_record_id: str,
    session: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_permission_with_context("read")),
):
    org_id = ctx.org_id

    # ── 1. Locate the record under the caller's org ───────────────────
    # Scope by ``org_id`` here so a customer in org A can never read a
    # record in org B even if they guessed the UUID. Returning 404 (not
    # 403) for cross-org is deliberate: a 403 leaks "this id exists,
    # just not for you."
    result = await session.execute(
        select(ActionRecord).where(
            ActionRecord.id == action_record_id,
            ActionRecord.org_id == org_id,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "record_not_found",
                "detail": "Action record not found",
            },
        )

    # ── 2. Staff cannot pull a proof — PHI in canonical form ──────────
    # The proof returns ``action_record_canonical`` which is the EXACT
    # canonical bytes that were hashed at seal time. Those bytes contain
    # ``data_subject_id`` + ``input_data`` + ``metadata`` (see
    # ``services/hashing.HASHABLE_FIELDS``). We can't redact those
    # fields without invalidating the proof — the verifier hashes the
    # bytes and compares to the leaf. So: refuse the read entirely for
    # staff, and audit-log the refusal so the customer can see it.
    #
    # Per Wave 3B.3 policy, we branch on ``ctx.is_staff`` so a future
    # STAFF_FULL tier inherits the same PHI guard without a per-route
    # fix.
    if ctx.is_staff:
        await audit_staff_read(
            session,
            staff_id=ctx.staff_id or "",
            endpoint="/v1/records/{record_id}/merkle-proof",
            org_id=org_id,
            resource_type="action_record_merkle_proof",
            resource_id=action_record_id,
            redacted=False,  # Read was REFUSED, not redacted.
        )
        raise HTTPException(
            status_code=403,
            detail={
                "code": "merkle_proof_phi_restricted",
                "detail": (
                    "Merkle proofs include the canonical bytes that were "
                    "hashed at seal time. Those bytes carry PHI fields "
                    "(data_subject_id, input_data, metadata) that cannot "
                    "be redacted without invalidating the proof. Vera "
                    "staff sessions are blocked from this endpoint; the "
                    "customer's own credentials are required."
                ),
            },
        )

    # ── 3. Build the proof ────────────────────────────────────────────
    try:
        payload = await build_proof(session, record=record)
    except ProofUnavailable as exc:
        if exc.code == "checkpoint_pending":
            # Tail window: a checkpoint hasn't been sealed at this
            # sequence yet. Polite Retry-After hint so SDK retry logic
            # can back off (and so curl users see the expected cadence).
            retry_after = exc.retry_after or 60
            return JSONResponse(
                status_code=409,
                content={
                    "code": "checkpoint_pending",
                    "detail": (
                        "This record has not been sealed into a "
                        "checkpoint yet. Retry after the next "
                        "checkpoint cadence tick."
                    ),
                },
                headers={"Retry-After": str(retry_after)},
            )
        # Anything else is a data-integrity bug (root mismatch, empty
        # window, etc.) — these should never reach a healthy
        # production system. 500 + log so ops can investigate; we
        # surface the code in the response so an operator running a
        # curl can correlate to the log line.
        logger.exception(
            "merkle_proof unavailable code=%s record_id=%s org_id=%s",
            exc.code,
            action_record_id,
            org_id,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "code": exc.code,
                "detail": (
                    "Merkle proof could not be constructed for this "
                    "record. Operators have been notified."
                ),
            },
        )

    return payload.to_dict()
