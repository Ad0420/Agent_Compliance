"""Phase 2 Wave 2D follow-up W1.1 — reviewer-role enforcement on the legacy
``POST /v1/approvals/{id}/decide`` endpoint.

Closes phase2-acceptance-findings:
* ``legacy-decide-no-role-enforcement`` (Critical) — wrong role on a
  DEA-gated approval used to return 200 with the role check ignored.
* ``require_permission-admin-too-strict-on-decide`` (Medium) — endpoint
  no longer requires admin keys, write is enough (the role check is now
  the security boundary).

Coverage mirrors ``test_reviews_complete.py``'s structure so the two
endpoints stay in lock-step.

What's tested:
* 200: gated approval + matching reviewer_role + admin key.
* 200: gated approval + higher-than-required reviewer_role.
* 200: un-gated approval (no ``context.required_role``) + omitted
  reviewer_role (legacy passthrough preserved).
* 200: write-only key (no admin) + correct role (proves auth relaxation).
* 403: gated approval + insufficient reviewer_role — structured envelope,
  approval stays pending, ``reviewed_below_threshold=True``, chain record
  with ``action_type='reviewer_credentials_insufficient'`` written.
* 403: gated approval + unknown reviewer_role string (fail-closed).
* 400: gated approval + omitted reviewer_role → ``reviewer_role_required``.
* 404: nonexistent approval id.
* 4xx: no auth header.
* 409: second decide caller after resolution (A6.5 atomicity preserved).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models import ActionRecord, Approval
from app.schemas.approval import ApprovalCreate
from app.services.approvals import request_approval
from app.services.auth import generate_api_key


def _now_naive_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _seed_gated_approval(
    db_session,
    org_id: str,
    *,
    required_role: str | None = "dea_authorized",
    gate_name: str = "controlled_substance_requires_dea",
    citation: str = "21 CFR 1306.04",
) -> Approval:
    """Materialise an Approval shaped like Wave 2B PR A2 would create.

    Mirrors the seed helper in ``test_reviews_complete.py`` so the two
    endpoint test suites exercise the same fixture surface.
    """
    create = ApprovalCreate(
        agent_name="scribemd",
        action_name="prescribe_medication",
        action_summary="Order oxycodone 5mg for patient_42",
        data_subject_id="patient_42",
        context={
            "gate_name": gate_name,
            "required_role": required_role,
            "citation": citation,
            "reason": "controlled_substance_proposed",
            "original_input_data": {"medication": "oxycodone"},
        },
        risk_tier="critical",
        approvers_required=1,
    )
    return await request_approval(db_session, org_id, create)


async def _seed_ungated_approval(db_session, org_id: str) -> Approval:
    """Approval without ``required_role`` — legacy Phase 1 shape."""
    create = ApprovalCreate(
        agent_name="loan-agent",
        action_name="approve_loan",
        action_summary="Approve $500k mortgage",
        data_subject_id="user_sarah_chen",
        context={"amount": 500_000},  # NO required_role
        risk_tier="high",
        approvers_required=1,
    )
    return await request_approval(db_session, org_id, create)


# ── 200: happy paths ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decide_gated_matching_role_with_admin_key_approves(
    async_client, org_and_key, db_session
):
    """200: gated approval + reviewer_role matches required_role exactly +
    admin key → approved, ``reviewed_below_threshold`` stays False."""
    org, raw_key, _ = org_and_key
    approval = await _seed_gated_approval(db_session, org.id)

    response = await async_client.post(
        f"/v1/approvals/{approval.id}/decide",
        json={
            "decision": "approve",
            "approver": "dr_smith@hospital.example",
            "reviewer_role": "dea_authorized",
            "note": "DEA registration on file.",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "approved"
    assert body["resolution_record_id"]
    assert body["reviewed_below_threshold"] is False
    assert len(body["decisions"]) == 1
    assert body["decisions"][0]["decision"] == "approve"
    assert body["decisions"][0]["signature"]


@pytest.mark.asyncio
async def test_decide_gated_higher_role_satisfies_lower_requirement(
    async_client, org_and_key, db_session
):
    """200: medical_director (level 50) satisfies dea_authorized (level 40).

    Mirrors A4's hierarchy semantics — higher-level roles automatically
    satisfy lower-level requirements.
    """
    org, raw_key, _ = org_and_key
    approval = await _seed_gated_approval(db_session, org.id)

    response = await async_client.post(
        f"/v1/approvals/{approval.id}/decide",
        json={
            "decision": "approve",
            "approver": "mdir_jones",
            "reviewer_role": "medical_director",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_decide_ungated_approval_without_reviewer_role_passes(
    async_client, org_and_key, db_session
):
    """200: legacy un-gated approval + no reviewer_role → approved.

    This is the backward-compat contract: Phase 1 callers (and any
    approval that doesn't carry ``context.required_role``) MUST keep
    working with the pre-W1.1 ``ApprovalDecision`` shape.
    """
    org, raw_key, _ = org_and_key
    approval = await _seed_ungated_approval(db_session, org.id)

    response = await async_client.post(
        f"/v1/approvals/{approval.id}/decide",
        json={"decision": "approve", "approver": "alice@example.com"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "approved"
    assert body["reviewed_below_threshold"] is False


@pytest.mark.asyncio
async def test_decide_ungated_approval_with_reviewer_role_still_passes(
    async_client, org_and_key, db_session
):
    """200: un-gated approval + reviewer_role supplied → still approved.

    The reviewer_role field is ignored when there's no required_role to
    compare against. Defends against breaking callers that supply
    reviewer_role on every call defensively.
    """
    org, raw_key, _ = org_and_key
    approval = await _seed_ungated_approval(db_session, org.id)

    response = await async_client.post(
        f"/v1/approvals/{approval.id}/decide",
        json={
            "decision": "approve",
            "approver": "alice@example.com",
            "reviewer_role": "attending_physician",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_decide_with_write_only_key_succeeds_post_w1_1(
    async_client, org_and_key, db_session
):
    """200: write-only key (no admin) + correct role → approved.

    Proves the route-level permission was relaxed from admin → write per
    W1.1 (phase2-acceptance-findings
    ``require_permission-admin-too-strict-on-decide``). Real reviewers
    should never need admin keys to register a decision.
    """
    org, _raw_admin, _ = org_and_key
    approval = await _seed_gated_approval(db_session, org.id)

    raw_write, _ = await generate_api_key(
        db_session, org.id, "writer-key", ["read", "write"]
    )

    response = await async_client.post(
        f"/v1/approvals/{approval.id}/decide",
        json={
            "decision": "approve",
            "approver": "dr_smith",
            "reviewer_role": "dea_authorized",
        },
        headers={"Authorization": f"Bearer {raw_write}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"


# ── 403: insufficient role ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decide_gated_wrong_role_returns_403_flat_envelope(
    async_client, org_and_key, db_session
):
    """403: physician (20) cannot satisfy dea_authorized (40).

    Verifies the load-bearing requirement: chain record written +
    ``reviewed_below_threshold=True`` flipped, approval stays pending,
    flat error envelope returned with all the structured context fields
    the dashboard / SDK consume.
    """
    org, raw_key, _ = org_and_key
    approval = await _seed_gated_approval(db_session, org.id)

    response = await async_client.post(
        f"/v1/approvals/{approval.id}/decide",
        json={
            "decision": "approve",
            "approver": "dr_phys",
            "reviewer_role": "physician",
            "note": "I'll vouch for it.",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    assert response.status_code == 403, response.text
    body = response.json()
    # Flat envelope — matches A4's shape exactly.
    assert body["code"] == "reviewer_credentials_insufficient"
    assert body["required_role"] == "dea_authorized"
    assert body["reviewer_role"] == "physician"
    assert body["review_id"] == approval.id
    assert "does not satisfy" in body["detail"]

    # Load-bearing flag flipped, approval stays pending so a higher-role
    # reviewer can still resolve it.
    refreshed = await db_session.get(Approval, approval.id)
    await db_session.refresh(refreshed)
    assert refreshed.reviewed_below_threshold is True
    assert refreshed.status == "pending"
    assert refreshed.resolution_record_id is None

    # Chain record written for the audit trail.
    rows = (
        await db_session.execute(
            select(ActionRecord).where(
                ActionRecord.org_id == org.id,
                ActionRecord.action_type == "reviewer_credentials_insufficient",
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    rec = rows[0]
    assert rec.result == "failure"
    assert rec.reasoning["required_role"] == "dea_authorized"
    assert rec.reasoning["reviewer_role"] == "physician"
    assert rec.reasoning["reviewer_id"] == "dr_phys"
    assert rec.reasoning["gate_name"] == "controlled_substance_requires_dea"
    assert rec.reasoning["attempted_decision"] == "approve"
    # Endpoint marker distinguishes this from A4's complete_review path
    # for audit-PDF rendering.
    assert rec.reasoning["endpoint"] == "legacy_decide"


@pytest.mark.asyncio
async def test_decide_gated_unknown_role_fails_closed(
    async_client, org_and_key, db_session
):
    """403: unrecognised role string fails closed (typo defence).

    A4's ``is_role_sufficient`` returns False for any role not in
    ``_ROLE_LEVELS`` — defends against ``attendng_physician`` (typo)
    silently clearing a gate.
    """
    org, raw_key, _ = org_and_key
    approval = await _seed_gated_approval(db_session, org.id)

    response = await async_client.post(
        f"/v1/approvals/{approval.id}/decide",
        json={
            "decision": "approve",
            "approver": "dr_smith",
            "reviewer_role": "dea_authorzed",  # typo
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 403, response.text
    refreshed = await db_session.get(Approval, approval.id)
    await db_session.refresh(refreshed)
    assert refreshed.reviewed_below_threshold is True


# ── 422: empty-string reviewer_role rejected at schema boundary ────────────


@pytest.mark.asyncio
async def test_decide_empty_reviewer_role_returns_422(
    async_client, org_and_key, db_session
):
    """422: empty-string reviewer_role rejected by Pydantic min_length=1.

    Mirrors A4's ReviewCompletionInput.reviewer_role contract — empty
    strings shouldn't reach the service-layer fail-closed branch where
    they'd otherwise produce a 403. The 422 keeps the validation
    surface aligned across the two endpoints so a single human acting
    through either endpoint sees the same rejection.
    """
    org, raw_key, _ = org_and_key
    approval = await _seed_gated_approval(db_session, org.id)

    response = await async_client.post(
        f"/v1/approvals/{approval.id}/decide",
        json={
            "decision": "approve",
            "approver": "dr_smith",
            "reviewer_role": "",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 422, response.text


# ── 400: missing reviewer_role on a gated approval ─────────────────────────


@pytest.mark.asyncio
async def test_decide_gated_omitted_role_returns_400_reviewer_role_required(
    async_client, org_and_key, db_session
):
    """400: gated approval + no reviewer_role → ``reviewer_role_required``.

    Backward-compat callers who never sent the field used to slip through
    silently (the legacy-decide-no-role-enforcement bug). We now surface
    the requirement explicitly so they can't approve a gated review by
    accident. 400 because the request shape is the problem, not the
    reviewer's credentials.
    """
    org, raw_key, _ = org_and_key
    approval = await _seed_gated_approval(db_session, org.id)

    response = await async_client.post(
        f"/v1/approvals/{approval.id}/decide",
        json={"decision": "approve", "approver": "dr_smith"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    assert response.status_code == 400, response.text
    body = response.json()
    assert body["code"] == "reviewer_role_required"
    assert body["required_role"] == "dea_authorized"
    assert body["review_id"] == approval.id

    # No chain record written and the flag stays clean — this is a
    # request-shape rejection, not a below-threshold attempt.
    refreshed = await db_session.get(Approval, approval.id)
    await db_session.refresh(refreshed)
    assert refreshed.reviewed_below_threshold is False
    assert refreshed.status == "pending"
    rows = (
        await db_session.execute(
            select(ActionRecord).where(
                ActionRecord.org_id == org.id,
                ActionRecord.action_type == "reviewer_credentials_insufficient",
            )
        )
    ).scalars().all()
    assert len(rows) == 0


# ── 404 / auth ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decide_unknown_approval_returns_404(async_client, org_and_key):
    """404: nonexistent approval id — auth header still valid."""
    _, raw_key, _ = org_and_key
    response = await async_client.post(
        "/v1/approvals/00000000-0000-0000-0000-000000000000/decide",
        json={
            "decision": "approve",
            "approver": "dr_smith",
            "reviewer_role": "attending_physician",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_decide_no_auth_header_is_rejected(
    async_client, org_and_key, db_session
):
    """4xx: missing Authorization header is rejected BEFORE the role check.

    FastAPI's ``HTTPBearer`` returns 403 (not 401) for missing schemes —
    the project's auth layer keeps that contract. The contract this test
    pins is that an unauthenticated caller never gets to the
    role-enforcement branch.
    """
    org, _, _ = org_and_key
    approval = await _seed_gated_approval(db_session, org.id)

    response = await async_client.post(
        f"/v1/approvals/{approval.id}/decide",
        json={
            "decision": "approve",
            "approver": "dr_smith",
            "reviewer_role": "dea_authorized",
        },
    )
    assert response.status_code in (401, 403), response.text
    # If 403, the body must NOT be the W1.1 role-check envelope — that
    # would indicate the auth dep let the call through to the service.
    if response.status_code == 403:
        body = response.json()
        assert body.get("code") != "reviewer_credentials_insufficient", body

    # Approval untouched.
    refreshed = await db_session.get(Approval, approval.id)
    await db_session.refresh(refreshed)
    assert refreshed.status == "pending"
    assert refreshed.reviewed_below_threshold is False


# ── 409: second-decide idempotency ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_decide_second_caller_after_resolution_returns_409(
    async_client, org_and_key, db_session
):
    """409: two callers with correct role; first resolves, second
    observes the resolved row and gets 409 ``already approved``.

    Proves W1.1's role check did NOT regress A6.5's single-transaction
    atomicity — the resolved-row guard still fires before the role check
    on the second call, so a second correct-role caller doesn't get a
    duplicate vote in.
    """
    org, raw_key, _ = org_and_key
    approval = await _seed_gated_approval(db_session, org.id)
    headers = {"Authorization": f"Bearer {raw_key}"}
    body = {
        "decision": "approve",
        "approver": "dr_smith",
        "reviewer_role": "dea_authorized",
    }

    r1 = await async_client.post(
        f"/v1/approvals/{approval.id}/decide", json=body, headers=headers
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "approved"

    # Second caller with a DIFFERENT approver (so they don't trip the
    # dual-vote guard) — the resolved-row check should still 409 first.
    body2 = dict(body, approver="dr_other")
    r2 = await async_client.post(
        f"/v1/approvals/{approval.id}/decide", json=body2, headers=headers
    )
    assert r2.status_code == 409, r2.text
    assert "already" in r2.json()["detail"].lower()
