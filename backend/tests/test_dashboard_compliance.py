"""Tests for the /v1/dashboard/compliance/* read-only endpoints
(Phase 4a, F1+F3 — backend half of the compliance reviewer wedge)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import pytest_asyncio

from app.config import settings
from app.models import (
    ActionRecord,
    Approval,
    ChainState,
    Organization,
    OrgMembership,
    PolicyViolation,
)
from app.services import auth as auth_service
from app.main import app

from tests._clerk_test_helpers import (
    TEST_ISSUER,
    make_keypair,
    reset_rate_limit,
    sign_token,
)


@pytest.fixture(scope="module")
def keypair():
    return make_keypair()


@pytest.fixture(autouse=True)
def _configure_clerk(monkeypatch, keypair):
    monkeypatch.setattr(settings, "clerk_jwks_url", "https://fixture/jwks.json")
    monkeypatch.setattr(settings, "clerk_issuer", TEST_ISSUER)
    monkeypatch.setattr(settings, "clerk_audience", None)
    auth_service._reset_jwks_cache_for_tests()

    async def _fake_fetch(_url: str) -> dict:
        return {"keys": [keypair["jwk"]]}

    monkeypatch.setattr(auth_service, "_fetch_jwks", _fake_fetch)
    reset_rate_limit(app)
    yield
    auth_service._reset_jwks_cache_for_tests()


async def _make_action_record(db_session, *, org_id: str, seq: int, result: str = "failure"):
    """Build a minimal ActionRecord row. The chain hashing service expects
    specific shapes for normal inserts, but these tests only care about
    the read path so we bypass it and store directly."""
    rec = ActionRecord(
        org_id=org_id,
        sequence_number=seq,
        previous_hash="x" * 64,
        record_hash="y" * 64,
        authorized_by="test",
        agent_name="agent-1",
        action_type="function_call",
        action_name=f"act-{seq}",
        action_timestamp=datetime.utcnow(),
        result=result,
        input_data={},
        policies_applied=[],
        environment={},
        reasoning={},
        outcome={},
        metadata_={},
        delegation_chain=[],
    )
    db_session.add(rec)
    await db_session.commit()
    return rec


@pytest_asyncio.fixture
async def seeded(db_session, db_engine):
    """Build an org with admin + compliance_reviewer + developer
    memberships, plus a smattering of records to populate the summary."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    from app import database as db_mod

    org = Organization(name="compliance-data-org", clerk_org_id="org_cmp_data")
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))
    db_session.add_all([
        OrgMembership(
            org_id=org.id,
            clerk_user_id="user_admin_cmp",
            clerk_org_id="org_cmp_data",
            role="admin",
        ),
        OrgMembership(
            org_id=org.id,
            clerk_user_id="user_dev_cmp",
            clerk_org_id="org_cmp_data",
            role="developer",
        ),
        OrgMembership(
            org_id=org.id,
            clerk_user_id="user_compliance_cmp",
            clerk_org_id="org_cmp_data",
            role="compliance_reviewer",
        ),
    ])

    # 2 failures (should show up in recent), 1 success (should not)
    await _make_action_record(db_session, org_id=org.id, seq=1, result="failure")
    await _make_action_record(db_session, org_id=org.id, seq=2, result="success")
    await _make_action_record(db_session, org_id=org.id, seq=3, result="blocked")

    # 1 high-risk approval, 1 already approved
    db_session.add_all([
        Approval(
            org_id=org.id,
            requested_by_agent="agent-x",
            action_name="risky",
            risk_tier="high",
            status="pending",
        ),
        Approval(
            org_id=org.id,
            requested_by_agent="agent-x",
            action_name="lower",
            risk_tier="medium",
            status="approved",
            decisions=[{"decided_by": "alice"}],
            resolved_at=datetime.utcnow(),
        ),
    ])

    # 1 violation
    db_session.add(
        PolicyViolation(
            org_id=org.id,
            severity="high",
            context={"reason": "test"},
        )
    )
    await db_session.commit()

    # Share AsyncSessionLocal so audit writes hit the same in-memory DB.
    test_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    original = db_mod.AsyncSessionLocal
    db_mod.AsyncSessionLocal = test_factory
    try:
        yield {"org_id": org.id, "clerk_org_id": "org_cmp_data"}
    finally:
        db_mod.AsyncSessionLocal = original


def _token(role: str, keypair, seeded) -> str:
    sub = {
        "admin": "user_admin_cmp",
        "developer": "user_dev_cmp",
        "compliance_reviewer": "user_compliance_cmp",
    }[role]
    return sign_token(keypair["priv"], sub=sub, org_id=seeded["clerk_org_id"])


@pytest.mark.asyncio
async def test_summary_returns_expected_shape(async_client, keypair, seeded):
    token = _token("compliance_reviewer", keypair, seeded)
    resp = await async_client.get(
        "/v1/dashboard/compliance/summary?days=30",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["window_days"] == 30
    assert body["high_risk_decisions"] == 1
    assert body["hitl_approvals_taken"] == 1
    assert body["policy_violations"] == 1


@pytest.mark.asyncio
async def test_recent_returns_only_failures_and_blocked(
    async_client, keypair, seeded
):
    token = _token("admin", keypair, seeded)
    resp = await async_client.get(
        "/v1/dashboard/compliance/recent?limit=5",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    results = sorted(r["result"] for r in body["records"])
    assert results == ["blocked", "failure"], body
    assert body["count"] == 2


@pytest.mark.asyncio
async def test_review_trail_developer_denied(async_client, keypair, seeded):
    token = _token("developer", keypair, seeded)
    resp = await async_client.get(
        "/v1/dashboard/compliance/review-trail",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_review_trail_admin_can_view(async_client, keypair, seeded):
    token = _token("admin", keypair, seeded)
    resp = await async_client.get(
        "/v1/dashboard/compliance/review-trail",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "records" in body
    assert "count" in body


@pytest.mark.asyncio
async def test_review_trail_reflects_compliance_activity(
    async_client, keypair, seeded
):
    """After a compliance_reviewer hits an audited route, an admin pulling
    review-trail must see the row."""
    reviewer = _token("compliance_reviewer", keypair, seeded)
    hit = await async_client.get(
        "/v1/dashboard/actions?limit=5",
        headers={"Authorization": f"Bearer {reviewer}"},
    )
    assert hit.status_code == 200

    admin = _token("admin", keypair, seeded)
    resp = await async_client.get(
        "/v1/dashboard/compliance/review-trail",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    actions = [r["action"] for r in body["records"]]
    assert "/v1/dashboard/actions" in actions


@pytest.mark.asyncio
async def test_exports_endpoint_lists_export_hits(
    async_client, keypair, seeded
):
    """A compliance_reviewer hitting /v1/dashboard/export/csv lands in
    the compliance review log; the exports endpoint surfaces it."""
    reviewer = _token("compliance_reviewer", keypair, seeded)
    csv_hit = await async_client.get(
        "/v1/dashboard/export/csv",
        headers={"Authorization": f"Bearer {reviewer}"},
    )
    assert csv_hit.status_code == 200

    admin = _token("admin", keypair, seeded)
    resp = await async_client.get(
        "/v1/dashboard/compliance/exports",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    paths = [e["path"] for e in body["exports"]]
    assert any(p.endswith("/export/csv") for p in paths)
