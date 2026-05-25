"""Phase 2 Wave 2C PR A4 — reviewer completion input schema.

Body shape for ``POST /v1/reviews/{review_id}/complete``. The endpoint
hands the validated input to ``services.reviews.complete_review`` which
checks the reviewer-role hierarchy and then delegates to the existing
``services.approvals.decide_approval`` path so the chain record + dual
``approval.* / review.*`` webhook emission stay in lock-step with the
``POST /v1/approvals/{id}/decide`` shape.

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


__all__ = ["ReviewCompletionInput"]
