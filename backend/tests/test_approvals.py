"""Tests for the Human-in-the-Loop approval workflow.

Covers:
1. Service: request_approval creates a pending ActionRecord in the chain
2. Service: approve decision writes a resolution record and signs the vote
3. Service: reject decision terminates immediately
4. Service: dual-verification — single vote with approvers_required=2 stays pending
5. Service: same approver can't vote twice
6. Service: cancel writes a resolution record and marks cancelled
7. Service: lazy expiration on read
8. Service: cross-org isolation (404)
9. API: POST /v1/approvals creates pending, links to chain record
10. API: GET /v1/approvals lists + filters (status, risk_tier, data_subject_id)
11. API: GET /v1/approvals/{id} returns current status
12. API: POST /v1/approvals/{id}/decide requires admin permission
13. API: POST /v1/approvals/{id}/cancel writes resolution record
14. API: 404 for cross-org approval access
15. API: 409 for already-resolved approval
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import Approval, ActionRecord, Organization, ChainState
from app.schemas.approval import ApprovalCreate, ApprovalDecision
from app.services.approvals import (
    cancel_approval,
    decide_approval,
    get_approval_with_lazy_expiry,
    request_approval,
)
from app.services.auth import generate_api_key


def _make_request(**kwargs) -> ApprovalCreate:
    defaults = dict(
        agent_name="loan-agent",
        action_name="approve_loan",
        action_summary="Approve $500k mortgage for applicant",
        data_subject_id="user_sarah_chen",
        context={"amount": 500_000, "applicant_id": "user_sarah_chen"},
        risk_tier="high",
        approvers_required=1,
    )
    defaults.update(kwargs)
    return ApprovalCreate(**defaults)


# ── Service-level tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_approval_creates_pending_chain_record(db_session, org_and_key):
    """Requesting approval writes a pending ActionRecord and links it to the approval."""
    org, _, _ = org_and_key

    approval = await request_approval(db_session, org.id, _make_request())

    assert approval.status == "pending"
    assert approval.request_record_id is not None
    assert approval.resolution_record_id is None

    record = await db_session.get(ActionRecord, approval.request_record_id)
    assert record is not None
    assert record.action_type == "human_approval_requested"
    assert record.result == "pending"
    assert record.data_subject_id == "user_sarah_chen"
    assert record.reasoning["risk_tier"] == "high"


@pytest.mark.asyncio
async def test_approve_decision_resolves_and_signs(db_session, org_and_key):
    """A single approve vote (approvers_required=1) resolves to approved and writes resolution record."""
    org, _, _ = org_and_key
    approval = await request_approval(db_session, org.id, _make_request())

    decision = ApprovalDecision(decision="approve", approver="alice@example.com", note="LGTM")
    resolved = await decide_approval(db_session, org.id, approval.id, decision)

    assert resolved.status == "approved"
    assert resolved.resolved_at is not None
    assert resolved.resolution_record_id is not None
    assert len(resolved.decisions) == 1
    assert resolved.decisions[0]["approver"] == "alice@example.com"
    assert resolved.decisions[0]["decision"] == "approve"
    assert resolved.decisions[0]["signature"]  # non-empty
    assert resolved.decisions[0]["key_id"]

    # Resolution record is in the chain
    record = await db_session.get(ActionRecord, resolved.resolution_record_id)
    assert record is not None
    assert record.action_type == "human_approval_resolved"
    assert record.result == "success"
    assert record.reasoning["final_status"] == "approved"


@pytest.mark.asyncio
async def test_reject_decision_terminates_immediately(db_session, org_and_key):
    """A single reject vote terminates regardless of approvers_required."""
    org, _, _ = org_and_key
    approval = await request_approval(
        db_session, org.id, _make_request(approvers_required=2)
    )

    decision = ApprovalDecision(decision="reject", approver="bob@example.com", note="Too risky")
    resolved = await decide_approval(db_session, org.id, approval.id, decision)

    assert resolved.status == "rejected"
    assert resolved.resolution_record_id is not None
    record = await db_session.get(ActionRecord, resolved.resolution_record_id)
    assert record.result == "failure"
    assert record.reasoning["final_status"] == "rejected"


@pytest.mark.asyncio
async def test_dual_verification_needs_both_approvers(db_session, org_and_key):
    """With approvers_required=2, one approve vote stays pending; second resolves it."""
    org, _, _ = org_and_key
    approval = await request_approval(
        db_session, org.id, _make_request(approvers_required=2)
    )

    first = await decide_approval(
        db_session,
        org.id,
        approval.id,
        ApprovalDecision(decision="approve", approver="alice@example.com"),
    )
    assert first.status == "pending"
    assert first.resolution_record_id is None
    assert len(first.decisions) == 1

    second = await decide_approval(
        db_session,
        org.id,
        approval.id,
        ApprovalDecision(decision="approve", approver="bob@example.com"),
    )
    assert second.status == "approved"
    assert second.resolution_record_id is not None
    assert len(second.decisions) == 2


@pytest.mark.asyncio
async def test_same_approver_cannot_vote_twice(db_session, org_and_key):
    """EU AI Act dual-verification requires DIFFERENT natural persons."""
    from fastapi import HTTPException

    org, _, _ = org_and_key
    approval = await request_approval(
        db_session, org.id, _make_request(approvers_required=2)
    )

    await decide_approval(
        db_session,
        org.id,
        approval.id,
        ApprovalDecision(decision="approve", approver="alice@example.com"),
    )
    with pytest.raises(HTTPException) as exc:
        await decide_approval(
            db_session,
            org.id,
            approval.id,
            ApprovalDecision(decision="approve", approver="alice@example.com"),
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_cancel_writes_resolution_record(db_session, org_and_key):
    """Cancelling a pending approval writes a cancellation record to the chain."""
    org, _, _ = org_and_key
    approval = await request_approval(db_session, org.id, _make_request())

    cancelled = await cancel_approval(db_session, org.id, approval.id, canceller="admin")
    assert cancelled.status == "cancelled"
    assert cancelled.resolution_record_id is not None

    record = await db_session.get(ActionRecord, cancelled.resolution_record_id)
    assert record.reasoning["final_status"] == "cancelled"
    assert record.reasoning["cancelled_by"] == "admin"


@pytest.mark.asyncio
async def test_lazy_expiration_on_read(db_session, org_and_key):
    """Reading a pending approval past its deadline marks it expired."""
    org, _, _ = org_and_key
    approval = await request_approval(
        db_session, org.id, _make_request(expires_in_seconds=1)
    )

    # Force expiration by rewriting the deadline to the past
    approval.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    await db_session.commit()

    expired = await get_approval_with_lazy_expiry(db_session, org.id, approval.id)
    assert expired.status == "expired"
    assert expired.resolution_record_id is not None


@pytest.mark.asyncio
async def test_decide_on_resolved_approval_conflicts(db_session, org_and_key):
    """Voting on an already-resolved approval returns 409."""
    from fastapi import HTTPException

    org, _, _ = org_and_key
    approval = await request_approval(db_session, org.id, _make_request())
    await decide_approval(
        db_session,
        org.id,
        approval.id,
        ApprovalDecision(decision="approve", approver="alice@example.com"),
    )

    with pytest.raises(HTTPException) as exc:
        await decide_approval(
            db_session,
            org.id,
            approval.id,
            ApprovalDecision(decision="approve", approver="bob@example.com"),
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_cross_org_access_returns_404(db_session, org_and_key):
    """Org A cannot access or decide on Org B's approval."""
    from fastapi import HTTPException

    org_a, _, _ = org_and_key
    approval = await request_approval(db_session, org_a.id, _make_request())

    # Create a second org
    org_b = Organization(name="other-org")
    db_session.add(org_b)
    await db_session.flush()
    db_session.add(ChainState(org_id=org_b.id))
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await get_approval_with_lazy_expiry(db_session, org_b.id, approval.id)
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        await decide_approval(
            db_session,
            org_b.id,
            approval.id,
            ApprovalDecision(decision="approve", approver="mallory@evil.com"),
        )
    assert exc.value.status_code == 404


# ── API-level tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_create_approval(async_client, org_and_key):
    """POST /v1/approvals creates a pending approval."""
    _, raw_key, _ = org_and_key
    response = await async_client.post(
        "/v1/approvals",
        json={
            "agent_name": "loan-agent",
            "action_name": "approve_loan",
            "context": {"amount": 500_000},
            "risk_tier": "high",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["request_record_id"]
    assert body["resolution_record_id"] is None


@pytest.mark.asyncio
async def test_api_list_approvals_filters(async_client, org_and_key):
    """GET /v1/approvals supports status / risk_tier / data_subject_id filters."""
    _, raw_key, _ = org_and_key
    headers = {"Authorization": f"Bearer {raw_key}"}

    # Create three approvals with different shapes
    for risk, subject in [("high", "user_a"), ("critical", "user_a"), ("low", "user_b")]:
        await async_client.post(
            "/v1/approvals",
            json={
                "agent_name": "agent",
                "action_name": "x",
                "risk_tier": risk,
                "data_subject_id": subject,
                "context": {},
            },
            headers=headers,
        )

    r = await async_client.get("/v1/approvals?risk_tier=high", headers=headers)
    assert r.status_code == 200
    assert r.json()["total"] == 1

    r = await async_client.get("/v1/approvals?data_subject_id=user_a", headers=headers)
    assert r.status_code == 200
    assert r.json()["total"] == 2

    r = await async_client.get("/v1/approvals?status=pending", headers=headers)
    assert r.json()["total"] == 3


@pytest.mark.asyncio
async def test_api_decide_approval_happy_path(async_client, org_and_key):
    """POST /v1/approvals/{id}/decide approves and resolves."""
    _, raw_key, _ = org_and_key
    headers = {"Authorization": f"Bearer {raw_key}"}

    create_r = await async_client.post(
        "/v1/approvals",
        json={"agent_name": "a", "action_name": "x", "context": {}},
        headers=headers,
    )
    approval_id = create_r.json()["id"]

    decide_r = await async_client.post(
        f"/v1/approvals/{approval_id}/decide",
        json={"decision": "approve", "approver": "alice@example.com"},
        headers=headers,
    )
    assert decide_r.status_code == 200
    body = decide_r.json()
    assert body["status"] == "approved"
    assert body["resolution_record_id"]
    assert body["decisions"][0]["signature"]


@pytest.mark.asyncio
async def test_api_decide_requires_admin(async_client, org_and_key, db_session):
    """Decide endpoint rejects non-admin keys."""
    org, raw_admin, _ = org_and_key
    headers_admin = {"Authorization": f"Bearer {raw_admin}"}

    create_r = await async_client.post(
        "/v1/approvals",
        json={"agent_name": "a", "action_name": "x", "context": {}},
        headers=headers_admin,
    )
    approval_id = create_r.json()["id"]

    # Make a write-only key for the same org
    raw_write, _ = await generate_api_key(
        db_session, org.id, "writer-key", ["read", "write"]
    )
    headers_write = {"Authorization": f"Bearer {raw_write}"}

    r = await async_client.post(
        f"/v1/approvals/{approval_id}/decide",
        json={"decision": "approve", "approver": "bob"},
        headers=headers_write,
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_api_cancel_approval(async_client, org_and_key):
    """POST /v1/approvals/{id}/cancel marks it cancelled and writes chain record."""
    _, raw_key, _ = org_and_key
    headers = {"Authorization": f"Bearer {raw_key}"}

    create_r = await async_client.post(
        "/v1/approvals",
        json={"agent_name": "a", "action_name": "x", "context": {}},
        headers=headers,
    )
    approval_id = create_r.json()["id"]

    r = await async_client.post(
        f"/v1/approvals/{approval_id}/cancel", headers=headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "cancelled"
    assert body["resolution_record_id"]


@pytest.mark.asyncio
async def test_api_decide_already_resolved_returns_409(async_client, org_and_key):
    """Voting twice on a resolved approval returns 409."""
    _, raw_key, _ = org_and_key
    headers = {"Authorization": f"Bearer {raw_key}"}

    create_r = await async_client.post(
        "/v1/approvals",
        json={"agent_name": "a", "action_name": "x", "context": {}},
        headers=headers,
    )
    approval_id = create_r.json()["id"]

    await async_client.post(
        f"/v1/approvals/{approval_id}/decide",
        json={"decision": "approve", "approver": "alice"},
        headers=headers,
    )
    r = await async_client.post(
        f"/v1/approvals/{approval_id}/decide",
        json={"decision": "approve", "approver": "bob"},
        headers=headers,
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_api_get_approval_status(async_client, org_and_key):
    """GET /v1/approvals/{id} returns current status."""
    _, raw_key, _ = org_and_key
    headers = {"Authorization": f"Bearer {raw_key}"}

    create_r = await async_client.post(
        "/v1/approvals",
        json={"agent_name": "a", "action_name": "x", "context": {}},
        headers=headers,
    )
    approval_id = create_r.json()["id"]

    r = await async_client.get(f"/v1/approvals/{approval_id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "pending"
    assert r.json()["id"] == approval_id
