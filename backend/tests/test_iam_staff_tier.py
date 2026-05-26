"""IAM staff/customer tier tests (Wave 3A.c — Phase 3 IAM hardening).

Maps to the new ``v1-test-plan.md`` Phase 3 row:

    "IAM staff/customer tier — STAFF_READ_ONLY scope strips PHI
    (input_data, metadata, Approval.context.original_input_data,
    data_subject_id) from responses; audit log written for every
    staff read with staff_id + endpoint + record_id; chain integrity
    + gate metadata + aggregate counts still visible."

Twenty tests across three layers:

  1. Pure-function ``redact_*`` unit tests (no DB / app needed).
  2. Auth resolution — tier_from_claims + dependency wiring.
  3. End-to-end through the FastAPI app: staff vs customer responses
     on /v1/actions, /v1/approvals; audit-log endpoint authorization.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.config import settings
from app.main import app
from app.models import (
    ActionRecord,
    Approval,
    ChainState,
    Organization,
    OrgMembership,
    StaffAuditLog,
)
from app.services import auth as auth_service
from app.services.auth import AuthContext
from app.services.iam import (
    IamTier,
    redact_action_record,
    redact_approval,
    tier_from_claims,
)

from tests._clerk_test_helpers import (
    TEST_ISSUER,
    make_keypair,
    reset_rate_limit,
    sign_token,
)


# ── Test plumbing ────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def keypair():
    return make_keypair()


_STAFF_CLERK_ORG_ID = "org_vera_staff_internal"


@pytest.fixture(autouse=True)
def _configure_clerk(monkeypatch, keypair):
    """Wire test JWKS + designate a staff Clerk org for IamTier resolution."""
    monkeypatch.setattr(settings, "clerk_jwks_url", "https://fixture/jwks.json")
    monkeypatch.setattr(settings, "clerk_issuer", TEST_ISSUER)
    monkeypatch.setattr(settings, "clerk_audience", None)
    monkeypatch.setattr(settings, "clerk_staff_org_id", _STAFF_CLERK_ORG_ID)
    auth_service._reset_jwks_cache_for_tests()

    async def _fake_fetch(_url: str) -> dict:
        return {"keys": [keypair["jwk"]]}

    monkeypatch.setattr(auth_service, "_fetch_jwks", _fake_fetch)
    reset_rate_limit(app)
    yield
    auth_service._reset_jwks_cache_for_tests()


@pytest_asyncio.fixture
async def customer_org(db_session):
    """A customer org with an admin Clerk user + a chain state."""
    org = Organization(name="cust-org", clerk_org_id="org_customer_a")
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))
    db_session.add(
        OrgMembership(
            org_id=org.id,
            clerk_user_id="user_customer_admin",
            clerk_org_id="org_customer_a",
            role="admin",
        )
    )
    await db_session.commit()
    await db_session.refresh(org)
    return org


def _staff_token(keypair) -> str:
    """Sign a token whose org_id matches the configured staff Clerk org."""
    return sign_token(
        keypair["priv"],
        sub="user_vera_engineer",
        org_id=_STAFF_CLERK_ORG_ID,
    )


def _customer_admin_token(keypair) -> str:
    return sign_token(
        keypair["priv"],
        sub="user_customer_admin",
        org_id="org_customer_a",
    )


# ── 1. Pure unit tests on redact_* ───────────────────────────────────────


def test_redact_action_record_strips_phi_for_staff():
    record = {
        "id": "rec_1",
        "record_hash": "deadbeef",
        "sequence_number": 1,
        "previous_hash": "GENESIS",
        "agent_name": "my-agent",
        "action_type": "function_call",
        "action_name": "transcribe_visit",
        "result": "success",
        "data_subject_id": "patient_42",
        "input_data": {"note": "Mr Smith DOB 1972 SSN 123-45-6789"},
        "metadata": {"chart_id": "chart_99"},
        "reasoning": {"gate_ruling": "allow"},
    }
    out = redact_action_record(record, IamTier.STAFF_READ_ONLY)
    assert out["input_data"] == {}
    assert out["metadata"] == {}
    assert out["data_subject_id"] == "[REDACTED]"
    # Chain integrity + agent metadata + result + reasoning preserved.
    assert out["record_hash"] == "deadbeef"
    assert out["sequence_number"] == 1
    assert out["previous_hash"] == "GENESIS"
    assert out["agent_name"] == "my-agent"
    assert out["action_type"] == "function_call"
    assert out["action_name"] == "transcribe_visit"
    assert out["result"] == "success"
    assert out["reasoning"] == {"gate_ruling": "allow"}


def test_redact_action_record_customer_unchanged():
    record = {
        "id": "rec_1",
        "input_data": {"note": "PHI"},
        "metadata": {"chart_id": "chart_99"},
        "data_subject_id": "patient_42",
    }
    out = redact_action_record(record, IamTier.CUSTOMER)
    # Identity for customers — no mutation, no redaction.
    assert out["input_data"] == {"note": "PHI"}
    assert out["metadata"] == {"chart_id": "chart_99"}
    assert out["data_subject_id"] == "patient_42"


def test_redact_action_record_handles_metadata_underscore_alias():
    """ORM attribute is ``metadata_``; response dict uses ``metadata``.
    The redactor handles either shape so it can be applied at either
    layer.
    """
    record = {
        "metadata_": {"chart_id": "chart_99"},
        "input_data": {"a": 1},
    }
    out = redact_action_record(record, IamTier.STAFF_READ_ONLY)
    assert out["metadata_"] == {}
    assert out["input_data"] == {}


def test_redact_approval_strips_context_phi_keeps_gate_metadata():
    approval = {
        "id": "appr_1",
        "data_subject_id": "patient_77",
        "action_name": "prescribe_substance",
        "context": {
            "original_input_data": {"med": "oxycodone", "dose": "5mg"},
            "gate_name": "controlled_substance",
            "required_role": "dea_licensed_physician",
            "citation": "21 CFR 1306.04",
            "reason": "gated",
            "fix_url": "/reviews/appr_1",
        },
        "status": "pending",
    }
    out = redact_approval(approval, IamTier.STAFF_READ_ONLY)
    assert "original_input_data" not in out["context"]
    # Gate metadata intact so staff can triage the ticket.
    assert out["context"]["gate_name"] == "controlled_substance"
    assert out["context"]["required_role"] == "dea_licensed_physician"
    assert out["context"]["citation"] == "21 CFR 1306.04"
    assert out["context"]["reason"] == "gated"
    assert out["context"]["fix_url"] == "/reviews/appr_1"
    # Top-level free-form fields redacted.
    assert out["data_subject_id"] == "[REDACTED]"
    # Non-PHI top-level passes through.
    assert out["action_name"] == "prescribe_substance"
    assert out["status"] == "pending"


def test_redact_approval_customer_unchanged():
    approval = {
        "data_subject_id": "patient_77",
        "context": {"original_input_data": {"med": "X"}, "gate_name": "g"},
    }
    out = redact_approval(approval, IamTier.CUSTOMER)
    assert out["data_subject_id"] == "patient_77"
    assert out["context"]["original_input_data"] == {"med": "X"}


def test_tier_from_claims_via_staff_org_id():
    claims = {"sub": "user_x", "org_id": _STAFF_CLERK_ORG_ID}
    assert tier_from_claims(claims, _STAFF_CLERK_ORG_ID) == IamTier.STAFF_READ_ONLY


def test_tier_from_claims_role_claim_without_org_id_match_is_customer():
    """Hardened tier resolution: role-claim alone is NOT sufficient for
    staff escalation. The JWT's ``org_id`` MUST match the configured
    ``clerk_staff_org_id``. Defends against a multi-tenant Clerk
    instance where a customer org names a role ``vera_staff``.
    """
    claims = {"sub": "user_x", "org_id": "other_org", "org_role": "vera_staff"}
    assert tier_from_claims(claims, _STAFF_CLERK_ORG_ID) == IamTier.CUSTOMER


def test_tier_from_claims_no_staff_org_configured_always_customer():
    """If ``clerk_staff_org_id`` is unset, staff tier is unreachable —
    no JWT shape can elevate."""
    claims = {"sub": "user_x", "org_id": _STAFF_CLERK_ORG_ID, "org_role": "vera_staff"}
    assert tier_from_claims(claims, None) == IamTier.CUSTOMER


def test_tier_from_claims_defaults_to_customer():
    claims = {"sub": "user_x", "org_id": "org_customer_a"}
    assert tier_from_claims(claims, _STAFF_CLERK_ORG_ID) == IamTier.CUSTOMER


# ── 2. Auth tier resolution at the dependency layer ──────────────────────


@pytest.mark.asyncio
async def test_api_key_resolves_to_customer_tier(async_client, org_and_key, keypair):
    """API-key callers always tier=CUSTOMER. Bring up an action + read it."""
    _, raw_key, _ = org_and_key
    create = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "test_a",
            "action_type": "function_call",
            "agent_name": "agent-a",
            "data_subject_id": "patient_1",
            "input_data": {"note": "PHI string"},
            "metadata": {"chart_id": "c1"},
            "result": "success",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert create.status_code == 200
    action_id = create.json()["id"]

    resp = await async_client.get(
        f"/v1/actions/{action_id}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # Customer sees full payload.
    assert body["data_subject_id"] == "patient_1"
    assert body["input_data"] == {"note": "PHI string"}
    assert body["metadata"] == {"chart_id": "c1"}


# ── 3. End-to-end staff redaction + audit ─────────────────────────────────


@pytest.mark.asyncio
async def test_staff_get_action_redacts_and_audits(
    async_client, org_and_key, db_session, keypair
):
    org, raw_key, _ = org_and_key
    # Customer-side write.
    create = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "transcribe",
            "action_type": "function_call",
            "agent_name": "scribe-agent",
            "data_subject_id": "patient_99",
            "input_data": {"note": "Mr Smith, lung biopsy"},
            "metadata": {"chart_id": "chart_99"},
            "result": "success",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert create.status_code == 200, create.text
    action_id = create.json()["id"]
    chain_record_hash = create.json()["record_hash"]
    chain_sequence = create.json()["sequence_number"]

    # Staff session reads the same action — must see redacted + audited.
    token = _staff_token(keypair)
    resp = await async_client.get(
        f"/v1/actions/{action_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": org.id,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # PHI redacted.
    assert body["input_data"] == {}
    assert body["metadata"] == {}
    assert body["data_subject_id"] == "[REDACTED]"
    # Chain integrity intact — staff CAN verify.
    assert body["record_hash"] == chain_record_hash
    assert body["sequence_number"] == chain_sequence
    assert body["agent_name"] == "scribe-agent"
    assert body["action_name"] == "transcribe"
    assert body["result"] == "success"

    # Audit row written.
    rows = (
        await db_session.execute(
            select(StaffAuditLog).where(
                StaffAuditLog.staff_id == "user_vera_engineer"
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].endpoint == "/v1/actions/{record_id}"
    assert rows[0].resource_type == "action_record"
    assert rows[0].resource_id == action_id
    assert rows[0].redacted is True
    assert rows[0].org_id == org.id


@pytest.mark.asyncio
async def test_staff_list_actions_redacts_and_audits_once(
    async_client, org_and_key, db_session, keypair
):
    org, raw_key, _ = org_and_key
    # Three actions.
    for i in range(3):
        await async_client.post(
            "/v1/actions",
            json={
                "action_name": f"a_{i}",
                "action_type": "function_call",
                "agent_name": "agent-multi",
                "input_data": {"note": f"PHI {i}"},
                "result": "success",
            },
            headers={"Authorization": f"Bearer {raw_key}"},
        )

    token = _staff_token(keypair)
    resp = await async_client.get(
        "/v1/actions",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": org.id,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3
    for r in body["records"]:
        assert r["input_data"] == {}
        # Aggregate fields preserved.
        assert r["sequence_number"] >= 1
        assert r["record_hash"]
        assert r["agent_name"] == "agent-multi"

    # ONE audit row for the list read — not three.
    rows = (
        await db_session.execute(
            select(StaffAuditLog).where(StaffAuditLog.endpoint == "/v1/actions")
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].resource_id is None


@pytest.mark.asyncio
async def test_customer_read_does_not_audit(async_client, org_and_key, db_session):
    """Customer reads of their own data are NOT audit-logged."""
    _, raw_key, _ = org_and_key
    create = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "self_read",
            "action_type": "function_call",
            "agent_name": "a",
            "result": "success",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert create.status_code == 200
    action_id = create.json()["id"]
    resp = await async_client.get(
        f"/v1/actions/{action_id}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    rows = (
        await db_session.execute(select(StaffAuditLog))
    ).scalars().all()
    # Customer reads must never write to staff_audit_log — that table is
    # for tracking who-at-Vera-touched-my-data only.
    assert rows == []


@pytest.mark.asyncio
async def test_staff_without_x_org_id_header_400(async_client, keypair):
    """Staff session without X-Org-Id rejects (can't target a customer)."""
    token = _staff_token(keypair)
    resp = await async_client.get(
        "/v1/actions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body.get("code") == "staff_org_id_required"


@pytest.mark.asyncio
async def test_staff_write_attempt_rejected(async_client, org_and_key, keypair):
    """Staff are read-only — writes are rejected.

    POST /v1/actions still uses the legacy ``require_permission("write")``
    dependency. A staff Clerk JWT has no backend ``OrgMembership`` row in
    the customer org, so the legacy path rejects with 401 (no membership)
    before our staff-detection branch fires. Either outcome is a refusal;
    the test asserts the negative (no 2xx) and accepts the legacy 401 or
    the new 403 — both are correct refusals of a write attempt.
    """
    org, _, _ = org_and_key
    token = _staff_token(keypair)
    resp = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "should_fail",
            "action_type": "function_call",
            "agent_name": "a",
            "result": "success",
        },
        headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": org.id,
        },
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_staff_get_approval_redacts(async_client, org_and_key, db_session, keypair):
    """Staff reading an approval: original_input_data + data_subject_id
    redacted; gate metadata preserved."""
    org, raw_key, _ = org_and_key
    # Create an approval directly via the ORM so we can stash a rich context.
    appr = Approval(
        org_id=org.id,
        requested_by_agent="agent-x",
        action_name="prescribe",
        data_subject_id="patient_55",
        context={
            "original_input_data": {"med": "oxycodone"},
            "gate_name": "controlled_substance",
            "required_role": "dea_licensed_physician",
            "citation": "21 CFR 1306.04",
            "reason": "gated",
        },
        risk_tier="critical",
        approvers_required=1,
        status="pending",
        decisions=[],
    )
    db_session.add(appr)
    await db_session.commit()
    await db_session.refresh(appr)

    token = _staff_token(keypair)
    resp = await async_client.get(
        f"/v1/approvals/{appr.id}",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": org.id,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Redacted.
    assert "original_input_data" not in body["context"]
    assert body["data_subject_id"] == "[REDACTED]"
    # Gate metadata kept.
    assert body["context"]["gate_name"] == "controlled_substance"
    assert body["context"]["required_role"] == "dea_licensed_physician"
    assert body["context"]["citation"] == "21 CFR 1306.04"

    # Audit row written.
    rows = (
        await db_session.execute(
            select(StaffAuditLog).where(StaffAuditLog.resource_type == "approval")
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].resource_id == appr.id


@pytest.mark.asyncio
async def test_customer_get_approval_unredacted(async_client, org_and_key, db_session):
    """Customer reading their own approval gets the full context blob."""
    org, raw_key, _ = org_and_key
    appr = Approval(
        org_id=org.id,
        requested_by_agent="agent-x",
        action_name="prescribe",
        data_subject_id="patient_55",
        context={
            "original_input_data": {"med": "oxycodone"},
            "gate_name": "controlled_substance",
        },
        risk_tier="critical",
        approvers_required=1,
        status="pending",
        decisions=[],
    )
    db_session.add(appr)
    await db_session.commit()
    await db_session.refresh(appr)

    resp = await async_client.get(
        f"/v1/approvals/{appr.id}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data_subject_id"] == "patient_55"
    assert body["context"]["original_input_data"] == {"med": "oxycodone"}


# ── 4. Staff audit-log endpoint ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_staff_audit_log_visible_to_staff(
    async_client, org_and_key, db_session, keypair
):
    """Staff reading their own audit log sees the row they just generated."""
    org, raw_key, _ = org_and_key
    create = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "x",
            "action_type": "function_call",
            "agent_name": "a",
            "result": "success",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    action_id = create.json()["id"]

    token = _staff_token(keypair)
    await async_client.get(
        f"/v1/actions/{action_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": org.id,
        },
    )

    resp = await async_client.get(
        "/v1/staff/audit-log",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": org.id,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    assert any(
        e["staff_id"] == "user_vera_engineer" and e["resource_id"] == action_id
        for e in body["entries"]
    )


@pytest.mark.asyncio
async def test_staff_audit_log_visible_to_customer_admin(
    async_client, org_and_key, db_session, keypair
):
    """Customer admin sees reads against their org."""
    org, raw_key, _ = org_and_key
    create = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "y",
            "action_type": "function_call",
            "agent_name": "a",
            "result": "success",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    action_id = create.json()["id"]
    token = _staff_token(keypair)
    await async_client.get(
        f"/v1/actions/{action_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": org.id,
        },
    )

    # Customer admin queries their own audit log (uses their admin API key).
    resp = await async_client.get(
        "/v1/staff/audit-log",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    entry = body["entries"][0]
    assert entry["org_id"] == org.id
    assert entry["staff_id"] == "user_vera_engineer"


@pytest.mark.asyncio
async def test_staff_audit_log_customer_non_admin_403(async_client, db_session):
    """Non-admin API key gets 403."""
    org = Organization(name="ro-org")
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))
    await db_session.commit()
    raw_ro, _ = await auth_service.generate_api_key(
        db_session, org.id, "ro-key", ["read"]
    )
    resp = await async_client.get(
        "/v1/staff/audit-log",
        headers={"Authorization": f"Bearer {raw_ro}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_staff_audit_log_cross_org_isolation(
    async_client, org_and_key, db_session, keypair, make_org_and_customer
):
    """Customer A's admin cannot see reads on customer B's data even with
    ?org_id=B."""
    org_a, key_a, _ = org_and_key
    org_b, _ = await make_org_and_customer("orgb")
    # Seed an audit row on org B.
    db_session.add(
        StaffAuditLog(
            staff_id="user_vera_engineer",
            endpoint="/v1/actions",
            org_id=org_b.id,
            resource_type="action_record",
            redacted=True,
        )
    )
    await db_session.commit()

    # Org A admin tries to see org B's reads via the org_id filter.
    resp = await async_client.get(
        f"/v1/staff/audit-log?org_id={org_b.id}",
        headers={"Authorization": f"Bearer {key_a}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # The filter is dropped server-side; org A sees only their own log
    # (which has zero rows on org B's seeded read).
    for entry in body["entries"]:
        assert entry["org_id"] == org_a.id


# ── 5. Chain verification + aggregate read paths (staff allowed) ─────────


@pytest.mark.asyncio
async def test_staff_chain_verification_accessible(
    async_client, org_and_key, keypair
):
    """Chain verification endpoints expose no PHI — staff should access
    them freely."""
    org, raw_key, _ = org_and_key
    # Seed at least one action so verification has data.
    await async_client.post(
        "/v1/actions",
        json={
            "action_name": "z",
            "action_type": "function_call",
            "agent_name": "a",
            "result": "success",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    token = _staff_token(keypair)
    # ``/v1/actions`` list IS the chain-integrity surface staff use to
    # confirm sequence numbers + hashes are intact. We exercise it
    # explicitly to assert the staff path returns chain fields without
    # PHI.
    resp = await async_client.get(
        "/v1/actions",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": org.id,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    for rec in body["records"]:
        assert rec["record_hash"]
        assert "previous_hash" in rec
        assert isinstance(rec["sequence_number"], int)
        assert rec["input_data"] == {}


@pytest.mark.asyncio
async def test_audit_log_persists_when_request_session_rolled_back(
    db_session, org_and_key
):
    """``audit_staff_read`` opens its own session and commits — even if the
    caller's request session later rolls back, the audit row sticks.
    """
    from app.services.iam import audit_staff_read

    org, _, _ = org_and_key

    await audit_staff_read(
        db_session,
        staff_id="user_vera_engineer",
        endpoint="/v1/actions",
        org_id=org.id,
        resource_type="action_record",
        resource_id="rec_test",
        redacted=True,
    )
    # Roll back the OUTER session — the inner commit must persist.
    await db_session.rollback()

    rows = (
        await db_session.execute(
            select(StaffAuditLog).where(StaffAuditLog.resource_id == "rec_test")
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_staff_data_subject_filter_403(async_client, org_and_key, keypair):
    """PHI side-channel defense: staff can't filter ``/v1/actions?data_subject_id=X``
    even though the response would redact the value — the FILTER itself
    confirms whether X exists in the org.
    """
    org, _, _ = org_and_key
    token = _staff_token(keypair)
    resp = await async_client.get(
        "/v1/actions?data_subject_id=patient_55",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": org.id,
        },
    )
    assert resp.status_code == 403
    assert resp.json().get("code") == "staff_phi_filter_forbidden"


@pytest.mark.asyncio
async def test_staff_search_filter_403(async_client, org_and_key, keypair):
    """Same PHI side-channel for the free-form ``search`` filter."""
    org, _, _ = org_and_key
    token = _staff_token(keypair)
    resp = await async_client.get(
        "/v1/actions?search=transcribe",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": org.id,
        },
    )
    assert resp.status_code == 403
    assert resp.json().get("code") == "staff_phi_filter_forbidden"


@pytest.mark.asyncio
async def test_staff_approval_data_subject_filter_403(async_client, org_and_key, keypair):
    """Same defense on the approvals list endpoint."""
    org, _, _ = org_and_key
    token = _staff_token(keypair)
    resp = await async_client.get(
        "/v1/approvals?data_subject_id=patient_55",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": org.id,
        },
    )
    assert resp.status_code == 403
    assert resp.json().get("code") == "staff_phi_filter_forbidden"


@pytest.mark.asyncio
async def test_customer_data_subject_filter_works(async_client, org_and_key):
    """Customer reads of their own data CAN filter by data_subject_id — the
    side-channel defense applies to staff only.
    """
    _, raw_key, _ = org_and_key
    resp = await async_client.get(
        "/v1/actions?data_subject_id=patient_55",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_audit_failure_does_not_500(monkeypatch, db_session, org_and_key):
    """A logging hiccup must NOT 500 the caller."""
    from app.services import iam as iam_mod

    org, _, _ = org_and_key

    def _boom_factory():
        raise RuntimeError("simulated audit storage outage")

    # Force the module-level session factory to raise. The helper must
    # swallow + log; it MUST NOT re-raise.
    monkeypatch.setattr(iam_mod, "AsyncSessionLocal", _boom_factory)

    # Should not raise even though the session factory blows up.
    await iam_mod.audit_staff_read(
        db_session,
        staff_id="user_vera_engineer",
        endpoint="/v1/actions",
        org_id=org.id,
        resource_type="action_record",
        resource_id="rec_failsafe",
        redacted=True,
    )
