"""IAM tier resolution + PHI redaction + staff-read audit.

Wave 3A.c (Phase 3) — closes Eng review finding 1E. Today, ``ActionRecord
.input_data``, ``ActionRecord.metadata_``, and ``Approval.context.
original_input_data`` can contain PHI. There is no staff-vs-customer
distinction in the API, so a Vera support engineer responding to a
customer ticket would see raw PHI in the response — a HIPAA business-
associate-grade concern.

This module:
  * Defines the ``IamTier`` enum that route handlers branch on.
  * Provides ``redact_action_record`` / ``redact_approval`` so PHI fields
    collapse to ``{}`` (for JSON columns whose downstream parsers expect
    a dict) or ``"[REDACTED]"`` (for string columns).
  * Provides ``audit_staff_read`` which best-effort logs every staff read
    to the ``staff_audit_log`` table. Failures NEVER 500 the request —
    a logging hiccup must not block the user response.

What is preserved at STAFF_READ_ONLY
------------------------------------
Chain integrity fields (record_hash, sequence_number, previous_hash,
agent_name, action_type, action_name, timestamps, result), gate metadata
in ``reasoning`` / on ``Approval.context`` (gate_name, required_role,
citation, reason), and aggregate counts. A staff engineer can confirm
"the chain is intact and the gate fired correctly" without seeing the
patient payload.

What is redacted at STAFF_READ_ONLY
-----------------------------------
ActionRecord:
  * ``input_data``     → ``{}``          (JSON column; consumers parse it
                                          as a dict)
  * ``metadata`` /
    ``metadata_``      → ``{}``          (same; both response and ORM
                                          shapes covered)
  * ``data_subject_id``→ ``"[REDACTED]"`` (string column; SDK consumers
                                          treat null differently from
                                          opaque, so we use the marker)

Approval.context:
  * ``original_input_data`` removed entirely from the context dict.

Out of scope (v1)
-----------------
  * STAFF_FULL break-glass tier (not in v1; would be next-phase work).
  * Per-field redaction policy. Whole-field redaction in v1; sub-field
    redaction is over-engineering for the immediate threat.
  * Customer-side "who read my data" dashboard surface (data is captured
    today; surface is Phase 4 polish).
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..database import AsyncSessionLocal
from ..models import StaffAuditLog

logger = logging.getLogger("vera.iam")


# Field-name constants kept here (single source of truth) so route handlers
# importing these can't drift from the redactor. If a new PHI field lands
# on ActionRecord, this is the one place to teach about it.
PHI_FIELDS_ACTION_RECORD_JSON: tuple[str, ...] = (
    "input_data",
    "metadata",
    # The ORM attribute is ``metadata_`` (trailing underscore because
    # ``metadata`` is reserved on SQLAlchemy's Base). The serialised
    # response uses ``metadata``. Cover both shapes so the redactor works
    # on either the raw ORM ``__dict__`` or the dumped response dict.
    "metadata_",
)
PHI_FIELDS_ACTION_RECORD_STRING: tuple[str, ...] = (
    "data_subject_id",
)
PHI_FIELDS_APPROVAL_CONTEXT: tuple[str, ...] = (
    "original_input_data",
)
# Approval rows have a top-level ``data_subject_id`` column too — used
# for ticket lookup, can contain PHI per the schema's max_length=500
# free-form field.
PHI_FIELDS_APPROVAL_STRING: tuple[str, ...] = (
    "data_subject_id",
)


_REDACTED_STRING = "[REDACTED]"


class IamTier(str, Enum):
    """Caller's tier — determines redaction + audit behaviour.

    * ``CUSTOMER``        — API-key holders and Clerk-authenticated humans
                            inside a customer org. Full access; no
                            audit-log write.
    * ``STAFF_READ_ONLY`` — Vera-internal Clerk users (org_role
                            ``vera_staff``). PHI redacted from every
                            response; every read writes a row to
                            ``staff_audit_log``. No writes allowed.
    * ``STAFF_FULL``      — Reserved for a future break-glass tier; not
                            instantiable in v1 (no codepath constructs
                            it). Listed so the enum is forward-compatible.
    """

    CUSTOMER = "customer"
    STAFF_READ_ONLY = "staff_read_only"
    STAFF_FULL = "staff_full"


def redact_action_record(record: dict, tier: IamTier) -> dict:
    """Return a copy of an ActionRecord-shaped dict with PHI fields
    redacted when ``tier`` is staff.

    * JSON-typed PHI fields → ``{}`` (downstream parsers (the dashboard,
      the SDK) expect dict, not string; replacing with ``"[REDACTED]"``
      would break ``record["input_data"]["foo"]`` access patterns).
    * String-typed PHI fields → ``"[REDACTED]"`` (a sentinel marker that
      is distinguishable from a legitimate ``None`` value).

    The input dict is NOT mutated; we shallow-copy and replace.
    """
    if tier == IamTier.CUSTOMER:
        return record
    out = dict(record)
    for field in PHI_FIELDS_ACTION_RECORD_JSON:
        if field in out:
            out[field] = {}
    for field in PHI_FIELDS_ACTION_RECORD_STRING:
        if field in out and out[field] is not None:
            out[field] = _REDACTED_STRING
    return out


def redact_approval(approval: dict, tier: IamTier) -> dict:
    """Return a copy of an Approval-shaped dict with PHI fields redacted.

    Strips ``context.original_input_data`` while keeping gate metadata
    (``gate_name``, ``required_role``, ``citation``, ``reason``,
    ``fix_url``, ``effect``) intact — staff need that to triage a
    customer ticket without seeing the payload.

    Also redacts the top-level ``data_subject_id`` string column.
    """
    if tier == IamTier.CUSTOMER:
        return approval
    out = dict(approval)
    # Context: shallow-copy, strip PHI keys, leave gate metadata.
    ctx = out.get("context")
    if isinstance(ctx, dict):
        new_ctx = {k: v for k, v in ctx.items() if k not in PHI_FIELDS_APPROVAL_CONTEXT}
        out["context"] = new_ctx
    for field in PHI_FIELDS_APPROVAL_STRING:
        if field in out and out[field] is not None:
            out[field] = _REDACTED_STRING
    return out


async def audit_staff_read(
    session: AsyncSession,  # noqa: ARG001 — kept for API symmetry; we use AsyncSessionLocal
    *,
    staff_id: str,
    endpoint: str,
    org_id: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    resource_count: Optional[int] = None,
    redacted: bool = True,
) -> None:
    """Append a staff-read row to ``staff_audit_log``.

    Per-request shape (Wave 3B.3 decision)
    --------------------------------------
    One row per HTTP request, not one row per record returned. The
    customer's threat model is "did Vera staff look at my data?" — they
    care about distinct staff requests, not pagination granularity. A
    staff GET ``/v1/actions?limit=200`` writes ONE row with
    ``resource_id=None`` and ``resource_count=N`` rather than 200 rows.

    Two canonical row shapes:
      * Single-record read   : ``resource_id`` set, ``resource_count``
                               NULL. The audit row pinpoints exactly
                               which record was read.
      * List read            : ``resource_id`` NULL, ``resource_count``
                               = N. The audit row tells the customer
                               "Vera staff saw the headers of N records
                               at time T" but not which specific records.

    Pre-3B.3 rows have ``resource_count`` NULL on list reads too. The
    customer-facing UI should treat NULL as "unknown count".

    Best-effort: any exception is logged and swallowed so a logging hiccup
    cannot 500 the user request. We commit on a NEW session so the
    caller's request transaction can roll back independently (a failed
    response should still leave the audit row in place — staff DID see
    the data even if the response transaction later rolled back).

    Why a new session, not BackgroundTasks: ``BackgroundTasks`` runs
    after the response is sent, which is fine — but it loses the
    AsyncSession bound to the request. We mirror the Wave 2B A3
    pattern (``services/webhooks.py``) of opening a fresh session via
    the module-level ``async_sessionmaker``-bound factory.

    Idempotency note: NOT idempotent. Every call writes a row. Two staff
    reads of the same record produce two rows — that's the intent
    ("this engineer accessed this record at 14:02 AND at 16:31").
    """
    try:
        # Use a fresh session via the module-level ``AsyncSessionLocal``
        # factory — the caller's request transaction may roll back, and
        # we want the audit row to persist regardless. This mirrors the
        # Wave 2B A3 webhook pattern (``services/webhooks.py``).
        #
        # Tests patch this module-level binding to the test engine's
        # session factory (see ``tests/conftest.py``); production reads
        # the real DB engine.
        async with AsyncSessionLocal() as audit_session:
            row = StaffAuditLog(
                staff_id=staff_id,
                endpoint=endpoint,
                org_id=org_id,
                resource_type=resource_type,
                resource_id=resource_id,
                resource_count=resource_count,
                redacted=redacted,
            )
            audit_session.add(row)
            await audit_session.commit()
    except Exception:
        # Defense-in-depth: NEVER let an audit-write failure 500 the
        # user response. Log + swallow. Operators can correlate via the
        # ``vera.iam`` logger if rows go missing.
        logger.exception(
            "audit_staff_read failed: staff_id=%s endpoint=%s org_id=%s "
            "resource_type=%s resource_id=%s resource_count=%s",
            staff_id,
            endpoint,
            org_id,
            resource_type,
            resource_id,
            resource_count,
        )


def tier_from_claims(claims: dict[str, Any], staff_org_id: Optional[str]) -> IamTier:
    """Resolve the caller's IAM tier from Clerk JWT claims.

    Staff escalation guard (Wave 3B.3 hardened):
      The JWT's ``org_id`` claim MUST match the configured
      ``staff_org_id`` for ANY staff tier. The match is trusted because
      Clerk signed the claim and we verified the issuer + audience +
      authorized-party allow-list upstream in ``verify_clerk_jwt``.

      Role-only matching (``org_role == "vera_staff"``) is intentionally
      disabled. A multi-tenant Clerk instance where a customer org
      happens to name a role ``vera_staff`` (or any string a staff-side
      role check might be written against) could otherwise mint a
      cross-tenant escalation by simply renaming a local role. The
      ``org_id`` claim is signed by Clerk's identity provider; the role
      name is operator-mutable per-org and so MUST NOT be the staff
      anchor.

    STAFF_FULL is reserved (v1):
      No codepath in this module returns ``IamTier.STAFF_FULL``. The
      enum value is kept so a future break-glass tier doesn't require
      re-rolling the Pydantic / response models, but in v1 only
      STAFF_READ_ONLY and CUSTOMER are materialised. Routes that defend
      against STAFF_FULL existing today must treat it as identical to
      STAFF_READ_ONLY (same redaction, same audit, same read-only
      surface) — see ``AuthContext.is_staff``.

    If ``staff_org_id`` is unset (development / customer-only
    deployments), the staff tier is unreachable — the function always
    returns CUSTOMER. API-key callers never reach this function; they're
    customers by construction.
    """
    if not staff_org_id:
        return IamTier.CUSTOMER
    clerk_org_id = claims.get("org_id")
    if clerk_org_id == staff_org_id:
        return IamTier.STAFF_READ_ONLY
    return IamTier.CUSTOMER
