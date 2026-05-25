"""Phase 2 Wave 2C PR A4 + Wave 2D PR A6 — review-callback schemas.

``ReviewCompletionInput`` is the body shape for
``POST /v1/reviews/{review_id}/complete`` (PR A4). The endpoint hands
the validated input to ``services.reviews.complete_review`` which
checks the reviewer-role hierarchy and then delegates to the existing
``services.approvals.decide_approval`` path so the chain record + dual
``approval.* / review.*`` webhook emission stay in lock-step with the
``POST /v1/approvals/{id}/decide`` shape.

``AttestationConflictResponse`` is the **flat error envelope** returned
when a second callback arrives for an already-resolved review with a
*different* decision than the canonical first attestation (PR A6 —
v1-implementation-plan.md §Phase 2, line 108). Matching second
callbacks are treated as idempotent and return the current
``ApprovalResponse`` instead.

``signature`` is accepted as a free-form string in Phase 2; cryptographic
verification lands in Phase 4+. Bounded length so a malicious caller
can't smuggle a multi-MB blob into the chain via the resolution record.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class ReviewCompletionInput(BaseModel):
    """Body for ``POST /v1/reviews/{review_id}/complete``.

    ``reviewer_role`` is matched against the ``required_role`` stashed in
    ``Approval.context`` (Wave 2B PR A2). Field constraints mirror the
    bounded-length conventions used by ``ApprovalDecision`` so an attacker
    can't smuggle PHI-sized blobs into the chain via the resolution
    record's ``reasoning`` field.
    """

    decision: Literal["approve", "reject"]
    reviewer_role: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description=(
            "The role the reviewer claims. Compared to required_role via "
            "services.reviewer_roles.is_role_sufficient — unknown strings "
            "fail-closed."
        ),
    )
    reviewer_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description=(
            "Human identifier of the reviewer (email, employee ID, etc.). "
            "Distinct from reviewer_role so a single reviewer can act "
            "under different role hats."
        ),
    )
    note: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Human-readable rationale, surfaced on the resolution chain record.",
    )
    signature: Optional[str] = Field(
        default=None,
        max_length=512,
        description=(
            "Cryptographic attestation. Phase 2 accepts the value as-is; "
            "verification ships in Phase 4+."
        ),
    )


class AttestationConflictResponse(BaseModel):
    """Phase 2 Wave 2D PR A6 — 409 envelope for attestation conflicts.

    Emitted by ``POST /v1/reviews/{review_id}/complete`` when the second
    callback for a resolved review carries a *different* decision than
    the first attestation. Per v1-implementation-plan.md §Phase 2
    line 108, the canonical decision stays the first attestation; the
    conflict is logged as a chain ``ActionRecord`` and dispatched as an
    ``attestation_conflict`` webhook event (event type pre-registered by
    PR A3).

    Shape mirrors the flat-error envelope used by PR A4's 403
    ``reviewer_credentials_insufficient`` path so the SDK's
    ``wrap_httpx_error`` contract stays consistent: top-level ``code``
    plus context fields, no nested ``detail`` blob to parse.
    """

    code: Literal["attestation_conflict"] = "attestation_conflict"
    review_id: str
    canonical_decision: Literal["approve", "reject"]
    conflicting_decision: Literal["approve", "reject"]
    detail: Optional[str] = Field(
        default=None,
        description=(
            "Human-readable explanation, suitable for logging. The "
            "structured fields above are the contract — ``detail`` is "
            "for operator UIs only."
        ),
    )


__all__ = ["AttestationConflictResponse", "ReviewCompletionInput"]
