"""Wave 2D PR A6.5 — atomic approval transaction tests.

Verifies the vote write + terminal status write + chain resolution
record write either all commit together or all roll back together.
Closes the Codex /review finding from A6 #224: the previous shape
committed the vote inside ``decide_approval`` BEFORE
``_resolve_and_record`` ran, which released the
``SELECT … FOR UPDATE`` lock that ``services/reviews.py``'s
``complete_review`` was holding and let a concurrent caller observe
a vote-committed-but-status-still-pending intermediate state.

Coverage:
* Chain-write failure rolls back the vote AND leaves no chain record.
* Status-write failure (simulated via chain-write failure since the
  chain write is the only thing between vote append and status flip
  inside ``_resolve_and_record``) leaves no partial state.
* Happy path: vote + status + resolution chain record are ALL visible
  after the single outer commit.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models import ActionRecord, Approval
from app.schemas.approval import ApprovalCreate, ApprovalDecision
from app.services.approvals import decide_approval, request_approval


async def _seed_pending_approval(
    db_session, org_id: str, *, approvers_required: int = 1
) -> Approval:
    """Materialise a pending single-vote approval for an org."""
    create = ApprovalCreate(
        agent_name="scribemd",
        action_name="add_diagnosis",
        action_summary="Add diagnosis E11.9 for patient_42",
        data_subject_id="patient_42",
        context={
            "gate_name": "new_diagnosis_requires_attending",
            "required_role": "attending_physician",
            "citation": "42 CFR 482.24(c)(4)(viii)",
            "reason": "new_diagnosis_proposed",
        },
        risk_tier="high",
        approvers_required=approvers_required,
    )
    return await request_approval(db_session, org_id, create)


@pytest.mark.asyncio
async def test_chain_write_failure_rolls_back_vote_and_status(
    db_session, org_and_key
):
    """If the resolution chain-record write raises, the vote MUST NOT persist.

    Mocks ``build_and_insert_record`` (the chain-write entry point) to
    raise on the second call — the first call is the ``request_approval``
    pending record that already committed during seeding, the second
    call is the resolution record inside ``_resolve_and_record``. The
    raise should leave the approval row's vote AND status untouched.
    """
    org, _, _ = org_and_key
    approval = await _seed_pending_approval(db_session, org.id)
    # Snapshot identifiers up-front. ``rollback()`` below expires the
    # ORM-attached ``approval`` object so any subsequent attribute
    # access would trigger a lazy reload (sync greenlet boundary).
    approval_id = approval.id
    org_id = org.id
    initial_decisions = list(approval.decisions)
    initial_status = approval.status
    assert initial_status == "pending"
    assert initial_decisions == []

    pre_chain_count = len(
        (
            await db_session.execute(
                select(ActionRecord).where(ActionRecord.org_id == org_id)
            )
        )
        .scalars()
        .all()
    )

    # Patch the chain-write entry point AS IMPORTED INTO approvals.py
    # so the failure fires inside ``_resolve_and_record`` only. Use
    # ``AsyncMock`` so the mock is awaitable (the real function is
    # async — a plain Mock with ``side_effect`` raises synchronously
    # before the await, tripping greenlet boundary checks).
    failing = AsyncMock(side_effect=RuntimeError("simulated chain write failure"))
    with patch(
        "app.services.approvals.build_and_insert_record",
        failing,
    ):
        with pytest.raises(RuntimeError, match="simulated chain write failure"):
            await decide_approval(
                db_session,
                org_id=org_id,
                approval_id=approval_id,
                decision=ApprovalDecision(
                    decision="approve",
                    approver="dr_smith:attending_physician",
                    note="should not persist",
                    # W1.1: gated approval (context.required_role
                    # set in _seed_pending_approval) now requires
                    # reviewer_role on the decide call.
                    reviewer_role="attending_physician",
                ),
            )

    # Roll back the failed transaction so we can read clean DB state.
    await db_session.rollback()

    # Re-read from DB. The vote must NOT be visible.
    refreshed = (
        await db_session.execute(
            select(Approval).where(Approval.id == approval_id)
        )
    ).scalar_one()
    assert refreshed.decisions == initial_decisions, (
        "vote leaked on failed chain write — atomicity broken"
    )
    assert refreshed.status == initial_status, (
        "status flipped on failed chain write — atomicity broken"
    )
    assert refreshed.resolution_record_id is None, (
        "resolution_record_id set despite chain write failure"
    )

    post_chain_count = len(
        (
            await db_session.execute(
                select(ActionRecord).where(ActionRecord.org_id == org_id)
            )
        )
        .scalars()
        .all()
    )
    assert post_chain_count == pre_chain_count, (
        f"chain record leaked: pre={pre_chain_count} post={post_chain_count}"
    )


@pytest.mark.asyncio
async def test_resolve_failure_after_chain_write_rolls_back_vote(
    db_session, org_and_key
):
    """If ``_resolve_and_record`` raises AFTER the chain write succeeds,
    the vote, the chain record, AND the status flip all roll back.

    This is the strongest atomicity assertion: it proves that even when
    the failure happens BETWEEN sub-writes inside ``_resolve_and_record``
    (chain-record write succeeded, status flush hasn't committed yet),
    rolling back the outer transaction wipes everything together — so
    no caller in a sibling process can ever observe the half-resolved
    state that A6 #224 flagged.
    """
    org, _, _ = org_and_key
    approval = await _seed_pending_approval(db_session, org.id)
    approval_id = approval.id
    org_id = org.id
    initial_decisions = list(approval.decisions)

    # Wrap ``_resolve_and_record`` so the real function runs (writing
    # the chain record + assigning the status field on the in-memory
    # Approval) but then raises before the outer commit lands.
    from app.services import approvals as approvals_module

    real_resolve = approvals_module._resolve_and_record

    async def crashing_resolve(*args, **kwargs):
        await real_resolve(*args, **kwargs)
        raise RuntimeError("simulated resolve failure after chain write")

    with patch.object(
        approvals_module, "_resolve_and_record", side_effect=crashing_resolve
    ):
        with pytest.raises(
            RuntimeError, match="simulated resolve failure after chain write"
        ):
            await decide_approval(
                db_session,
                org_id=org_id,
                approval_id=approval_id,
                decision=ApprovalDecision(
                    decision="approve",
                    approver="dr_smith:attending_physician",
                    # W1.1: gated approval requires reviewer_role.
                    reviewer_role="attending_physician",
                ),
            )

    # The exception aborts the outer ``await session.commit()`` in
    # ``decide_approval`` — so the uncommitted writes (vote + chain
    # record + status flip) must be discarded by rollback.
    await db_session.rollback()

    refreshed = (
        await db_session.execute(
            select(Approval).where(Approval.id == approval_id)
        )
    ).scalar_one()
    assert refreshed.decisions == initial_decisions, (
        "vote leaked after resolve raised"
    )
    assert refreshed.status == "pending", (
        "status flipped despite resolve raising"
    )
    assert refreshed.resolution_record_id is None, (
        "resolution_record_id set despite resolve raising"
    )

    # The chain record written inside the SAVEPOINT must also be gone.
    resolution_chain_rows = (
        await db_session.execute(
            select(ActionRecord)
            .where(ActionRecord.org_id == org_id)
            .where(ActionRecord.action_type == "human_approval_resolved")
        )
    ).scalars().all()
    assert resolution_chain_rows == [], (
        "resolution chain record leaked despite rollback"
    )


@pytest.mark.asyncio
async def test_happy_path_vote_status_and_chain_record_all_commit(
    db_session, org_and_key
):
    """Vote + terminal status + resolution chain record all land atomically."""
    org, _, _ = org_and_key
    approval = await _seed_pending_approval(db_session, org.id)
    assert approval.status == "pending"

    pre_resolved_chain = len(
        (
            await db_session.execute(
                select(ActionRecord)
                .where(ActionRecord.org_id == org.id)
                .where(ActionRecord.action_type == "human_approval_resolved")
            )
        )
        .scalars()
        .all()
    )

    resolved = await decide_approval(
        db_session,
        org_id=org.id,
        approval_id=approval.id,
        decision=ApprovalDecision(
            decision="approve",
            approver="dr_smith:attending_physician",
            # W1.1: gated approval requires reviewer_role.
            reviewer_role="attending_physician",
        ),
    )

    # All three writes visible after the single outer commit.
    assert resolved.status == "approved"
    assert len(resolved.decisions) == 1
    assert resolved.decisions[0]["decision"] == "approve"
    assert resolved.decisions[0]["approver"] == "dr_smith:attending_physician"
    assert resolved.decisions[0]["signature"]  # KMS sig present
    assert resolved.resolution_record_id is not None

    # Re-read from DB to confirm durability (not just in-memory state).
    refreshed = (
        await db_session.execute(
            select(Approval).where(Approval.id == approval.id)
        )
    ).scalar_one()
    assert refreshed.status == "approved"
    assert len(refreshed.decisions) == 1

    # The resolution chain record exists and is linked.
    chain_rows = (
        await db_session.execute(
            select(ActionRecord)
            .where(ActionRecord.org_id == org.id)
            .where(ActionRecord.action_type == "human_approval_resolved")
        )
    ).scalars().all()
    assert len(chain_rows) == pre_resolved_chain + 1
    resolution = next(
        r for r in chain_rows if r.id == refreshed.resolution_record_id
    )
    assert resolution.result == "success"
    assert resolution.reasoning["final_status"] == "approved"
